import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

import time
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os
import requests # New import

# --- Configuration ---
DB_PATH = '/data/channels.db'
# This is the static file Nginx will serve
OUTPUT_M3U_FILE = '/tmp/playlist.m3u' 
# HOST_URL must be set as an environment variable
HOST_URL = os.environ.get('HOST_URL')
if not HOST_URL:
    print("[Poller] FATAL ERROR: HOST_URL environment variable is not set.")
    exit(1)
POLL_INTERVAL = 60 # seconds

streamlink_session = streamlink.Streamlink()

# --- NEW: Twitch API Helper Functions ---
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
    
    # Add defaults for safety
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
        # Set expiry with a 60-second buffer for safety
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
        
    print(f"[Poller-VOD]: Fetching User IDs for {len(login_names)} channels...")
    try:
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'}
        # Build query params
        params = [('login', name) for name in login_names]
        
        response = requests.get(TWITCH_API_URL_USERS, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get('data', [])
        
        # Return a mapping of login_name -> id
        return {user['login']: user['id'] for user in data}
    except Exception as e:
        print(f"[Poller-VOD] ERROR: Failed to get User IDs: {e}")
        return {}

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

def update_m3u_file():
    print(f"[Poller]: Starting playlist generation... (Host: {HOST_URL})")
    
    settings = get_settings()
    new_m3u_content = ["#EXTM3U"]
    live_count = 0
    vod_count = 0

    try:
        conn = get_db_connection()
        channels = conn.execute('SELECT login_name FROM channels').fetchall()
        conn.close()
        
        login_names = [row['login_name'] for row in channels]
        
        # --- 1. Live Stream Check (Always runs) ---
        print(f"[Poller-Live]: Checking status for {len(login_names)} live channels...")
        for login_name in login_names:
            is_live = False
            try:
                streams = streamlink_session.streams(f'twitch.tv/{login_name}')
                if "best" in streams:
                    is_live = True
                    live_count += 1
            except (NoPluginError, PluginError, TypeError):
                is_live = False
            except Exception:
                is_live = False
            
            channel_name = f"[Offline] {login_name.title()}"
            if is_live:
                channel_name = login_name.title()
            
            # Use "Twitch Live" as the group title
            new_m3u_content.append(f'#EXTINF:-1 tvg-id="{login_name}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch Live",{channel_name}')
            new_m3u_content.append(f'{HOST_URL}/play/{login_name}')
        
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
                    for login_name, user_id in user_id_map.items():
                        vods = get_channel_vods(token, settings['twitch_client_id'], user_id, settings['vod_count_per_channel'])
                        
                        if vods:
                            print(f"[Poller-VOD]: Found {len(vods)} VODs for {login_name}.")
                            # Create a VOD group for this channel
                            vod_group_title = f"{login_name.title()} VODs"
                            
                            for vod in vods:
                                # Clean up title
                                vod_title = vod['title'].replace(',', '')
                                # Use a unique tvg-id
                                vod_tvg_id = f"{login_name}.vod.{vod['id']}"
                                
                                new_m3u_content.append(f'#EXTINF:-1 tvg-id="{vod_tvg_id}" tvg-name="{vod_title}" tvg-logo="" group-title="{vod_group_title}",VOD: {vod_title}')
                                new_m3u_content.append(f'{HOST_URL}/play_vod/{vod["id"]}')
                                vod_count += 1
                        
                        gevent.sleep(0.1) # Be nice to the API
        
        elif settings['vod_enabled']:
            print("[Poller-VOD]: VODs are enabled, but Client ID or Secret are missing. Skipping VOD fetch.")
        else:
             print("[Poller-VOD]: VOD feature is disabled. Skipping.")

        # --- 3. Write File ---
        with open(OUTPUT_M3U_FILE, 'w') as f:
            f.write('\n'.join(new_m3u_content))
            
        print(f"[Poller]: Playlist update successful. {live_count} live channels, {vod_count} VODs written.")

    except Exception as e:
        print(f"[Poller] FATAL ERROR during update: {e}")

if __name__ == "__main__":
    print("[Poller]: Service started. Waiting 5s before first poll...")
    gevent.sleep(5)
    while True:
        update_m3u_file()
        gevent.sleep(POLL_INTERVAL)