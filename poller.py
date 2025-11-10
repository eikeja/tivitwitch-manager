import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os
import time
from datetime import datetime, timedelta
import html
from urllib.parse import urljoin, urlparse
import logging
import sys

app = Flask(__name__)

# --- START Logging Config ---
app.logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s [Flask] [%(filename)s:%(lineno)d] - %(message)s'
))
app.logger.addHandler(stream_handler)
app.logger.info("Flask application starting...")
# --- END Logging Config ---

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')
DB_PATH = '/data/channels.db'
HOST_URL = os.environ.get('HOST_URL')

app.logger.info("Gevent monkey-patching angewendet.")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_password_hash():
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
    conn.close()
    return row['value'] if row else None

# --- TiviMate / XC API Auth Helper ---
def check_xc_auth(username, password):
    """Checks TiviMate credentials against the master password."""
    if not password:
        app.logger.warning("[Auth] Check_xc_auth fehlgeschlagen: Kein Passwort angegeben.")
        return False
    pw_hash = get_password_hash()
    if not pw_hash: # No password set in setup
        app.logger.error("[Auth] Check_xc_auth fehlgeschlagen: Kein Master-Passwort in der DB gesetzt (Setup ausführen?).")
        return False
        
    is_valid = check_password_hash(pw_hash, password)
    if not is_valid:
        app.logger.warning(f"[Auth] Check_xc_auth fehlgeschlagen: Falsches Passwort für User '{username}'.")
        
    return is_valid

# --- Global EPG XML Generator Function ---
def generate_epg_data():
    """Generates the XMLTV content based on the DB."""
    app.logger.info("[EPG] Generiere EPG-Daten...")
    conn = get_db_connection()
    streams = conn.execute('SELECT * FROM live_streams WHERE is_live = 1').fetchall()
    conn.close()
    app.logger.info(f"[EPG] EPG-Daten für {len(streams)} Live-Kanäle erstellt.")
    
    xml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv>']
    
    # Define channels
    for stream in streams:
        xml_content.append(f'  <channel id="{stream["epg_channel_id"]}">')
        xml_content.append(f'    <display-name>{html.escape(stream["login_name"].title())}</display-name>')
        xml_content.append('  </channel>')
        
    # Define programs (EPG entries)
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


