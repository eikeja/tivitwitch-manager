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
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-bitte-in-prod-aendern')

# --- NEU: Dynamische Pfade ---
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

# --- Login-Routen (identisch zu v2.3) ---
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if get_password_hash():
        return redirect(url_for('login'))
    if request.method == 'POST':
        password = request.form.get('password')
        if not password or len(password) < 4:
            flash('Passwort muss mindestens 4 Zeichen lang sein.', 'error')
            return redirect(url_for('setup'))
        pw_hash = generate_password_hash(password)
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ('password_hash', pw_hash))
        conn.commit()
        conn.close()
        session['logged_in'] = True
        flash('Passwort erfolgreich festgelegt!', 'success')
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
            flash('Falsches Passwort.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Du wurdest ausgeloggt.', 'success')
    return redirect(url_for('login'))

# --- Auth-Middleware (identisch zu v2.3) ---
@app.before_request
def check_auth():
    if request.path.startswith('/play/') or request.path.startswith('/static/'):
        return
    if request.endpoint in ['login', 'setup', 'get_playlist']: # /playlist.m3u muss öffentlich sein
        return
    if not get_password_hash():
        return redirect(url_for('setup'))
    if 'logged_in' not in session:
        return redirect(url_for('login'))

# --- Kern-Anwendung ---
@app.route('/play/<string:login_name>')
def play_stream(login_name):
    try:
        streams = streamlink_session.streams(f'twitch.tv/{login_name}')
        if "best" not in streams:
            print(f"[Play]: Stream nicht gefunden für {login_name}")
            return "Stream offline oder nicht gefunden", 404
        stream_fd = streams["best"].open()
    except Exception as e:
        print(f"[Play] FEHLER: {e}")
        return "Fehler beim Öffnen des Streams", 500
    def generate_stream():
        try:
            while True:
                data = stream_fd.read(4096)
                if not data: break
                yield data
        finally:
            stream_fd.close()
    return Response(generate_stream(), mimetype='video/mp2t')

# --- GUI-Routen (identisch zu v2.3) ---
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
# ... (Rest der API-Routen ist identisch) ...
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: return jsonify({'error': 'Kanalname fehlt'}), 400
    login_name = new_channel.strip().lower()
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO channels (login_name) VALUES (?)', (login_name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Kanal existiert bereits'}), 409
    finally:
        conn.close()
    return jsonify({'success': f"Kanal '{login_name}' hinzugefügt"}), 201

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': 'Kanal gelöscht'}), 200

# --- NEU: Nginx bedient die statische Datei nicht mehr ---
# Wir müssen die /playlist.m3u Route wieder in Flask einbauen
@app.route('/playlist.m3u')
def get_playlist():
    # Wir lesen einfach die statische Datei, die der Poller erstellt
    try:
        with open('/data/playlist.m3u', 'r') as f:
            content = f.read()
        return Response(content, mimetype='application/vnd.apple.mpegurl')
    except FileNotFoundError:
        return Response("#EXTM3U\n", mimetype='application/vnd.apple.mpegurl')