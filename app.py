import sqlite3
import gevent
from gevent import monkey
monkey.patch_all() 

from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import streamlink
from streamlink.exceptions import NoPluginError, PluginError
import os

app = Flask(__name__)
# A secret key is required for Flask sessions
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')

# Path to the persistent database
DB_PATH = '/data/channels.db'
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

# --- Login & Setup Routes (All translated to English) ---
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

# --- Auth Middleware ---
@app.before_request
def check_auth():
    # Public endpoints that TiviMate/VLC need
    #
    # --- HIER IST DIE KORREKTUR ---
    # Wir fügen '/play_vod/' zur Ausnahmeliste hinzu
    #
    if request.path.startswith('/play/') or request.path.startswith('/play_vod/') or request.path.startswith('/static/'):
        return
        
    # Public endpoint for the M3U playlist (handled by Nginx)
    # The login/setup routes must also be public
    if request.endpoint in ['login', 'setup']:
        return

    # Check if a password is set
    if not get_password_hash():
        return redirect(url_for('setup'))
        
    # Check if the user is logged in
    if 'logged_in' not in session:
        # Allow API requests if they are protected by other means (e.g., future API key)
        # For now, just redirect to login for all non-public HTML routes
        if 'api' not in request.path:
            return redirect(url_for('login'))
        # If it is an API path, check session
        if 'logged_in' not in session:
             return jsonify({'error': 'Unauthorized'}), 401


# --- Stream Proxy Endpoints ---

# EXISTING: Live Stream Proxy
@app.route('/play/<string:login_name>')
def play_stream(login_name):
    try:
        streams = streamlink_session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            print(f"[Play-Live]: Stream not found for {login_name}")
            return "Stream offline or not found", 404
        stream_fd = streams["best"].open()
    except Exception as e:
        print(f"[Play-Live] ERROR: {e}")
        return "Error opening stream", 500
    def generate_stream():
        try:
            while True:
                data = stream_fd.read(4096)
                if not data: break
                yield data
        finally:
            stream_fd.close()
    return Response(generate_stream(), mimetype='video/mp2t')

# NEW: VOD Stream Proxy
@app.route('/play_vod/<string:video_id>')
def play_vod(video_id):
    try:
        # Note the different URL format for VODs
        streams = streamlink_session.streams(f'twitch.tv/videos/{video_id}')
        if "best" not in streams:
            print(f"[Play-VOD]: VOD not found for {video_id}")
            return "VOD not found", 404
        stream_fd = streams["best"].open()
    except Exception as e:
        print(f"[Play-VOD] ERROR: {e}")
        return "Error opening VOD stream", 500
    def generate_stream():
        try:
            while True:
                data = stream_fd.read(4096)
                if not data: break
                yield data
        finally:
            stream_fd.close()
    return Response(generate_stream(), mimetype='video/mp2t')


# --- Protected GUI/API Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# --- Channel API (Existing) ---
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
    finally:
        conn.close()
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': 'Channel deleted'}), 200

# --- NEW: Settings API ---
@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db_connection()
    settings_raw = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in settings_raw}
    
    # Never send the client secret to the frontend
    if 'twitch_client_secret' in settings:
        settings['twitch_client_secret'] = "" # Send empty string
        
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    conn = get_db_connection()
    
    try:
        # Save simple settings
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('vod_enabled', str(data.get('vod_enabled', 'false')).lower()))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('twitch_client_id', data.get('twitch_client_id', '')))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                     ('vod_count_per_channel', str(data.get('vod_count_per_channel', '5'))))
        
        # IMPORTANT: Only update the secret if a new, non-empty value is provided
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