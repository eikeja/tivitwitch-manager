import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

import time
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os

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

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_m3u_file():
    print(f"[Poller]: Starting playlist generation... (Host: {HOST_URL})")
    try:
        conn = get_db_connection()
        channels = conn.execute('SELECT login_name FROM channels').fetchall()
        conn.close()
        
        new_m3u_content = ["#EXTM3U"]
        live_count = 0
        
        for channel_row in channels:
            login_name = channel_row['login_name']
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
            
            # Add [Offline] tag if the stream is not live
            channel_name = f"[Offline] {login_name.title()}"
            if is_live:
                channel_name = login_name.title()
            
            new_m3u_content.append(f'#EXTINF:-1 tvg-id="{login_name}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch",{channel_name}')
            new_m3u_content.append(f'{HOST_URL}/play/{login_name}')
        
        # Write the result to the static file
        with open(OUTPUT_M3U_FILE, 'w') as f:
            f.write('\n'.join(new_m3u_content))
            
        print(f"[Poller]: Playlist update successful. {live_count} of {len(channels)} channels are live.")

    except Exception as e:
        print(f"[Poller] ERROR: {e}")

if __name__ == "__main__":
    print("[Poller]: Service started. Waiting 5s before first poll...")
    gevent.sleep(5)
    while True:
        update_m3u_file()
        gevent.sleep(POLL_INTERVAL)