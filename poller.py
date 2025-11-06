import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

import time
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os
import requests

# --- Configuration ---
DB_PATH = '/data/channels.db'
POLL_INTERVAL = 60 # seconds

# --- Twitch API Helper Functions ---
TWITCH_AUTH_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_API_URL_USERS = 'https://api.twitch.tv/helix/users'
TWITCH_API_URL_VIDEOS = 'https://api.twitch.tv/helix/videos'
TWITCH_API_URL_STREAMS = 'https://api.twitch.tv/helix/streams' # NEW: Stream info endpoint
current_app_token = None
token_expires_at = 0

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_settings():
    conn = get_db_connection()
    settings_raw = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in settings_raw}
    
    settings.setdefault('vod_enabled', 'false')
    settings.setdefault('twitch_client_id', '')
    settings.setdefault('twitch_client_secret', '')
    settings.setdefault('vod_count_per_channel', '5')
    
    settings['vod_enabled'] = settings['vod_enabled'] == 'true'
    try:
        settings['vod_count_per_channel'] = int(settings['vod_count_per_channel'])
    except ValueError:
        settings['vod_count_per_channel'] = 5
        
    return settings

def get_twitch_app_token(client_id, client_secret):
    global current_app_token, token_expires_at
    
    if current_app_token and time.time() < token_expires_at:
        return current_app_token

    print("[Poller-VOD]: No valid token. Requesting new Twitch App Access Token...")
    try:
        response = requests.post(
            TWITCH_AUTH_URL,
            params={
                'client_id': client_id,
                'client_secret': client_secret,
                'grant_type': 'client_credentials'
            }
        )
        response.raise_for_status()
        data = response.json()
        
        current_app_token = data['access_token']
        token_expires_at = time.time() + data['expires_in'] - 60
        
        print("[Poller-VOD]: Successfully acquired new token.")
        return current_app_token
    except Exception as e:
        print(f"[Poller-VOD] ERROR: Failed to get Twitch token: {e}")
        return None

def get_user_ids(token, client_id, login_names):
    if not login_names:
        return {}
    
    user_id_map = {}
    for i in range(0, len(login_names), 100):
        chunk = login_names[i:i+100]
        print(f"[Poller-VOD]: Fetching User IDs for {len(chunk)} channels...")
        try:
            headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
            params = [('login', name) for name in chunk]
            
            response = requests.get(TWITCH_API_URL_USERS, headers=headers, params=params)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            for user in data:
                user_id_map[user['login']] = user['id']
            
        except Exception as e:
            print(f"[Poller-VOD] ERROR: Failed to get User IDs: {e}")
    
    return user_id_map

def get_channel_vods(token, client_id, user_id, vod_count):
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        params = {
            'user_id': user_id,
            'type': 'archive', 
            'first': vod_count
        }
        
        response = requests.get(TWITCH_API_URL_VIDEOS, headers=headers, params=params)
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        print(f"[Poller-VOD] ERROR: Failed to get VODs for user {user_id}: {e}")
        return []

def get_live_streams_info(token, client_id, user_id_map):
    """Fetches live stream info (title, game) from the Twitch API."""
    if not user_id_map:
        return {}
        
    print(f"[Poller-Live]: Fetching stream info for {len(user_id_map)} channels...")
    live_stream_map = {}
    user_ids = list(user_id_map.values())
    
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i:i+100]
            params = [('user_id', user_id) for user_id in chunk]
            
            response = requests.get(TWITCH_API_URL_STREAMS, headers=headers, params=params)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            for stream in data:
                live_stream_map[stream['user_id']] = {
                    "title": stream.get('title', ''),
                    "game": stream.get('game_name', '')
                }
                
    except Exception as e:
        print(f"[Poller-Live] ERROR: Failed to get stream info: {e}")
    
    return live_stream_map


# --- Main Poller Function ---

