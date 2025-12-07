from flask import (
    Blueprint, render_template, request, jsonify, current_app
)
import sqlite3
import logging
from db import get_db, get_all_settings

bp = Blueprint('views', __name__, url_prefix='')

@bp.route('/')
def index():
    """Serves the main web interface (index.html)."""
    return render_template('index.html')

# --- API Endpoints for the Web Interface ---

@bp.route('/api/channels', methods=['GET'])
def get_channels():
    conn = get_db()
    channels = conn.execute('SELECT * FROM channels ORDER BY login_name').fetchall()
    current_app.logger.info("[WebAPI] GET /api/channels (Loading channels)")
    return jsonify([dict(ix) for ix in channels])

@bp.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: 
        current_app.logger.warning("[WebAPI] POST /api/channels: Channel name missing.")
        return jsonify({'error': 'Channel name missing'}), 400
        
    login_name = new_channel.strip().lower()
    current_app.logger.info(f"[WebAPI] POST /api/channels: Attempting to add channel '{login_name}'.")
    conn = get_db()
    try:
        conn.execute('INSERT INTO channels (login_name) VALUES (?)', (login_name,))
        conn.commit()
    except sqlite3.IntegrityError:
        current_app.logger.warning(f"[WebAPI] POST /api/channels: Channel '{login_name}' already exists.")
        return jsonify({'error': 'Channel already exists'}), 409
    
    try:
        new_channel_row = conn.execute('SELECT id FROM channels WHERE login_name = ?', (login_name,)).fetchone()
        if new_channel_row:
            current_app.logger.info(f"[WebAPI] Adding channel '{login_name}' (ID: {new_channel_row['id']}) to live_streams table.")
            conn.execute(
                "INSERT OR IGNORE INTO live_streams (id, login_name, epg_channel_id, display_name, is_live) VALUES (?, ?, ?, ?, ?)",
                (new_channel_row['id'], login_name, f"{login_name}.tv", f"[Offline] {login_name.title()}", 0)
            )
            conn.commit()
    except Exception as e:
        current_app.logger.error(f"[WebAPI] Error adding to live_streams table: {e}")
    finally:
        pass
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@bp.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    current_app.logger.info(f"[WebAPI] DELETE /api/channels/{channel_id}: Attempting to delete channel.")
    conn = get_db()
    channel = conn.execute('SELECT login_name FROM channels WHERE id = ?', (channel_id,)).fetchone()
    if channel:
        current_app.logger.info(f"[WebAPI] Deleting VODs for channel '{channel['login_name']}'.")
        conn.execute('DELETE FROM vod_streams WHERE channel_login = ?', (channel['login_name'],))
    
    conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.execute('DELETE FROM live_streams WHERE id = ?', (channel_id,))
    
    conn.commit()
    current_app.logger.info(f"[WebAPI] Channel {channel_id} deleted successfully.")
    return jsonify({'success': 'Channel deleted'}), 200

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Loads settings for the Web UI."""
    settings = get_all_settings()
    current_app.logger.info(f"[WebAPI] GET /api/settings: Loading settings.")
    return jsonify(settings)

@bp.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Saves settings from the Web UI."""
    data = request.json
    current_app.logger.info(f"[WebAPI] POST /api/settings: Saving settings: {data}")
    conn = get_db()
    
    new_log_level_str = data.get('log_level', 'info')
    
    try:
        def save(key, value):
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

        # Save all settings
        save('vod_enabled', str(data.get('vod_enabled', 'false')).lower())
        save('twitch_client_id', data.get('twitch_client_id', ''))
        save('vod_count_per_channel', str(data.get('vod_count_per_channel', '5')))
        save('m3u_enabled', str(data.get('m3u_enabled', 'false')).lower())
        save('live_stream_mode', data.get('live_stream_mode', 'proxy'))
        save('log_level', new_log_level_str)
        
        if data.get('twitch_client_secret'):
            current_app.logger.info(f"[WebAPI] A new Twitch secret is being saved.")
            save('twitch_client_secret', data.get('twitch_client_secret'))
            
        conn.commit()
        
        # *** BUG FIX & FEATURE: Dynamically adjust running app's log level ***
        if new_log_level_str == 'error':
            current_app.logger.setLevel(logging.ERROR)
            # Use .logger.warning() to ensure this message always appears
            current_app.logger.warning("Log level set to ERROR at runtime.")
        else:
            current_app.logger.setLevel(logging.INFO)
            current_app.logger.info("Log level set to INFO at runtime.")
        # Note: The poller will only pick up the new level on its next restart.
            
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"[WebAPI] Failed to save settings: {e}")
        return jsonify({'error': f'Failed to save settings: {e}'}), 500
    finally:
        conn.close()
        
    current_app.logger.info(f"[WebAPI] Settings saved successfully.")
    return jsonify({'success': 'Settings saved!'}), 200