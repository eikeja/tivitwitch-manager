from flask import (
    Blueprint, request, jsonify, Response, redirect, current_app
)
from db import get_db, get_setting, check_xc_auth
import streamlink
import time
from datetime import datetime, timedelta
import html
from urllib.parse import urljoin, urlparse
import os

bp = Blueprint('streaming', __name__)

HOST_URL = os.environ.get('HOST_URL')

# --- Streaming Helpers ---

def generate_epg_data():
    """Generates the XMLTV content based on the DB."""
    current_app.logger.info("[EPG] Generating EPG data...")
    db = get_db()
    streams = db.execute('SELECT * FROM live_streams WHERE is_live = 1').fetchall()
    current_app.logger.info(f"[EPG] EPG data generated for {len(streams)} live channels.")
    
    xml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv>']
    
    for stream in streams:
        xml_content.append(f'  <channel id="{stream["epg_channel_id"]}">')
        xml_content.append(f'    <display-name>{html.escape(stream["login_name"].title())}</display-name>')
        xml_content.append('  </channel>')
        
    now = datetime.utcnow()
    start_time = now.strftime('%Y%m%d%H%M%S +0000')
    end_time = (now + timedelta(hours=24)).strftime('%Y%m%d%H%M%S +0000')
    
    for stream in streams:
        title = html.escape(stream['stream_title'] or 'No Title')
        desc = html.escape(stream['stream_game'] or 'No Category')
        
        xml_content.append(f'  <programme start="{start_time}" stop="{end_time}" channel="{stream["epg_channel_id"]}">')
        xml_content.append(f'    <title lang="en">{title}</title>')
        xml_content.append(f'    <desc lang="en">{desc}</desc>')
        xml_content.append(f'    <category lang="en">{desc}</category>')
        xml_content.append('  </programme>')
        
    xml_content.append('</tv>')
    return '\n'.join(xml_content)

def _get_vod_playlist_response(session, twitch_vod_id, stream_url):
    """(For VODs) Rewrites the playlist to point to our /vod-segment-proxy/."""
    try:
        current_app.logger.info(f"[HLS-Proxy-VOD1] Fetching media playlist for VOD {twitch_vod_id}: {stream_url}")
        response = session.http.get(stream_url)
        response.raise_for_status()
        media_playlist_text = response.text
    except Exception as e:
        current_app.logger.error(f"[HLS-Proxy-VOD1] ERROR: Failed to fetch media playlist '{stream_url}': {e}")
        return "Error fetching media playlist", 500

    output_playlist = []
    segment_count = 0
    
    for line in media_playlist_text.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith('#'):
            output_playlist.append(line)
        else:
            segment_count += 1
            segment_path = urlparse(line).path
            proxy_url = f"/vod-segment-proxy/{twitch_vod_id}/{segment_path}"
            output_playlist.append(proxy_url)
    
    current_app.logger.info(f"[HLS-Proxy-VOD1] Playlist for VOD {twitch_vod_id} rewritten to local proxy with {segment_count} segments.")
    return Response('\n'.join(output_playlist), mimetype='application/vnd.apple.mpegurl')

def generate_stream_data(stream_fd):
    """(For Live-Proxy) Yields chunks of stream data."""
    # This function runs outside the app context.
    # Use print() instead of current_app.logger, as stdout is captured anyway.
    try:
        while True:
            data = stream_fd.read(4096)
            if not data:
                print("[Live-Proxy] Stream ended (no more data).")
                break
            yield data
    except Exception as e:
        if "Connection reset by peer" not in str(e):
            print(f"[Live-Proxy] ERROR: Error during streaming: {e}")
    finally:
        stream_fd.close()
        print("[Live-Proxy] Stream connection closed.")

# --- TIVIMATE XTREAM CODES API ENDPOINT ---
@bp.route('/player_api.php', methods=['GET', 'POST'])
def player_api():
    username = request.args.get('username', 'default')
    password = request.args.get('password', '')
    action = request.args.get('action', '')
    
    if not HOST_URL:
        current_app.logger.critical("[XC-API] HOST_URL environment variable is not set! API will fail.")
        return "HOST_URL environment variable is not set on the server.", 500

    db = get_db() 
    current_app.logger.info(f"[XC-API] Request from user '{username}', Action: '{action}'")

    # --- 1. Authentication ---
    if action == 'get_user_info' or action == '':
        if check_xc_auth(username, password):
            current_app.logger.info(f"[XC-API] User '{username}' authenticated successfully (get_user_info).")
            port = "80"
            if ':' in HOST_URL:
                port_str = HOST_URL.split(':')[-1]
                if port_str.isdigit():
                    port = port_str

            return jsonify({
                "user_info": {"username": username, "password": password, "auth": 1, "status": "Active", "exp_date": None, "is_trial": "0", "max_connections": "1", "created_at": time.time()},
                "server_info": {"url": HOST_URL.replace("http://", "").replace("https://", "").split(':')[0], "port": port, "https": 1 if HOST_URL.startswith("https") else 0, "server_protocol": "http", "rtmp_port": "1935", "timezone": "UTC", "timestamp_now": int(time.time()), "epg_url": "/xmltv.php"}
            })
        else:
            current_app.logger.warning(f"[XC-API] User '{username}' authentication failed (get_user_info).")
            return jsonify({"user_info": {"auth": 0, "status": "Invalid Credentials"}})

    if not check_xc_auth(username, password):
        current_app.logger.warning(f"[XC-API] User '{username}' authentication failed for Action '{action}'.")
        return "Invalid credentials", 401
    
    # --- 2. Live Categories ---
    if action == 'get_live_categories':
        current_app.logger.info(f"[XC-API] Delivering live categories for user '{username}'.")
        return jsonify([{"category_id": "1", "category_name": "Twitch Live", "parent_id": 0}])

@bp.route('/epg.xml')
def generate_epg_xml():
    password = request.args.get('password', '')
    if not check_xc_auth(None, password): return "Invalid password", 401
    
    current_app.logger.info("[M3U-EPG] Request for M3U EPG (epg.xml) received.")
    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')

@bp.route('/xmltv.php')
def generate_xc_epg_xml():
    username = request.args.get('username')
    password = request.args.get('password')
    if not check_xc_auth(username, password): return "Invalid credentials", 401

    current_app.logger.info(f"[XC-EPG] Request for XC EPG (xmltv.php) from user '{username}' received.")
    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')