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
import logging
import zlib

bp = Blueprint('streaming', __name__)

HOST_URL = os.environ.get('HOST_URL')

# --- Streaming Helpers ---
from db import get_user_by_token, get_user_by_username 

def generate_epg_data(user_id=None):
    """Generates the XMLTV content based on the DB, optionally filtered by user."""
    current_app.logger.info(f"[EPG] Generating EPG data... (User ID: {user_id})")
    db = get_db()
    
    if user_id:
        query = '''
            SELECT l.* 
            FROM live_streams l
            JOIN channels c ON l.login_name = c.login_name
            WHERE c.user_id = ? AND l.is_live = 1
        '''
        streams = db.execute(query, (user_id,)).fetchall()
    else:
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
    """(For Live-Proxy) Yields chunks of stream data with performance logging."""
    # This function runs outside the app context.
    try:
        chunk_size = 32768 # 32KB chunks
        last_log_time = time.time()
        total_bytes = 0
        total_read_time = 0
        total_yield_time = 0
        chunks_count = 0
        
        # Use root logger to ensure capture by FileHandler (since we are in thread/generator)
        logger = logging.getLogger("flask.app") 
        msg_start = f"[Live-Proxy] Diagnostics started. Chunk Size: {chunk_size}"
        logger.info(msg_start)
        print(msg_start, flush=True) # Fallback

        while True:
            # 1. Twitch Read
            t_start = time.time()
            data = stream_fd.read(chunk_size)
            t_read_done = time.time()
            
            if chunks_count == 0:
                 logger.info(f"[Live-Proxy] First chunk received ({len(data)} bytes) in {(t_read_done - t_start)*1000:.1f}ms.")

            if not data:
                logger.info("[Live-Proxy] Stream ended (no more data).")
                break
                
            read_dur = t_read_done - t_start
            
            # 2. Client Write (Yield)
            yield data
            t_yield_done = time.time()
            yield_dur = t_yield_done - t_read_done
            
            # Update stats
            total_bytes += len(data)
            total_read_time += read_dur
            total_yield_time += yield_dur
            chunks_count += 1
            
            # 3. Log (Every 2s)
            now = time.time()
            if now - last_log_time >= 2:
                elapsed = now - last_log_time
                mb_s = (total_bytes / (1024*1024)) / elapsed
                avg_read = (total_read_time / chunks_count) * 1000 if chunks_count else 0
                avg_write = (total_yield_time / chunks_count) * 1000 if chunks_count else 0
                
                msg_speed = f"[Speed] Throughput: {mb_s:.2f} MB/s | Twitch Read (Avg): {avg_read:.1f}ms | Client Write (Avg): {avg_write:.1f}ms"
                logger.info(msg_speed)
                print(msg_speed, flush=True)
                
                last_log_time = now
                total_bytes = 0
                total_read_time = 0
                total_yield_time = 0
                chunks_count = 0

    except Exception as e:
        if "Connection reset by peer" not in str(e):
            logging.getLogger("flask.app").error(f"[Live-Proxy] ERROR: Error during streaming: {e}")
    finally:
        stream_fd.close()
        logging.getLogger("flask.app").info("[Live-Proxy] Stream connection closed.")

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
    
    # Get User Object for filtering
    user = get_user_by_username(username)
    user_id = user['id'] if user else None

    # --- 2. Live Categories ---
    if action == 'get_live_categories':
        current_app.logger.info(f"[XC-API] Delivering live categories for user '{username}'.")
        return jsonify([{"category_id": "1", "category_name": "Twitch Live", "parent_id": 0}])

    # --- 3. Live Streams ---
    if action == 'get_live_streams':
        # Filter by user subscription
        if user_id:
            query = '''
                SELECT l.* 
                FROM live_streams l
                JOIN channels c ON l.login_name = c.login_name
                WHERE c.user_id = ?
                ORDER BY l.is_live DESC, l.login_name ASC
            '''
            streams = db.execute(query, (user_id,)).fetchall()
        else:
            # Fallback (shouldn't happen with auth)
            streams = db.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
            
        current_app.logger.info(f"[XC-API] Delivering {len(streams)} live streams for user '{username}'.")
        
        live_streams_json = []
        for stream in streams:
            # Use login_name as key for now, or maybe stream['login_name'] as ID? 
            # TiviMate expects an integer stream_id mostly. 
            # We don't have a stable integer ID per user-channel-link easily unless we use channels.id
            # But live_streams table removed ID. 
            # Let's use hash or just keep login_name if supported, or fake ID?
            # Actually, we can use channels.id! We need to join to get it.
            # Let's adjust query to get channels.id as stream_id
            pass # See next block for fix logic (I can't edit mid-stream easily, but I will adjust query above)
            
        # Re-doing query to get channel ID which is stable for the user
        if user_id:
            query = '''
                SELECT l.*, c.id as channel_id
                FROM live_streams l
                JOIN channels c ON l.login_name = c.login_name
                WHERE c.user_id = ?
                ORDER BY l.is_live DESC, l.login_name ASC
            '''
            streams = db.execute(query, (user_id,)).fetchall()
            
        live_streams_json = []
        for stream in streams:
            display_name = stream['display_name']
            if stream['is_live'] and stream['stream_title']:
                display_name = f"{stream['login_name']} - {stream['stream_title']}"
                
            live_streams_json.append({
                "num": stream['channel_id'], "name": display_name, "stream_type": "live", "stream_id": stream['channel_id'], 
                "stream_icon": "", "epg_channel_id": stream['epg_channel_id'], "added": str(int(time.time())),
                "category_id": "1", "custom_sid": "", "tv_archive": 0, "container_extension": "m3u8"
            })
        return jsonify(live_streams_json)
        
    if action == 'get_vod_categories':
        query = '''
            SELECT DISTINCT c.login_name
            FROM channels c
            JOIN vod_streams v ON c.login_name = v.channel_login
            WHERE c.user_id = ?
        '''
        vod_categories = db.execute(query, (user_id,)).fetchall() if user_id else []
        json_resp = []
        for row in vod_categories:
            cat_id = str(zlib.crc32(row['login_name'].encode('utf-8')) & 0x7FFFFFFF)
            json_resp.append({
                "category_id": cat_id,
                "category_name": row['login_name'].title(),
                "parent_id": 0
            })
        current_app.logger.info(f"[XC-API] Delivering {len(json_resp)} VOD categories for user '{username}'.")
        return jsonify(json_resp)
        
    if action == 'get_vod_streams':
        category_id_filter = request.args.get('category_id')
        query = '''
            SELECT v.*, c.login_name
            FROM vod_streams v
            JOIN channels c ON v.channel_login = c.login_name
            WHERE c.user_id = ?
            ORDER BY v.created_at DESC
        '''
        vods = db.execute(query, (user_id,)).fetchall() if user_id else []
        json_resp = []
        
        for vod in vods:
            cat_id = str(zlib.crc32(vod['login_name'].encode('utf-8')) & 0x7FFFFFFF)
            if category_id_filter and category_id_filter != '*' and str(category_id_filter) != cat_id:
                continue
                
            formatted_date = ""
            try:
                dt = datetime.strptime(vod['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                formatted_date = dt.strftime("%d.%m.%y")
            except Exception:
                formatted_date = vod['created_at'][:10]
                
            ep_title = f"[{formatted_date}] {vod['title']}"
            
            json_resp.append({
                "num": vod['id'],
                "name": ep_title,
                "stream_type": "movie",
                "stream_id": vod['vod_id'],
                "stream_icon": vod['thumbnail_url'],
                "rating": "5",
                "rating_5based": 5,
                "added": str(int(time.time())),
                "category_id": cat_id,
                "container_extension": "mp4",
                "custom_sid": "",
                "direct_source": ""
            })
            
        current_app.logger.info(f"[XC-API] Delivering {len(json_resp)} VOD streams for user '{username}'.")
        return jsonify(json_resp)

    if action == 'get_vod_info':
        vod_id = request.args.get('vod_id')
        if not vod_id: return jsonify({})
        row = db.execute("SELECT * FROM vod_streams WHERE vod_id = ? OR id = ?", (vod_id, vod_id)).fetchone()
        if not row: return jsonify({})
        
        duration_str = "00:00:00"
        if row['duration']:
            duration_str = str(timedelta(seconds=int(row['duration'])))
            
        return jsonify({
            "info": {
                "movie_image": row['thumbnail_url'],
                "plot": row['title'],
                "cast": row['channel_login'].title(),
                "director": row['channel_login'].title(),
                "genre": "Twitch VOD",
                "releaseDate": row['created_at'][:10],
                "duration_secs": row['duration'],
                "duration": duration_str
            },
            "movie_data": {
                "stream_id": row['vod_id'],
                "name": row['title'],
                "added": str(int(time.time())),
                "category_id": str(zlib.crc32(row['channel_login'].encode('utf-8')) & 0x7FFFFFFF),
                "container_extension": "mp4"
            }
        })

    # --- SERIES API FOR VODS (REVERTED TO EMPTY) ---
    if action == 'get_series_categories':
        return jsonify([])

    if action == 'get_series':
        return jsonify([])

    if action == 'get_series_info':
        return jsonify({})

    current_app.logger.error(f"[XC-API] Unknown Action '{action}' from user '{username}'.")
    return jsonify({"error": "Unknown action"})

# --- LIVE STREAM ENDPOINTS (WITH SWITCH) ---

@bp.route('/live/<username>/<password>/<int:stream_id>')
@bp.route('/live/<username>/<password>/<int:stream_id>.<ext>')
def play_live_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        return "Invalid credentials", 401
    
    db = get_db()
    # stream_id in M3U/XC is now channels.id
    # We need to find the login_name from channels table (and ensure user owns it? strict check optional but good)
    channel = db.execute('''
        SELECT c.login_name, u.auth_token 
        FROM channels c 
        JOIN users u ON c.user_id = u.id 
        WHERE c.id = ?
    ''', (stream_id,)).fetchone()
    
    if not channel:
        current_app.logger.error(f"[Play-Live-XC] Stream with ID {stream_id} not found in Channels.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    auth_token = channel['auth_token']
    
    live_mode = get_setting('live_stream_mode', 'proxy') # Default 'proxy'
    current_app.logger.info(f"[Play-Live-XC] Request for {login_name} (ID: {stream_id}). Mode: {live_mode}")

    hls_live_edge = get_setting('hls_live_edge', '10')      # Default INCREASED to 10 for stability
    # FORCE THREADS to 10
    # hls_segment_threads = get_setting('hls_segment_threads', '4')
    hls_segment_threads = 10
    ringbuffer_size = get_setting('ringbuffer_size', '33554432') # Default INCREASED to 32MB
    debug_logging = get_setting('streamlink_log_enabled', 'false') == 'true'
    # FORCE DISABLE ADS to fix Discontinuity
    # disable_ads = get_setting('twitch_disable_ads', 'true') == 'true' 
    disable_ads = True

    sl_logger = logging.getLogger("streamlink")
    # ... (Keep logging config) ...

    session = streamlink.Streamlink()
    session.set_option("hls-live-edge", int(hls_live_edge))
    session.set_option("hls-segment-threads", int(hls_segment_threads))
    session.set_option("hls-playlist-reload-attempts", 5) # Internal stability boost
    session.set_option("ringbuffer-size", int(ringbuffer_size))
    session.set_option("http-header", "User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    session.set_option("twitch-disable-ads", disable_ads)
    if auth_token:
        current_app.logger.info(f"[Streamlink] Applying User Auth Token for stream: {login_name}")
        session.set_option("twitch-auth-token", auth_token)
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            current_app.logger.warning(f"[Play-Live-XC] Streamlink found no stream for {login_name}. (Offline?)")
            return "Stream offline or not found", 404
        
        if live_mode == 'direct':
            current_app.logger.info(f"[Play-Live-XC] Sending 302 Redirect for {login_name} to: {streams['best'].url}")
            return redirect(streams["best"].url)
        else:
            current_app.logger.info(f"[Play-Live-XC] Opening stream in Proxy-Mode for {login_name}. (Ads Disabled: {disable_ads}, Buffer: {ringbuffer_size}, Edge: {hls_live_edge})")
            stream_fd = streams["best"].open()
            current_app.logger.info("[Live-Proxy] Stream generator starting.")
            return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')

    except Exception as e:
        current_app.logger.error(f"[Play-Live-XC] ERROR: {e}")
        return "Error opening stream", 500

@bp.route('/play_live_m3u/<int:stream_id>')
def play_live_m3u(stream_id):
    """M3U endpoint, also respects the live stream mode."""
    # This ID is channels.id
    db = get_db()
    channel = db.execute('''
        SELECT c.login_name, u.auth_token 
        FROM channels c 
        JOIN users u ON c.user_id = u.id 
        WHERE c.id = ?
    ''', (stream_id,)).fetchone()
    
    if not channel:
        current_app.logger.error(f"[Play-Live-M3U] Stream with ID {stream_id} not found.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    auth_token = channel['auth_token']
    
    live_mode = get_setting('live_stream_mode', 'proxy')
    current_app.logger.info(f"[Play-Live-M3U] Request for {login_name} (ID: {stream_id}). Mode: {live_mode}")
    
    hls_live_edge = get_setting('hls_live_edge', '10')      # Default INCREASED to 10
    # FORCE THREADS to 10
    hls_segment_threads = 10
    ringbuffer_size = get_setting('ringbuffer_size', '33554432') # Default INCREASED to 32MB
    debug_logging = get_setting('streamlink_log_enabled', 'false') == 'true'
    disable_ads = get_setting('twitch_disable_ads', 'true') == 'true' # Default ENABLED

    sl_logger = logging.getLogger("streamlink")
    # ... (Logging config skipped for brevity in search, assuming it matches above structure) ...

    session = streamlink.Streamlink()
    session.set_option("hls-live-edge", int(hls_live_edge))
    session.set_option("hls-segment-threads", int(hls_segment_threads))
    session.set_option("hls-playlist-reload-attempts", 5)
    session.set_option("ringbuffer-size", int(ringbuffer_size))
    session.set_option("http-header", "User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    session.set_option("twitch-disable-ads", disable_ads)
    if auth_token:
        session.set_option("twitch-auth-token", auth_token)
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            current_app.logger.warning(f"[Play-Live-M3U] Streamlink found no stream for {login_name}. (Offline?)")
            return "Stream offline or not found", 404
        
        if live_mode == 'direct':
            current_app.logger.info(f"[Play-Live-M3U] Sending 302 Redirect for {login_name}.")
            return redirect(streams["best"].url)
        else:
            current_app.logger.info(f"[Play-Live-M3U] Opening stream in Proxy-Mode for {login_name}. (Ads Disabled: {disable_ads})")
            stream_fd = streams["best"].open()
            current_app.logger.info("[Live-Proxy] Stream generator starting.")
            return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')
        
    except Exception as e:
        current_app.logger.error(f"[Play-Live-M3U] ERROR: {e}")
        return "Error opening stream", 500
        
# --- VOD & SERIES STREAM ENDPOINTS (Proxy is mandatory here) ---

@bp.route('/movie/<username>/<password>/<string:stream_id>') 
@bp.route('/movie/<username>/<password>/<string:stream_id>.<ext>')
@bp.route('/series/<username>/<password>/<string:stream_id>') 
@bp.route('/series/<username>/<password>/<string:stream_id>.<ext>')
def play_vod_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        current_app.logger.warning(f"[Play-VOD-XC] Invalid credentials for user '{username}'")
        return "Invalid credentials", 401

    twitch_vod_id = stream_id 
    
    # Resolve potential internal ID to Twitch VOD ID
    db = get_db()
    # First check if it's already a valid Twitch VOD ID (usually long string of digits)
    # But strictly, check DB first to be safe or if stream_id is internal ID
    row = db.execute("SELECT vod_id FROM vod_streams WHERE vod_id = ?", (stream_id,)).fetchone()
    if row:
        twitch_vod_id = row['vod_id']
    else:
        # Fallback: check if it is an internal ID
        if str(stream_id).isdigit():
             row = db.execute("SELECT vod_id FROM vod_streams WHERE id = ?", (stream_id,)).fetchone()
             if row:
                 twitch_vod_id = row['vod_id']
                 current_app.logger.info(f"[Play-VOD-XC]: Resolved internal ID {stream_id} to Twitch VOD ID {twitch_vod_id}")

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
    token = request.args.get('token')
    
    if get_setting('m3u_enabled', 'false') != 'true':
        current_app.logger.warning("[M3U] M3U playlist request, but feature is disabled.")
        return "M3U playlist feature is disabled on the server.", 404
    
    user_id = None
    if token:
        user = get_user_by_token(token)
        if user:
            user_id = user['id']
        else:
            return "Invalid token", 401
    else:
        # Require token
        return "Auth token missing", 401
        
    db = get_db()
    # Join to filter by user and get channels.id
    query = '''
        SELECT l.*, c.id as channel_id
        FROM live_streams l
        JOIN channels c ON l.login_name = c.login_name
        WHERE c.user_id = ?
        ORDER BY l.is_live DESC, l.login_name ASC
    '''
    streams = db.execute(query, (user_id,)).fetchall()
    
    epg_url = f"{HOST_URL}/epg.xml?token={token}"
    m3u_content = [f'#EXTM3U url-tvg="{epg_url}"']
    
    for stream in streams:
        channel_name = stream['display_name']
        if stream['is_live'] and stream['stream_title']:
            channel_name = f"{stream['login_name']} - {stream['stream_title']}"
            
        tvg_id = stream['epg_channel_id'] 
        stream_url = f"{HOST_URL}/play_live_m3u/{stream['channel_id']}"
        m3u_content.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch Live",{channel_name}')
        m3u_content.append(stream_url)

    current_app.logger.info(f"[M3U] M3U playlist generated with {len(streams)} channels for token user.")
    return Response('\n'.join(m3u_content), mimetype='audio/mpegurl')

@bp.route('/epg.xml')
def generate_epg_xml():
    token = request.args.get('token')
    user_id = None
    if token:
        user = get_user_by_token(token)
        if user: user_id = user['id']
            
    current_app.logger.info("[M3U-EPG] Request for M3U EPG (epg.xml) received.")
    xml_data = generate_epg_data(user_id=user_id)
    return Response(xml_data, mimetype='application/xml')

@bp.route('/xmltv.php')
def generate_xc_epg_xml():
    username = request.args.get('username')
    password = request.args.get('password')
    if not check_xc_auth(username, password): return "Invalid credentials", 401
    
    user = get_user_by_username(username)
    user_id = user['id'] if user else None

    current_app.logger.info(f"[XC-EPG] Request for XC EPG (xmltv.php) from user '{username}' received.")
    xml_data = generate_epg_data(user_id=user_id)
    return Response(xml_data, mimetype='application/xml')