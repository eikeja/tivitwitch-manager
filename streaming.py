from flask import (
    Blueprint, request, jsonify, Response, redirect, current_app
)
from db import get_db_connection, get_setting, check_xc_auth
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
    conn = get_db_connection()
    streams = conn.execute('SELECT * FROM live_streams WHERE is_live = 1').fetchall()
    conn.close()
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

    conn = get_db_connection() 
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

            conn.close() 
            return jsonify({
                "user_info": {"username": username, "password": password, "auth": 1, "status": "Active", "exp_date": None, "is_trial": "0", "max_connections": "1", "created_at": time.time()},
                "server_info": {"url": HOST_URL.replace("http://", "").replace("https://", "").split(':')[0], "port": port, "https": 1 if HOST_URL.startswith("https") else 0, "server_protocol": "http", "rtmp_port": "1935", "timezone": "UTC", "timestamp_now": int(time.time()), "epg_url": "/xmltv.php"}
            })
        else:
            current_app.logger.warning(f"[XC-API] User '{username}' authentication failed (get_user_info).")
            conn.close() 
            return jsonify({"user_info": {"auth": 0, "status": "Invalid Credentials"}})

    if not check_xc_auth(username, password):
        current_app.logger.warning(f"[XC-API] User '{username}' authentication failed for Action '{action}'.")
        conn.close() 
        return "Invalid credentials", 401
    
    # --- 2. Live Categories ---
    if action == 'get_live_categories':
        current_app.logger.info(f"[XC-API] Delivering live categories for user '{username}'.")
        conn.close() 
        return jsonify([{"category_id": "1", "category_name": "Twitch Live", "parent_id": 0}])

    # --- 3. Live Streams ---
    if action == 'get_live_streams':
        streams = conn.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
        conn.close() 
        current_app.logger.info(f"[XC-API] Delivering {len(streams)} live streams for user '{username}'.")
        
        live_streams_json = []
        for stream in streams:
            live_streams_json.append({
                "num": stream['id'], "name": stream['display_name'], "stream_type": "live", "stream_id": stream['id'], 
                "stream_icon": "", "epg_channel_id": stream['epg_channel_id'], "added": str(int(time.time())),
                "category_id": "1", "custom_sid": "", "tv_archive": 0, "container_extension": "m3u8"
            })
        return jsonify(live_streams_json)
        
    # --- VOD Category Map ---
    categories_raw = conn.execute('SELECT DISTINCT category FROM vod_streams ORDER BY category').fetchall()
    category_map = {row['category']: str(i + 1) for i, row in enumerate(categories_raw)}
    
    # --- 4. VOD (Movie) Categories ---
    if action == 'get_vod_categories':
        vod_categories_json = [{"category_id": cat_id, "category_name": cat_name, "parent_id": 0} for cat_name, cat_id in category_map.items()]
        conn.close()
        current_app.logger.info(f"[XC-API] Delivering {len(vod_categories_json)} VOD categories for user '{username}'.")
        return jsonify(vod_categories_json)
        
    # --- 5. VOD (Movie) Streams ---
    if action == 'get_vod_streams':
        category_id = request.args.get('category_id', None)
        query = 'SELECT * FROM vod_streams'
        params = []
        
        if category_id and category_id != '*':
            cat_name = next((name for name, c_id in category_map.items() if c_id == category_id), None)
            if cat_name:
                query += ' WHERE category = ?'
                params.append(cat_name)
        
        query += ' ORDER BY created_at DESC'
        vods = conn.execute(query, params).fetchall()
        conn.close()
        current_app.logger.info(f"[XC-API] Delivering {len(vods)} VOD streams for user '{username}' (Category: {category_id}).")
        
        vod_streams_json = []
        for vod in vods:
            vod_streams_json.append({
                "num": vod['id'], "name": vod['title'], "stream_type": "movie", 
                "stream_id": vod['vod_id'], # VOD 404 Fix
                "stream_icon": vod['thumbnail_url'] or None, "rating": 0, "rating_5based": 0,
                "added": str(int(time.time())), "category_id": category_map.get(vod['category'], "1"), 
                "container_extension": "m3u8", "custom_sid": "",
            })
        return jsonify(vod_streams_json)

    if action in ('get_series_categories', 'get_series'):
        current_app.logger.info(f"[XC-API] Delivering empty series response for Action '{action}'.")
        conn.close()
        return jsonify([]) 

    conn.close()
    current_app.logger.error(f"[XC-API] Unknown Action '{action}' from user '{username}'.")
    return jsonify({"error": "Unknown action"})

# --- LIVE STREAM ENDPOINTS (WITH SWITCH) ---