def update_database():
    print("[Poller]: Starting database update cycle...")
    
    settings = get_settings()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        channels = conn.execute('SELECT id, login_name FROM channels').fetchall()
        login_names = [row['login_name'] for row in channels]
        
        # --- 1. Get Token and User IDs (needed for Live and VODs) ---
        token = None
        user_id_map = {}
        if (settings['vod_enabled'] or len(channels) > 0) and settings['twitch_client_id'] and settings['twitch_client_secret']:
            token = get_twitch_app_token(settings['twitch_client_id'], settings['twitch_client_secret'])
            if token:
                user_id_map = get_user_ids(token, settings['twitch_client_id'], login_names)
        
        # --- 2. Live Stream Check (NEW LOGIC) ---
        print(f"[Poller-Live]: Checking status for {len(login_names)} live channels...")
        live_stream_info_map = {}
        if token and user_id_map:
            # Swap User-IDs to Login-Names for easier reference
            login_to_user_id = user_id_map
            user_id_to_login = {v: k for k, v in user_id_map.items()}
            
            # Query the API for live stream info
            live_stream_api_data = get_live_streams_info(token, settings['twitch_client_id'], user_id_map)
            
            # Translate the API response (key is user_id) into our map (key is login_name)
            for user_id, info in live_stream_api_data.items():
                login_name = user_id_to_login.get(user_id)
                if login_name:
                    live_stream_info_map[login_name] = info

        live_count = len(live_stream_info_map)
        
        # Update all channels in the DB
        for channel in channels:
            login_name = channel['login_name']
            epg_id = f"{login_name}.tv" # Unique EPG-ID (e.g., "gronkh.tv")
            
            stream_info = live_stream_info_map.get(login_name)
            
            if stream_info: # Channel is LIVE
                display_name = login_name.title()
                is_live = True
                stream_title = stream_info['title']
                stream_game = stream_info['game']
            else: # Channel is OFFLINE
                display_name = f"[Offline] {login_name.title()}"
                is_live = False
                stream_title = None
                stream_game = None
            
            cursor.execute(
                """INSERT OR REPLACE INTO live_streams 
                   (id, login_name, epg_channel_id, display_name, is_live, stream_title, stream_game) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (channel['id'], login_name, epg_id, display_name, is_live, stream_title, stream_game)
            )

        print(f"[Poller-Live]: Live check complete. {live_count} channels are live.")

        # --- 3. VOD Check ---
        if settings['vod_enabled'] and token:
            print("[Poller-VOD]: VOD feature is enabled. Fetching VODs...")
            db_vods_raw = cursor.execute('SELECT vod_id, channel_login FROM vod_streams').fetchall()
            db_vod_map = {} 
            for row in db_vods_raw:
                if row['channel_login'] not in db_vod_map:
                    db_vod_map[row['channel_login']] = set()
                db_vod_map[row['channel_login']].add(row['vod_id'])

            for login_name, user_id in user_id_map.items():
                vods = get_channel_vods(token, settings['twitch_client_id'], user_id, settings['vod_count_per_channel'])
                
                if vods:
                    # print(f"[Poller-VOD]: Found {len(vods)} VODs for {login_name}.") # (Becomes too verbose)
                    vod_category = f"{login_name.title()} VODs"
                    api_vod_ids_this_channel = set()
                    
                    for vod in vods:
                        api_vod_ids_this_channel.add(vod['id'])
                        
                        # --- START OF CHANGE ---
                        # NEW: Format thumbnail URL
                        # Twitch-URL: ...-thumbnail-%{width}x%{height}.jpg
                        # We replace it with a standard size
                        thumbnail = vod['thumbnail_url'].replace('%{width}', '640').replace('%{height}', '360')
                        
                        # CHANGED: From IGNORE to REPLACE and added thumbnail_url
                        cursor.execute(
                            "INSERT OR REPLACE INTO vod_streams (vod_id, channel_login, title, created_at, category, thumbnail_url) VALUES (?, ?, ?, ?, ?, ?)",
                            (vod['id'], login_name, vod['title'], vod['created_at'], vod_category, thumbnail)
                        )
                        # --- END OF CHANGE ---
                    
                    db_vods_this_channel = db_vod_map.get(login_name, set())
                    vods_to_delete = db_vods_this_channel - api_vod_ids_this_channel
                    
                    if vods_to_delete:
                        print(f"[Poller-VOD]: Pruning {len(vods_to_delete)} old VODs for {login_name}.")
                        for old_vod_id in vods_to_delete:
                            cursor.execute("DELETE FROM vod_streams WHERE vod_id = ?", (old_vod_id,))
                
                gevent.sleep(0.1) 
            
            removed_channels = set(db_vod_map.keys()) - set(user_id_map.keys())
            if removed_channels:
                 print(f"[Poller-VOD]: Pruning VODs for removed channels: {removed_channels}")
                 for removed_channel in removed_channels:
                     cursor.execute("DELETE FROM vod_streams WHERE channel_login = ?", (removed_channel,))
        
        elif settings['vod_enabled']:
            print("[Poller-VOD]: VODs are enabled, but Client ID or Secret are missing. Skipping VOD fetch.")
        else:
             print("[Poller-VOD]: VOD feature is disabled. Skipping.")
             cursor.execute("DELETE FROM vod_streams")

        conn.commit()
        print("[Poller]: Database update successful.")

    except Exception as e:
        print(f"[Poller] FATAL ERROR during update: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("[Poller]: Service started. Waiting 5s before first poll...")
    gevent.sleep(5)
    while True:
        update_database()
        gevent.sleep(POLL_INTERVAL)