# --- Web UI Auth & Routes (Login, Setup, etc.) ---
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if get_password_hash():
        return redirect(url_for('login'))
    if request.method == 'POST':
        password = request.form.get('password')
        if not password or len(password) < 4:
            flash('Password must be at least 4 characters long.', 'error')
            return redirect(url_for('setup'))
        pw_hash = generate_password_hash(password)
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ('password_hash', pw_hash))
        conn.commit()
        conn.close()
        session['logged_in'] = True
        flash('Password set successfully!', 'success')
        app.logger.info("[Auth] Neues Master-Passwort wurde gesetzt.")
        return redirect(url_for('index'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not get_password_hash():
        return redirect(url_for('setup'))
    if request.method == 'POST':
        password = request.form.get('password')
        pw_hash = get_password_hash()
        if check_password_hash(pw_hash, password):
            session['logged_in'] = True
            app.logger.info("[Auth] Web UI Login erfolgreich.")
            return redirect(url_for('index'))
        else:
            app.logger.warning("[Auth] Web UI Login fehlgeschlagen (falsches Passwort).")
            flash('Invalid password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'success')
    app.logger.info("[Auth] Web UI Logout.")
    return redirect(url_for('login'))

# --- Web UI Auth Middleware ---
@app.before_request
def check_web_ui_auth():
    public_paths = [
        '/static/',
        '/login',
        '/setup',
        '/player_api.php',
        '/live/',
        '/movie/',
        '/vod-segment-proxy/',
        '/playlist.m3u',
        '/play_live_m3u/',
        '/epg.xml',
        '/xmltv.php'
    ]
    
    for path in public_paths:
        if request.path.startswith(path):
            return 

    if not get_password_hash():
         app.logger.info(f"[Auth] Kein Passwort gesetzt, leite zu /setup um (von {request.path})")
         return redirect(url_for('setup'))
        
    if 'logged_in' not in session:
        app.logger.warning(f"[Auth] Nicht eingeloggt, leite zu /login um (von {request.path})")
        if 'api' in request.path: 
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('login')) 


# --- TIVIMATE STREAMING ENDPOINTS (PUBLIC) ---

# --- METHODE 1: HLS-Proxy (Für LIVE) ---
# --- START ÄNDERUNG: HLS-Proxy-Funktion entfernt ---
# def _get_live_hls_response(session, stream_url):
#     ... (entfernt)
# --- ENDE ÄNDERUNG ---


# --- METHODE 2: VOD-Playlist-Rewriter (STUFE 1) ---
def _get_vod_playlist_response(session, twitch_vod_id, stream_url):
    """(Für VOD-Streams) Schreibt Playlist auf den /vod-segment-proxy/ um."""
    try:
        app.logger.info(f"[HLS-Proxy-VOD1] Rufe Media-Playlist für VOD {twitch_vod_id} ab: {stream_url}")
        response = session.http.get(stream_url)
        response.raise_for_status()
        media_playlist_text = response.text
    except Exception as e:
        app.logger.error(f"[HLS-Proxy-VOD1] ERROR: Failed to fetch media playlist '{stream_url}': {e}")
        return "Error fetching media playlist", 500

    output_playlist = []
    segment_count = 0
    
    for line in media_playlist_text.splitlines():
        line = line.strip()
        if not line:
            continue
        
        if line.startswith('#'):
            output_playlist.append(line)
        else:
            segment_count += 1
            segment_path = urlparse(line).path
            proxy_url = f"/vod-segment-proxy/{twitch_vod_id}/{segment_path}"
            output_playlist.append(proxy_url)
    
    app.logger.info(f"[HLS-Proxy-VOD1] Playlist für VOD {twitch_vod_id} mit {segment_count} Segmenten auf lokalen Proxy umgeschrieben.")
    return Response(
        '\n'.join(output_playlist), 
        mimetype='application/vnd.apple.mpegurl'
    )


# --- Live Streams (Nutzt HLS-Proxy) ---
@app.route('/live/<username>/<password>/<int:stream_id>')
@app.route('/live/<username>/<password>/<int:stream_id>.<ext>')
def play_live_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        return "Invalid credentials", 401
    
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        app.logger.error(f"[Play-Live-XC] Stream mit DB-ID {stream_id} nicht in DB gefunden.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    app.logger.info(f"[Play-Live-XC]: Client requested HLS for {login_name} (DB-ID: {stream_id})")
    
    session = streamlink.Streamlink() # Frische Session
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            app.logger.warning(f"[Play-Live-XC]: Streamlink fand keinen Stream für {login_name} (ID: {stream_id}). (Offline?)")
            return "Stream offline or not found", 404
            
        # --- START ÄNDERUNG: Nutze 302 Redirect statt HLS-Proxy ---
        app.logger.info(f"[Play-Live-XC]: Streamlink für {login_name} erfolgreich. Sende 302 Redirect an: {streams['best'].url}")
        return redirect(streams["best"].url)
        # --- ENDE ÄNDERUNG ---

    except Exception as e:
        app.logger.error(f"[Play-Live-XC] ERROR: {e}")
        return "Error opening stream", 500

# --- VOD Streams (Nutzt Stufe-1-Rewriter) ---
@app.route('/movie/<username>/<password>/<string:stream_id>')
@app.route('/movie/<username>/<password>/<string:stream_id>.<ext>')
def play_vod_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        app.logger.warning(f"[Play-VOD-XC] Invalid credentials for user '{username}'")
        return "Invalid credentials", 401

    twitch_vod_id = stream_id 
    app.logger.info(f"[Play-VOD-XC]: Client requested HLS-STUFE-1 for VOD {twitch_vod_id}")

    session = streamlink.Streamlink() # Frische Session

    try:
        streams = session.streams(f'twitch.tv/videos/{twitch_vod_id}')
        
        if "best" not in streams:
            app.logger.warning(f"[Play-VOD-XC]: VOD not found on Twitch: {twitch_vod_id}")
            return "VOD not found", 404
            
        app.logger.info(f"[Play-VOD-XC]: Streamlink für VOD {twitch_vod_id} erfolgreich. Nutze Stufe-1-Rewriter.")
        return _get_vod_playlist_response(session, twitch_vod_id, streams["best"].url)

    except Exception as e:
        app.logger.error(f"[Play-VOD-XC] ERROR: {e}")
        return "Error opening VOD stream", 500

# --- VOD Segment-Proxy (STUFE 2) ---
@app.route('/vod-segment-proxy/<string:twitch_vod_id>/<path:segment_path>')
def vod_segment_proxy(twitch_vod_id, segment_path):
    """
    STUFE 2: Fängt Segment-Anfragen ab, holt eine frische Playlist
    und leitet zur gültigen Twitch-CDN-URL weiter.
    """
    
    app.logger.info(f"[VOD-Proxy-S2]: Request for segment '{segment_path}' for VOD {twitch_vod_id}")
    
    session = streamlink.Streamlink()
    try:
        streams = session.streams(f'twitch.tv/videos/{twitch_vod_id}')
        
        if "best" not in streams:
            app.logger.warning(f"[VOD-Proxy-S2] Streamlink found no streams for VOD {twitch_vod_id}")
            return "Streamlink found no streams", 404
            
        media_playlist_url = streams["best"].url
        base_url = media_playlist_url.rsplit('/', 1)[0] + '/'
        
        response = session.http.get(media_playlist_url)
        response.raise_for_status()
        media_playlist_text = response.text
        
        for line in media_playlist_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            line_path = urlparse(line).path
            if line_path.endswith(segment_path):
                absolute_segment_url = urljoin(base_url, line)
                app.logger.info(f"[VOD-Proxy-S2]: Redirecting to Twitch CDN for segment.")
                return redirect(absolute_segment_url)

        app.logger.error(f"[VOD-Proxy-S2] ERROR: Segment '{segment_path}' not found in fresh playlist for VOD {twitch_vod_id}.")
        return "Segment not found in playlist", 404
        
    except Exception as e:
        app.logger.error(f"[VOD-Proxy-S2] ERROR: {e}")
        return "Error proxying segment", 500


# --- M3U Live Stream Endpoint (Nutzt HLS-Proxy) ---
@app.route('/play_live_m3u/<int:stream_id>')
def play_live_m3u(stream_id):
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        app.logger.error(f"[Play-Live-M3U] Stream mit DB-ID {stream_id} nicht in DB gefunden.")
        return "Stream not found", 404
        
    login_name = channel['login_name']
    app.logger.info(f"[Play-Live-M3U]: Client requested HLS for {login_name} (DB-ID: {stream_id})")
    
    session = streamlink.Streamlink() # Frische Session
    
    try:
        streams = session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            app.logger.warning(f"[Play-Live-M3U]: Streamlink fand keinen Stream für {login_name} (ID: {stream_id}). (Offline?)")
            return "Stream offline or not found", 404
        
        # --- START ÄNDERUNG: Nutze 302 Redirect statt HLS-Proxy ---
        app.logger.info(f"[Play-Live-M3U]: Streamlink für {login_name} erfolgreich. Sende 302 Redirect an: {streams['best'].url}")
        return redirect(streams["best"].url)
        # --- ENDE ÄNDERUNG ---
        
    except Exception as e:
        app.logger.error(f"[Play-Live-M3U] ERROR: {e}")
        return "Error opening stream", 500


# --- M3U Playlist Endpoint ---
@app.route('/playlist.m3u')
def generate_m3u():
    password = request.args.get('password', '')
    
    if not check_xc_auth(None, password):
        return "Invalid password", 401
        
    conn = get_db_connection()
    
    m3u_enabled = conn.execute("SELECT value FROM settings WHERE key = 'm3u_enabled'").fetchone()
    if not (m3u_enabled and m3u_enabled['value'] == 'true'):
        app.logger.warning("[M3U] M3U-Playlist-Anfrage, obwohl Feature deaktiviert ist.")
        return "M3U playlist feature is disabled on the server.", 404
        
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

    app.logger.info(f"[M3U] M3U-Playlist mit {len(streams)} Kanälen generiert.")
    return Response('\n'.join(m3u_content), mimetype='audio/mpegurl')

# --- M3U EPG Endpoint ---
@app.route('/epg.xml')
def generate_epg_xml():
    password = request.args.get('password', '')
    
    if not check_xc_auth(None, password):
        return "Invalid password", 401
    
    app.logger.info("[M3U-EPG] Anfrage für M3U EPG (epg.xml) erhalten.")
    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')

# --- Xtream Codes EPG Endpoint ---
@app.route('/xmltv.php')
def generate_xc_epg_xml():
    username = request.args.get('username')
    password = request.args.get('password')

    if not check_xc_auth(username, password):
        return "Invalid credentials", 401

    app.logger.info(f"[XC-EPG] Anfrage für XC EPG (xmltv.php) von User '{username}' erhalten.")
    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')


# --- TIVIMATE XTREAM CODES API ENDPOINT ---
@app.route('/player_api.php', methods=['GET', 'POST'])
def player_api():
    username = request.args.get('username', 'default')
    password = request.args.get('password', '')
    action = request.args.get('action', '')
    
    if not HOST_URL:
        app.logger.critical("[XC-API] HOST_URL Umgebungsvariable ist nicht gesetzt! API wird fehlschlagen.")
        return "HOST_URL environment variable is not set on the server.", 500

    conn = get_db_connection() 
    app.logger.info(f"[XC-API] Anfrage von User '{username}', Action: '{action}'")

    # --- 1. Authentication ---
    if action == 'get_user_info' or action == '':
        if check_xc_auth(username, password):
            app.logger.info(f"[XC-API] User '{username}' erfolgreich authentifiziert (get_user_info).")
            port = "80"
            if ':' in HOST_URL:
                port_str = HOST_URL.split(':')[-1]
                if port_str.isdigit():
                    port = port_str

            conn.close() 
            return jsonify({
                "user_info": {
                    "username": username,
                    "password": password,
                    "auth": 1,
                    "status": "Active",
                    "exp_date": None,
                    "is_trial": "0",
                    "max_connections": "1",
                    "created_at": time.time()
                },
                "server_info": {
                    "url": HOST_URL.replace("http://", "").replace("https://", "").split(':')[0],
                    "port": port,
                    "https": 1 if HOST_URL.startswith("https") else 0,
                    "server_protocol": "http",
                    "rtmp_port": "1935",
                    "timezone": "UTC",
                    "timestamp_now": int(time.time()),
                    "epg_url": "/xmltv.php" 
                }
            })
        else:
            app.logger.warning(f"[XC-API] User '{username}' Authentifizierung fehlgeschlagen (get_user_info).")
            conn.close() 
            return jsonify({"user_info": {"auth": 0, "status": "Invalid Credentials"}})

    if not check_xc_auth(username, password):
        app.logger.warning(f"[XC-API] User '{username}' Authentifizierung für Action '{action}' fehlgeschlagen.")
        conn.close() 
        return "Invalid credentials", 401

    
    # --- 2. Live Categories ---
    if action == 'get_live_categories':
        app.logger.info(f"[XC-API] Liefere Live-Kategorien für User '{username}'.")
        conn.close() 
        return jsonify([{"category_id": "1", "category_name": "Twitch Live", "parent_id": 0}])

    # --- 3. Live Streams ---
    if action == 'get_live_streams':
        streams = conn.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
        conn.close() 
        app.logger.info(f"[XC-API] Liefere {len(streams)} Live-Streams für User '{username}'.")
        
        live_streams_json = []
        for stream in streams:
            live_streams_json.append({
                "num": stream['id'],
                "name": stream['display_name'],
                "stream_type": "live",
                "stream_id": stream['id'], 
                "stream_icon": "",
                "epg_channel_id": stream['epg_channel_id'],
                "added": str(int(time.time())),
                "category_id": "1", 
                "custom_sid": "",
                "tv_archive": 0,
                # --- START ÄNDERUNG: Container-Extension irrelevant bei Redirect ---
                "container_extension": "m3u8" 
                # --- ENDE ÄNDERUNG ---
            })
        
        return jsonify(live_streams_json)
        
    # --- VOD Category Map ---
    categories_raw = conn.execute('SELECT DISTINCT category FROM vod_streams ORDER BY category').fetchall()
    category_map = {row['category']: str(i + 1) for i, row in enumerate(categories_raw)}
    
    # --- 4. VOD (Movie) Categories ---
    if action == 'get_vod_categories':
        vod_categories_json = []
        for category_name, category_id in category_map.items():
            vod_categories_json.append({
                "category_id": category_id, 
                "category_name": category_name,
                "parent_id": 0
            })
        conn.close()
        app.logger.info(f"[XC-API] Liefere {len(vod_categories_json)} VOD-Kategorien für User '{username}'.")
        return jsonify(vod_categories_json)
        
    # --- 5. VOD (Movie) Streams ---
    if action == 'get_vod_streams':
        category_id = request.args.get('category_id', None)
        
        query = 'SELECT * FROM vod_streams'
        params = []
        
        if category_id and category_id != '*':
            cat_name = None
            for name, c_id in category_map.items():
                if c_id == category_id:
                    cat_name = name
                    break
            
            if cat_name:
                query += ' WHERE category = ?'
                params.append(cat_name)
        
        query += ' ORDER BY created_at DESC'
        
        vods = conn.execute(query, params).fetchall()
        conn.close()
        app.logger.info(f"[XC-API] Liefere {len(vods)} VOD-Streams für User '{username}' (Kategorie: {category_id}).")
        
        vod_streams_json = []
        for vod in vods:
            vod_cat_id = category_map.get(vod['category'], "1") 
            
            vod_streams_json.append({
                "num": vod['id'],
                "name": vod['title'],
                "stream_type": "movie", 
                "stream_id": vod['vod_id'], 
                "stream_icon": vod['thumbnail_url'] or None, 
                "rating": 0,
                "rating_5based": 0,
                "added": str(int(time.time())),
                "category_id": vod_cat_id, 
                "container_extension": "m3u8",
                "custom_sid": "",
            })
            
        return jsonify(vod_streams_json)

    # --- 6. Series Categories (Always empty) ---
    if action == 'get_series_categories':
        app.logger.info(f"[XC-API] Liefere leere Serien-Kategorien für User '{username}'.")
        conn.close()
        return jsonify([]) 
        
    # --- 7. Series (Always empty) ---
    if action == 'get_series':
        app.logger.info(f"[XC-API] Liefere leere Serien für User '{username}'.")
        conn.close()
        return jsonify([]) 

    conn.close()
    app.logger.error(f"[XC-API] Unbekannte Action '{action}' von User '{username}'.")
    return jsonify({"error": "Unknown action"})


# --- Web UI Protected Routes (API & Main Page) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/channels', methods=['GET'])
def get_channels():
    conn = get_db_connection()
    channels = conn.execute('SELECT * FROM channels ORDER BY login_name').fetchall()
    conn.close()
    app.logger.info("[WebAPI] GET /api/channels (Lade Kanäle)")
    return jsonify([dict(ix) for ix in channels])

@app.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: 
        app.logger.warning("[WebAPI] POST /api/channels: Channel-Name fehlt.")
        return jsonify({'error': 'Channel name missing'}), 400
        
    login_name = new_channel.strip().lower()
    app.logger.info(f"[WebAPI] POST /api/channels: Versuche Kanal '{login_name}' hinzuzufügen.")
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO channels (login_name) VALUES (?)', (login_name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        app.logger.warning(f"[WebAPI] POST /api/channels: Kanal '{login_name}' existiert bereits.")
        return jsonify({'error': 'Channel already exists'}), 409
    
    try:
        new_channel_row = conn.execute('SELECT id FROM channels WHERE login_name = ?', (login_name,)).fetchone()
        if new_channel_row:
            app.logger.info(f"[WebAPI] Füge Kanal '{login_name}' (ID: {new_channel_row['id']}) auch zur live_streams Tabelle hinzu.")
            conn.execute(
                "INSERT OR IGNORE INTO live_streams (id, login_name, epg_channel_id, display_name, is_live) VALUES (?, ?, ?, ?, ?)",
                (new_channel_row['id'], login_name, f"{login_name}.tv", f"[Offline] {login_name.title()}", 0)
            )
            conn.commit()
    except Exception as e:
        app.logger.error(f"[WebAPI] Fehler beim Hinzufügen zu live_streams: {e}")
    finally:
        conn.close()
        
    app.logger.info(f"[WebAPI] Kanal '{login_name}' erfolgreich hinzugefügt.")
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    app.logger.info(f"[WebAPI] DELETE /api/channels/{channel_id}: Versuche Kanal zu löschen.")
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM channels WHERE id = ?', (channel_id,)).fetchone()
    if channel:
        app.logger.info(f"[WebAPI] Lösche VODs für Kanal '{channel['login_name']}'.")
        conn.execute('DELETE FROM vod_streams WHERE channel_login = ?', (channel['login_name'],))
    
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.execute('DELETE FROM live_streams WHERE id = ?', (channel_id,))
    
    conn.commit()
    conn.close()
    app.logger.info(f"[WebAPI] Kanal {channel_id} erfolgreich gelöscht.")
    return jsonify({'success': 'Channel deleted'}), 200

@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db_connection()
    settings_raw = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in settings_raw}
    if 'twitch_client_secret' in settings:
        settings['twitch_client_secret'] = "" 
    app.logger.info(f"[WebAPI] GET /api/settings: Lade Einstellungen.")
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    app.logger.info(f"[WebAPI] POST /api/settings: Speichere Einstellungen: {data}")
    conn = get_db_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('vod_enabled', str(data.get('vod_enabled', 'false')).lower()))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('twitch_client_id', data.get('twitch_client_id', '')))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('vod_count_per_channel', str(data.get('vod_count_per_channel', '5'))))
        
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('m3u_enabled', str(data.get('m3u_enabled', 'false')).lower()))
        
        if data.get('twitch_client_secret'):
            app.logger.info(f"[WebAPI] Ein neues Twitch-Secret wird gespeichert.")
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                         ('twitch_client_secret', data.get('twitch_client_secret')))
            
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"[WebAPI] Fehler beim Speichern der Einstellungen: {e}")
        return jsonify({'error': f'Failed to save settings: {e}'}), 500
    finally:
        conn.close()
        
    app.logger.info(f"[WebAPI] Einstellungen erfolgreich gespeichert.")
    return jsonify({'success': 'Settings saved!'}), 200