@bp.route('/live/<username>/<password>/<int:stream_id>')
@bp.route('/live/<username>/<password>/<int:stream_id>.<ext>')
def play_live_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        return "Invalid credentials", 401
    
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        current_app.logger.error(f"[Play-Live-XC] Stream with DB-ID {stream_id} not found in DB.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    
    live_mode = get_setting('live_stream_mode', 'proxy') # Default 'proxy'
    current_app.logger.info(f"[Play-Live-XC] Request for {login_name} (DB-ID: {stream_id}). Mode: {live_mode}")

    session = streamlink.Streamlink()
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            current_app.logger.warning(f"[Play-Live-XC] Streamlink found no stream for {login_name}. (Offline?)")
            return "Stream offline or not found", 404
        
        if live_mode == 'direct':
            # --- MODE 1: DIRECT (Fast, shows ads) ---
            current_app.logger.info(f"[Play-Live-XC] Sending 302 Redirect for {login_name} to: {streams['best'].url}")
            return redirect(streams["best"].url)
        else:
            # --- MODE 2: PROXY (Slow, filters ads) ---
            current_app.logger.info(f"[Play-Live-XC] Opening stream in Proxy-Mode for {login_name}.")
            stream_fd = streams["best"].open()
            current_app.logger.info("[Live-Proxy] Stream generator starting.")
            return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')

    except Exception as e:
        current_app.logger.error(f"[Play-Live-XC] ERROR: {e}")
        return "Error opening stream", 500

@bp.route('/play_live_m3u/<int:stream_id>')
def play_live_m3u(stream_id):
    """M3U endpoint, also respects the live stream mode."""
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        current_app.logger.error(f"[Play-Live-M3U] Stream with DB-ID {stream_id} not found in DB.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    
    live_mode = get_setting('live_stream_mode', 'proxy')
    current_app.logger.info(f"[Play-Live-M3U] Request for {login_name} (DB-ID: {stream_id}). Mode: {live_mode}")
    
    session = streamlink.Streamlink()
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            current_app.logger.warning(f"[Play-Live-M3U] Streamlink found no stream for {login_name}. (Offline?)")
            return "Stream offline or not found", 404
        
        if live_mode == 'direct':
            current_app.logger.info(f"[Play-Live-M3U] Sending 302 Redirect for {login_name}.")
            return redirect(streams["best"].url)
        else:
            current_app.logger.info(f"[Play-Live-M3U] Opening stream in Proxy-Mode for {login_name}.")
            stream_fd = streams["best"].open()
            current_app.logger.info("[Live-Proxy] Stream generator starting.")
            return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')
        
    except Exception as e:
        current_app.logger.error(f"[Play-Live-M3U] ERROR: {e}")
        return "Error opening stream", 500
        
# --- VOD STREAM ENDPOINTS (Unchanged, proxy is mandatory here) ---

@bp.route('/movie/<username>/<password>/<string:stream_id>') 
@bp.route('/movie/<username>/<password>/<string:stream_id>.<ext>')
def play_vod_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        current_app.logger.warning(f"[Play-VOD-XC] Invalid credentials for user '{username}'")
        return "Invalid credentials", 401

    twitch_vod_id = stream_id 
    current_app.logger.info(f"[Play-VOD-XC]: Client requested HLS-STUFE-1 for VOD {twitch_vod_id}")
    session = streamlink.Streamlink()

    try:
        streams = session.streams(f'twitch.tv/videos/{twitch_vod_id}')
        if "best" not in streams:
            current_app.logger.warning(f"[Play-VOD-XC]: VOD not found on Twitch: {twitch_vod_id}")
            return "VOD not found", 404
            
        current_app.logger.info(f"[Play-VOD-XC]: Streamlink for VOD {twitch_vod_id} successful. Using Stufe-1-Rewriter.")
        return _get_vod_playlist_response(session, twitch_vod_id, streams["best"].url)

    except Exception as e:
        current_app.logger.error(f"[Play-VOD-XC] ERROR: {e}")
        return "Error opening VOD stream", 500

@bp.route('/vod-segment-proxy/<string:twitch_vod_id>/<path:segment_path>')
def vod_segment_proxy(twitch_vod_id, segment_path):
    """STAGE 2: Intercepts segment requests and redirects to a valid Twitch CDN URL."""
    current_app.logger.info(f"[VOD-Proxy-S2]: Request for segment '{segment_path}' for VOD {twitch_vod_id}")
    session = streamlink.Streamlink()
    
    try:
        streams = session.streams(f'twitch.tv/videos/{twitch_vod_id}')
        if "best" not in streams:
            current_app.logger.warning(f"[VOD-Proxy-S2] Streamlink found no streams for VOD {twitch_vod_id}")
            return "Streamlink found no streams", 404
            
        media_playlist_url = streams["best"].url
        base_url = media_playlist_url.rsplit('/', 1)[0] + '/'
        
        response = session.http.get(media_playlist_url)
        response.raise_for_status()
        media_playlist_text = response.text
        
        for line in media_playlist_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            
            line_path = urlparse(line).path
            if line_path.endswith(segment_path):
                absolute_segment_url = urljoin(base_url, line)
                current_app.logger.info(f"[VOD-Proxy-S2]: Redirecting to Twitch CDN for segment.")
                return redirect(absolute_segment_url)

        current_app.logger.error(f"[VOD-Proxy-S2] ERROR: Segment '{segment_path}' not found in fresh playlist for VOD {twitch_vod_id}.")
        return "Segment not found in playlist", 404
        
    except Exception as e:
        current_app.logger.error(f"[VOD-Proxy-S2] ERROR: {e}")
        return "Error proxying segment", 500

# --- M3U / EPG ENDPOINTS ---

@bp.route('/playlist.m3u')
def generate_m3u():
    password = request.args.get('password', '')
    if not check_xc_auth(None, password): return "Invalid password", 401
    
    if get_setting('m3u_enabled', 'false') != 'true':
        current_app.logger.warning("[M3U] M3U playlist request, but feature is disabled.")
        return "M3U playlist feature is disabled on the server.", 404
        
    conn = get_db_connection()
    streams = conn.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
    conn.close()
    
    epg_url = f"{HOST_URL}/epg.xml?password={password}"
    m3u_content = [f'#EXTM3U url-tvg="{epg_url}"']
    
    for stream in streams:
        channel_name = stream['display_name']
        tvg_id = stream['epg_channel_id'] 
        stream_url = f"{HOST_URL}/play_live_m3u/{stream['id']}"
        m3u_content.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch Live",{channel_name}')
        m3u_content.append(stream_url)

    current_app.logger.info(f"[M3U] M3U playlist generated with {len(streams)} channels.")
    return Response('\n'.join(m3u_content), mimetype='audio/mpegurl')

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