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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')
DB_PATH = '/data/channels.db'
HOST_URL = os.environ.get('HOST_URL')

streamlink_session = streamlink.Streamlink()

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
        return False
    pw_hash = get_password_hash()
    if not pw_hash: # No password set in setup
        return False
    return check_password_hash(pw_hash, password)

# --- Globale EPG XML Generator Funktion (Korrekt) ---
def generate_epg_data():
    """Generiert den XMLTV-Inhalt basierend auf der DB."""
    conn = get_db_connection()
    streams = conn.execute('SELECT * FROM live_streams WHERE is_live = 1').fetchall()
    conn.close()
    
    xml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv>']
    
    # Kanäle definieren
    for stream in streams:
        xml_content.append(f'  <channel id="{stream["epg_channel_id"]}">')
        xml_content.append(f'    <display-name>{html.escape(stream["login_name"].title())}</display-name>')
        xml_content.append('  </channel>')
        
    # Programme (EPG-Einträge) definieren
    now = datetime.utcnow()
    # EPG für 24 Stunden anzeigen (wunschgemäß)
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
            return redirect(url_for('index'))
        else:
            flash('Invalid password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# --- Web UI Auth Middleware (Korrekt) ---
@app.before_request
def check_web_ui_auth():
    public_paths = [
        '/static/',
        '/login',
        '/setup',
        '/player_api.php', # XC API
        '/live/',           # XC Live Stream
        '/movie/',          # XC VOD Stream
        '/playlist.m3u',    # M3U Playlist
        '/play_live_m3u/',  # M3U Live Stream
        '/epg.xml',         # M3U EPG
        '/xmltv.php'        # XC EPG
    ]
    
    for path in public_paths:
        if request.path.startswith(path):
            return 

    if not get_password_hash():
         return redirect(url_for('setup'))
        
    if 'logged_in' not in session:
        if 'api' in request.path: 
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('login')) 


# --- TIVIMATE STREAMING ENDPOINTS (PUBLIC) ---

def generate_stream_data(stream_fd):
    """Yields chunks of stream data."""
    try:
        while True:
            data = stream_fd.read(4096)
            if not data:
                break
            yield data
    finally:
        stream_fd.close()

# --- Live Streams (Korrekt) ---
@app.route('/live/<username>/<password>/<int:stream_id>')
@app.route('/live/<username>/<password>/<int:stream_id>.<ext>')
def play_live_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        return "Invalid credentials", 401
    
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        return "Stream not found", 404
        
    login_name = channel['login_name']
    
    try:
        streams = streamlink_session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            print(f"[Play-Live-XC]: Stream not found for {login_name} (ID: {stream_id})")
            return "Stream offline or not found", 404
        stream_fd = streams["best"].open()
    except Exception as e:
        print(f"[Play-Live-XC] ERROR: {e}")
        return "Error opening stream", 500
        
    return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')

