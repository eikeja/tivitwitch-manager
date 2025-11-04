import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

import time
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os

# --- NEU: Dynamische Pfade aus Umgebungsvariablen ---
DB_PATH = '/data/channels.db'
OUTPUT_M3U_FILE = '/tmp/playlist.m3u'
# HOST_URL MUSS als Environment Variable gesetzt werden
HOST_URL = os.environ.get('HOST_URL')
if not HOST_URL:
    print("[Poller] FATALER FEHLER: HOST_URL Environment Variable ist nicht gesetzt.")
    exit(1)
POLL_INTERVAL = 60 # Sekunden

streamlink_session = streamlink.Streamlink()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_m3u_file():
    print(f"[Poller]: Starte Cache-Erstellung... (Host: {HOST_URL})")
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
            
            channel_name = f"[Offline] {login_name.title()}"
            if is_live:
                channel_name = login_name.title()
            
            new_m3u_content.append(f'#EXTINF:-1 tvg-id="{login_name}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch",{channel_name}')
            new_m3u_content.append(f'{HOST_URL}/play/{login_name}')
        
        with open(OUTPUT_M3U_FILE, 'w') as f:
            f.write('\n'.join(new_m3u_content))
            
        print(f"[Poller]: Cache-Update erfolgreich. {live_count} von {len(channels)} Kanälen sind live.")

    except Exception as e:
        print(f"[Poller] FEHLER: {e}")

if __name__ == "__main__":
    print("[Poller]: Dienst gestartet. Warte 5s vor der ersten Prüfung...")
    gevent.sleep(5)
    while True:
        update_m3u_file()
        gevent.sleep(POLL_INTERVAL)