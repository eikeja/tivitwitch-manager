from flask import (
    Blueprint, render_template, request, jsonify, current_app
)
import sqlite3
from db import get_db_connection, get_all_settings

bp = Blueprint('views', __name__, url_prefix='')

@bp.route('/')
def index():
    """Zeigt die Haupt-Web-Oberfläche (index.html)."""
    return render_template('index.html')

# --- API-Endpunkte für die Web-Oberfläche ---

@bp.route('/api/channels', methods=['GET'])
def get_channels():
    conn = get_db_connection()
    channels = conn.execute('SELECT * FROM channels ORDER BY login_name').fetchall()
    conn.close()
    current_app.logger.info("[WebAPI] GET /api/channels (Lade Kanäle)")
    return jsonify([dict(ix) for ix in channels])

@bp.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: 
        current_app.logger.warning("[WebAPI] POST /api/channels: Channel-Name fehlt.")
        return jsonify({'error': 'Channel name missing'}), 400
        
    login_name = new_channel.strip().lower()
    current_app.logger.info(f"[WebAPI] POST /api/channels: Versuche Kanal '{login_name}' hinzuzufügen.")
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO channels (login_name) VALUES (?)', (login_name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        current_app.logger.warning(f"[WebAPI] POST /api/channels: Kanal '{login_name}' existiert bereits.")
        return jsonify({'error': 'Channel already exists'}), 409
    
    try:
        new_channel_row = conn.execute('SELECT id FROM channels WHERE login_name = ?', (login_name,)).fetchone()
        if new_channel_row:
            current_app.logger.info(f"[WebAPI] Füge Kanal '{login_name}' (ID: {new_channel_row['id']}) auch zur live_streams Tabelle hinzu.")
            conn.execute(
                "INSERT OR IGNORE INTO live_streams (id, login_name, epg_channel_id, display_name, is_live) VALUES (?, ?, ?, ?, ?)",
                (new_channel_row['id'], login_name, f"{login_name}.tv", f"[Offline] {login_name.title()}", 0)
            )
            conn.commit()
    except Exception as e:
        current_app.logger.error(f"[WebAPI] Fehler beim Hinzufügen zu live_streams: {e}")
    finally:
        conn.close()
        
    current_app.logger.info(f"[WebAPI] Kanal '{login_name}' erfolgreich hinzugefügt.")
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@bp.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    current_app.logger.info(f"[WebAPI] DELETE /api/channels/{channel_id}: Versuche Kanal zu löschen.")
    conn = get_db_connection()
    channel = conn.execute('SELECT login_name FROM channels WHERE id = ?', (channel_id,)).fetchone()
    if channel:
        current_app.logger.info(f"[WebAPI] Lösche VODs für Kanal '{channel['login_name']}'.")
        conn.execute('DELETE FROM vod_streams WHERE channel_login = ?', (channel['login_name'],))
    
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.execute('DELETE FROM live_streams WHERE id = ?', (channel_id,))
    
    conn.commit()
    conn.close()
    current_app.logger.info(f"[WebAPI] Kanal {channel_id} erfolgreich gelöscht.")
    return jsonify({'success': 'Channel deleted'}), 200

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Lädt Einstellungen für die Web-UI."""
    settings = get_all_settings()
    current_app.logger.info(f"[WebAPI] GET /api/settings: Lade Einstellungen.")
    return jsonify(settings)

@bp.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Speichert Einstellungen aus der Web-UI."""
    data = request.json
    current_app.logger.info(f"[WebAPI] POST /api/settings: Speichere Einstellungen: {data}")
    conn = get_db_connection()
    
    try:
        def save(key, value):
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

        # Speichere alle Einstellungen
        save('vod_enabled', str(data.get('vod_enabled', 'false')).lower())
        save('twitch_client_id', data.get('twitch_client_id', ''))
        save('vod_count_per_channel', str(data.get('vod_count_per_channel', '5')))
        save('m3u_enabled', str(data.get('m3u_enabled', 'false')).lower())
        
        # *** DEIN NEUES FEATURE ***
        save('live_stream_mode', data.get('live_stream_mode', 'proxy'))
        
        # Speichere das Secret nur, wenn ein neues eingegeben wurde
        if data.get('twitch_client_secret'):
            current_app.logger.info(f"[WebAPI] Ein neues Twitch-Secret wird gespeichert.")
            save('twitch_client_secret', data.get('twitch_client_secret'))
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"[WebAPI] Fehler beim Speichern der Einstellungen: {e}")
        return jsonify({'error': f'Failed to save settings: {e}'}), 500
    finally:
        conn.close()
        
    current_app.logger.info(f"[WebAPI] Einstellungen erfolgreich gespeichert.")
    return jsonify({'success': 'Settings saved!'}), 200