# --- VOD Streams (Korrekt) ---
@app.route('/movie/<username>/<password>/<int:stream_id>')
@app.route('/movie/<username>/<password>/<int:stream_id>.<ext>')
def play_vod_stream_xc(username, password, stream_id, ext=None):
    if not check_xc_auth(username, password):
        return "Invalid credentials", 401

    conn = get_db_connection()
    vod = conn.execute('SELECT vod_id FROM vod_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not vod:
        print(f"[Play-VOD-XC]: VOD with DB-ID {stream_id} not found.")
        return "VOD not found", 404
        
    twitch_vod_id = vod['vod_id']

    try:
        streams = streamlink_session.streams(f'twitch.tv/videos/{twitch_vod_id}')
        if "best" not in streams:
            print(f"[Play-VOD-XC]: VOD not found on Twitch: {twitch_vod_id}")
            return "VOD not found", 404
            
        stream_url = streams["best"].url
        return redirect(stream_url)

    except Exception as e:
        print(f"[Play-VOD-XC] ERROR: {e}")
        return "Error opening VOD stream", 500

# --- M3U Live Stream Endpoint (Korrekt) ---
@app.route('/play_live_m3u/<int:stream_id>')
def play_live_m3u(stream_id):
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM live_streams WHERE id = ?', (stream_id,)).fetchone()
    conn.close()
    
    if not channel:
        return "Stream not found", 404
        
    login_name = channel['login_name']
    
    try:
        streams = streamlink_session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            print(f"[Play-Live-M3U]: Stream not found for {login_name} (ID: {stream_id})")
            return "Stream offline or not found", 404
        stream_fd = streams["best"].open()
    except Exception as e:
        print(f"[Play-Live-M3U] ERROR: {e}")
        return "Error opening stream", 500
        
    return Response(generate_stream_data(stream_fd), mimetype='video/mp2t')


# --- M3U Playlist Endpoint (Korrekt) ---
@app.route('/playlist.m3u')
def generate_m3u():
    password = request.args.get('password', '')
    
    if not check_xc_auth(None, password):
        return "Invalid password", 401
        
    conn = get_db_connection()
    
    m3u_enabled = conn.execute("SELECT value FROM settings WHERE key = 'm3u_enabled'").fetchone()
    if not (m3u_enabled and m3u_enabled['value'] == 'true'):
        return "M3U playlist feature is disabled on the server.", 404
        
    streams = conn.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
    conn.close()
    
    # EPG-URL korrekt einfügen
    epg_url = f"{HOST_URL}/epg.xml?password={password}"
    m3u_content = [f'#EXTM3U url-tvg="{epg_url}"']
    
    for stream in streams:
        channel_name = stream['display_name']
        tvg_id = stream['epg_channel_id'] 
        stream_url = f"{HOST_URL}/play_live_m3u/{stream['id']}"
        
        m3u_content.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{channel_name}" tvg-logo="" group-title="Twitch Live",{channel_name}')
        m3u_content.append(stream_url)

    return Response('\n'.join(m3u_content), mimetype='audio/mpegurl')

# --- M3U EPG Endpoint (Korrekt) ---
@app.route('/epg.xml')
def generate_epg_xml():
    password = request.args.get('password', '')
    
    if not check_xc_auth(None, password):
        return "Invalid password", 401
    
    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')

# --- Xtream Codes EPG Endpoint (Korrekt) ---
@app.route('/xmltv.php')
def generate_xc_epg_xml():
    username = request.args.get('username')
    password = request.args.get('password')

    if not check_xc_auth(username, password):
        return "Invalid credentials", 401

    xml_data = generate_epg_data()
    return Response(xml_data, mimetype='application/xml')


# --- TIVIMATE XTREAM CODES API ENDPOINT (ANGEPASST) ---
@app.route('/player_api.php', methods=['GET', 'POST'])
def player_api():
    username = request.args.get('username', 'default')
    password = request.args.get('password', '')
    action = request.args.get('action', '')
    
    if not HOST_URL:
        return "HOST_URL environment variable is not set on the server.", 500

    conn = get_db_connection() 

    # --- 1. Authentication (KORRIGIERT) ---
    if action == 'get_user_info' or action == '':
        if check_xc_auth(username, password):
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
                    # KORREKTUR: Das ist das richtige Feld, das TiviMate erwartet.
                    # Es muss nur der Pfad sein, TiviMate fügt User/Pass selbst hinzu.
                    "epg_url": "/xmltv.php" 
                }
            })
        else:
            conn.close() 
            return jsonify({"user_info": {"auth": 0, "status": "Invalid Credentials"}})

    if not check_xc_auth(username, password):
        conn.close() 
        return "Invalid credentials", 401

    
    # --- 2. Live Categories (Korrekt) ---
    if action == 'get_live_categories':
        conn.close() 
        return jsonify([{"category_id": "1", "category_name": "Twitch Live", "parent_id": 0}])

    # --- 3. Live Streams (Korrekt) ---
    if action == 'get_live_streams':
        streams = conn.execute('SELECT * FROM live_streams ORDER BY is_live DESC, login_name ASC').fetchall()
        conn.close() 
        
        live_streams_json = []
        for stream in streams:
            live_streams_json.append({
                "num": stream['id'],
                "name": stream['display_name'],
                "stream_type": "live",
                "stream_id": stream['id'], 
                "stream_icon": "",
                "epg_channel_id": stream['epg_channel_id'], # Korrekt
                "added": str(int(time.time())),
                "category_id": "1", 
                "custom_sid": "",
                "tv_archive": 0,
            })
        
        return jsonify(live_streams_json)
        
    # --- VOD-Kategorie-Map (Korrekt) ---
    categories_raw = conn.execute('SELECT DISTINCT category FROM vod_streams ORDER BY category').fetchall()
    category_map = {row['category']: str(i + 1) for i, row in enumerate(categories_raw)}
    
    # --- 4. VOD (Filme) Kategorien (Korrekt) ---
    if action == 'get_vod_categories':
        vod_categories_json = []
        for category_name, category_id in category_map.items():
            vod_categories_json.append({
                "category_id": category_id, 
                "category_name": category_name,
                "parent_id": 0
            })
        conn.close()
        return jsonify(vod_categories_json)
        
    # --- 5. VOD (Filme) Streams (Korrekt) ---
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
        
        vod_streams_json = []
        for vod in vods:
            vod_cat_id = category_map.get(vod['category'], "1") 
            
            vod_streams_json.append({
                "num": vod['id'],
                "name": vod['title'],
                "stream_type": "movie", 
                "stream_id": vod['id'], 
                "stream_icon": "", 
                "rating": 0,
                "rating_5based": 0,
                "added": str(int(time.time())),
                "category_id": vod_cat_id, 
                "container_extension": "mp4", 
                "custom_sid": "",
            })
            
        return jsonify(vod_streams_json)

    # --- 6. Serien Kategorien (Immer leer) ---
    if action == 'get_series_categories':
        conn.close()
        return jsonify([]) 
        
    # --- 7. Serien (Immer leer) ---
    if action == 'get_series':
        conn.close()
        return jsonify([]) 

    conn.close()
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
    return jsonify([dict(ix) for ix in channels])

