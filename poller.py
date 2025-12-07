import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

import time
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os
import requests
import logging
import sys

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'channels.db')
POLL_INTERVAL = 60 # seconds

# --- Helper function (boot time only) ---
def get_startup_log_level():
    """Reads the log level from the DB *before* the logger is configured."""
    level_str = 'info' # Default
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT value FROM settings WHERE key = 'log_level'").fetchone()
        conn.close()
        if row and row[0] == 'error':
            level_str = 'error'
    except Exception as e:
        print(f"[Poller-Boot-Warning] Could not read log level from DB: {e}")
        pass
    
    print(f"[Poller-Boot] Setting log level to '{level_str}'.")
    return logging.ERROR if level_str == 'error' else logging.INFO

# --- START Logging Config (Dynamic) ---
log_level = get_startup_log_level()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s %(levelname)s [Poller] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logging.warning("--------------------------------------")
logging.warning(f"Poller service starting... (Log Level: {logging.getLevelName(log_level)})")
logging.warning("--------------------------------------")
# --- END Logging Config ---


# --- Twitch API Helper Functions ---
TWITCH_AUTH_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_API_URL_USERS = 'https://api.twitch.tv/helix/users'
TWITCH_API_URL_VIDEOS = 'https://api.twitch.tv/helix/videos'
TWITCH_API_URL_STREAMS = 'https://api.twitch.tv/helix/streams'

# Cache for tokens: Key=(client_id, client_secret), Value={'token': str, 'expires': float}
token_cache = {}

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_base_settings():
    """Fetches global settings that are not user-specific."""
    conn = get_db_connection()
    settings_raw = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in settings_raw}
    
    settings.setdefault('vod_enabled', 'false')
    settings.setdefault('vod_count_per_channel', '5')
    
    settings['vod_enabled'] = settings['vod_enabled'] == 'true'
    try:
        settings['vod_count_per_channel'] = int(settings['vod_count_per_channel'])
    except ValueError:
        settings['vod_count_per_channel'] = 5
    
    return settings

