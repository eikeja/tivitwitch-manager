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

streamlink_session = streamlink.Streamlink()

# --- NEW: Twitch API Helper Functions (wie zuvor) ---
TWITCH_AUTH_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_API_URL_USERS = 'https://api.twitch.tv/helix/users'
TWITCH_API_URL_VIDEOS = 'https://api.twitch.tv/helix/videos'
current_app_token = None
token_expires_at = 0

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_settings():
    """Fetches all settings from the database."""
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
    """Get or refresh a Twitch App Access Token."""
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
    """Get Twitch User IDs from a list of login names."""
    if not login_names:
        return {}
    
    # Twitch API can handle up to 100 login names per request
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
    """Get the latest VODs for a specific User ID."""
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        params = {
            'user_id': user_id,
            'type': 'archive', # 'archive' = past broadcasts
            'first': vod_count
        }
        
        response = requests.get(TWITCH_API_URL_VIDEOS, headers=headers, params=params)
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        print(f"[Poller-VOD] ERROR: Failed to get VODs for user {user_id}: {e}")
        return []

# --- Main Poller Function ---

def update_database():
    print("[Poller]: Starting database update cycle...")
    
    settings = get_settings()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get the list of channels to check from the management table
        channels = conn.execute('SELECT id, login_name FROM channels').fetchall()
        login_names = [row['login_name'] for row in channels]
        
        # --- 1. Live Stream Check ---
        print(f"[Poller-Live]: Checking status for {len(login_names)} live channels...")
        live_count = 0
        
        # We'll update the status for all channels, even if offline
        for channel in channels:
            login_name = channel['login_name']
            is_live = False
            try:
                streams = streamlink_session.streams(f'twitch.tv/{login_name}')
                if "best" in streams:
                    is_live = True
                    live_count += 1
            except Exception:
                is_live = False
            
            display_name = f"[Offline] {login_name.title()}"
            if is_live:
                display_name = login_name.title()
            
            # Update or insert into live_streams table
            cursor.execute(
                "INSERT OR REPLACE INTO live_streams (id, login_name, display_name, is_live) VALUES (?, ?, ?, ?)",
                (channel['id'], login_name, display_name, is_live)
            )

        print(f"[Poller-Live]: Live check complete. {live_count} channels are live.")

        # --- 2. VOD Check (Only if enabled) ---
        if settings['vod_enabled'] and settings['twitch_client_id'] and settings['twitch_client_secret']:
            print("[Poller-VOD]: VOD feature is enabled. Fetching VODs...")
            token = get_twitch_app_token(settings['twitch_client_id'], settings['twitch_client_secret'])
            
            if token:
                user_id_map = get_user_ids(token, settings['twitch_client_id'], login_names)
                
                if not user_id_map:
                    print("[Poller-VOD]: Could not map any login names to User IDs. Skipping VODs.")
                else:
                    # Prune VODs for channels that are no longer in the map
                    all_logins_tuple = tuple(user_id_map.keys())
                    cursor.execute(f"DELETE FROM vod_streams WHERE channel_login NOT IN {all_logins_tuple}")
                    
                    for login_name, user_id in user_id_map.items():
                        # Delete old VODs for this channel first
                        cursor.execute("DELETE FROM vod_streams WHERE channel_login = ?", (login_name,))
                        
                        vods = get_channel_vods(token, settings['twitch_client_id'], user_id, settings['vod_count_per_channel'])
                        
                        if vods:
                            print(f"[Poller-VOD]: Found {len(vods)} VODs for {login_name}.")
                            vod_category = f"{login_name.title()} VODs"
                            
                            for vod in vods:
                                cursor.execute(
                                    "INSERT INTO vod_streams (vod_id, channel_login, title, created_at, category) VALUES (?, ?, ?, ?, ?)",
                                    (vod['id'], login_name, vod['title'], vod['created_at'], vod_category)
                                )
                        
                        gevent.sleep(0.1) # Be nice to the API
        
        elif settings['vod_enabled']:
            print("[Poller-VOD]: VODs are enabled, but Client ID or Secret are missing. Skipping VOD fetch.")
        else:
             print("[Poller-VOD]: VOD feature is disabled. Skipping.")
             # Clear all VODs from DB if feature is disabled
             cursor.execute("DELETE FROM vod_streams")

        # Commit all changes at the end
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