@app.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: return jsonify({'error': 'Channel name missing'}), 400
    login_name = new_channel.strip().lower()
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO channels (login_name) VALUES (?)', (login_name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Channel already exists'}), 409
    
    try:
        new_channel_row = conn.execute('SELECT id FROM channels WHERE login_name = ?', (login_name,)).fetchone()
        if new_channel_row:
            conn.execute(
                "INSERT OR IGNORE INTO live_streams (id, login_name, epg_channel_id, display_name, is_live) VALUES (?, ?, ?, ?, ?)",
                (new_channel_row['id'], login_name, f"{login_name}.tv", f"[Offline] {login_name.title()}", 0)
            )
            conn.commit()
    except Exception as e:
        print(f"Error adding to live_streams table: {e}")
    finally:
        conn.close()
        
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM channels WHERE id = ?', (channel_id,)).fetchone()
    if channel:
        conn.execute('DELETE FROM vod_streams WHERE channel_login = ?', (channel['login_name'],))
    
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.execute('DELETE FROM live_streams WHERE id = ?', (channel_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'success': 'Channel deleted'}), 200

@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db_connection()
    settings_raw = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in settings_raw}
    if 'twitch_client_secret' in settings:
        settings['twitch_client_secret'] = "" 
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
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
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                         ('twitch_client_secret', data.get('twitch_client_secret')))
            
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Failed to save settings: {e}'}), 500
    finally:
        conn.close()
        
    return jsonify({'success': 'Settings saved!'}), 200