def get_twitch_app_token(client_id, client_secret):
    """Fetches a token for a specific ID/Secret pair. Caches result."""
    global token_cache
    
    cache_key = (client_id, client_secret)
    cached = token_cache.get(cache_key)
    
    # Check cache validity
    if cached and time.time() < cached['expires']:
        return cached['token']

    logging.info(f"[Poller-Auth] Requesting new token for Client ID {client_id[:4]}...")
    try:
        response = requests.post(
            TWITCH_AUTH_URL,
            params={
                'client_id': client_id,
                'client_secret': client_secret,
                'grant_type': 'client_credentials'
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        token = data['access_token']
        expires = time.time() + data['expires_in'] - 60
        
        token_cache[cache_key] = {'token': token, 'expires': expires}
        logging.info(f"[Poller-Auth] Token acquired for Client ID {client_id[:4]}...")
        return token
    except Exception as e:
        logging.error(f"[Poller-Auth] ERROR: Failed to get Twitch token for ID {client_id[:4]}...: {e}")
        return None

def get_user_ids(token, client_id, login_names):
    if not login_names:
        return {}
    
    user_id_map = {}
    for i in range(0, len(login_names), 100):
        chunk = login_names[i:i+100]
        try:
            headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
            params = [('login', name) for name in chunk]
            
            response = requests.get(TWITCH_API_URL_USERS, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            for user in data:
                user_id_map[user['login']] = user['id']
            
        except Exception as e:
            logging.error(f"[Poller-API] ERROR: Failed to get Twitch User IDs: {e}")
    
    return user_id_map

def get_channel_vods(token, client_id, user_id, vod_count):
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        params = {
            'user_id': user_id,
            'type': 'archive', 
            'first': vod_count
        }
        
        response = requests.get(TWITCH_API_URL_VIDEOS, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        logging.error(f"[Poller-API] ERROR: Failed to get VODs for {user_id}: {e}")
        return []

def get_live_streams_info(token, client_id, user_id_map):
    if not user_id_map:
        return {}
        
    live_stream_map = {}
    user_ids = list(user_id_map.values())
    
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i:i+100]
            params = [('user_id', user_id) for user_id in chunk]
            
            response = requests.get(TWITCH_API_URL_STREAMS, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            for stream in data:
                live_stream_map[stream['user_id']] = {
                    "title": stream.get('title', ''),
                    "game": stream.get('game_name', '')
                }
                
    except Exception as e:
        logging.error(f"[Poller-API] ERROR: Failed to get stream info: {e}")
    
    return live_stream_map

# --- Main Poller Function ---
def update_database():
    logging.info("[Poller] Starting update cycle...")
    
    settings = get_base_settings()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Get all users who have credentials
        users_with_creds = conn.execute("SELECT id, username, client_id, client_secret FROM users WHERE client_id IS NOT NULL AND client_secret IS NOT NULL").fetchall()
        
        all_monitored_logins = set()
        
        # 2. Iterate each user and poll
        for user in users_with_creds:
            uid = user['id']
            username = user['username']
            c_id = user['client_id']
            c_secret = user['client_secret']
            
            # Fetch channels for this user
            user_channels = conn.execute("SELECT login_name FROM channels WHERE user_id = ?", (uid,)).fetchall()
            login_names = [row['login_name'] for row in user_channels]
            
            if not login_names:
                continue

            all_monitored_logins.update(login_names)
            
            logging.info(f"[Poller] Processing {len(login_names)} channels for user '{username}'...")
            
            # Authenticate
            token = get_twitch_app_token(c_id, c_secret)
            if not token:
                logging.warning(f"[Poller] Skipping user '{username}': Could not auth.")
                continue
                
            # Resolve IDs
            user_id_map = get_user_ids(token, c_id, login_names)
            
            # Poll Live Status
            live_data = get_live_streams_info(token, c_id, user_id_map)
            
            # Update Live Streams Table (Shared Cache)
            # We iterate through this user's channels only
            user_id_to_login = {v: k for k, v in user_id_map.items()}
            
            for login_name in login_names:
                twitch_user_id = user_id_map.get(login_name)
                stream_info = live_data.get(twitch_user_id) if twitch_user_id else None
                
                epg_id = f"{login_name}.tv"
                
                if stream_info: # LIVE
                    display_name, is_live, stream_title, stream_game = login_name.title(), True, stream_info['title'], stream_info['game']
                else: # OFFLINE
                    display_name, is_live, stream_title, stream_game = f"[Offline] {login_name.title()}", False, None, None
                
                # We use INSERT OR REPLACE. Since multiple users might watch same channel,
                # last one wins. This is fine as data should be identical.
                cursor.execute(
                    """INSERT OR REPLACE INTO live_streams 
                       (login_name, epg_channel_id, display_name, is_live, stream_title, stream_game) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (login_name, epg_id, display_name, is_live, stream_title, stream_game)
                )

            # Poll VODs (if enabled)
            if settings['vod_enabled']:
                process_vods(cursor, token, c_id, login_names, user_id_map, settings['vod_count_per_channel'])
                
            # Yield to other greenlets
            gevent.sleep(0.1)

        # 3. Garbage Collection
        # streams that are in live_streams but NOT in all_monitored_logins should be removed
        if all_monitored_logins:
            placeholders = ','.join(['?'] * len(all_monitored_logins))
            cursor.execute(f"DELETE FROM live_streams WHERE login_name NOT IN ({placeholders})", list(all_monitored_logins))
        else:
            cursor.execute("DELETE FROM live_streams")

        conn.commit()
        logging.info("[Poller] Update cycle complete.")

    except Exception as e:
        logging.critical(f"[Poller] FATAL ERROR during update cycle: {e}")
        conn.rollback()
    finally:
        conn.close()

def process_vods(cursor, token, client_id, login_names, user_id_map, vod_count):
    """Helper to process VODs for a specific user session."""
    
    for login_name in login_names:
        user_id = user_id_map.get(login_name)
        if not user_id: continue
        
        vods = get_channel_vods(token, client_id, user_id, vod_count)
        if not vods: continue

        vod_category = f"{login_name.title()} VODs"
        
        for vod in vods:
            thumbnail = vod['thumbnail_url'].replace('%{width}', '640').replace('%{height}', '360')
            cursor.execute(
                "INSERT OR REPLACE INTO vod_streams (vod_id, channel_login, title, created_at, category, thumbnail_url) VALUES (?, ?, ?, ?, ?, ?)",
                (vod['id'], login_name, vod['title'], vod['created_at'], vod_category, thumbnail)
            )
            
# --- Main run loop ---
if __name__ == "__main__":
    gevent.sleep(5) # Wait for DB to be ready
    while True:
        try:
            update_database()
        except Exception as e:
            logging.critical(f"[Poller] Unhandled exception in main loop: {e}")
            
        logging.info(f"Next poll run in {POLL_INTERVAL} seconds.")
        gevent.sleep(POLL_INTERVAL)