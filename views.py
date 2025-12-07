from flask import (
    Blueprint, render_template, request, jsonify, current_app, g
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
    # Filter channels by Key user
    channels = conn.execute('SELECT * FROM channels WHERE user_id = ? ORDER BY login_name', (g.user['id'],)).fetchall()
    current_app.logger.info(f"[WebAPI] GET /api/channels for user {g.user['username']}")
    return jsonify([dict(ix) for ix in channels])

@bp.route('/api/channels', methods=['POST'])
def add_channel():
    new_channel = request.json.get('name')
    if not new_channel: 
        current_app.logger.warning("[WebAPI] POST /api/channels: Channel name missing.")
        return jsonify({'error': 'Channel name missing'}), 400
        
    login_name = new_channel.strip().lower()
    current_app.logger.info(f"[WebAPI] POST /api/channels: User {g.user['username']} adding '{login_name}'.")
    conn = get_db()
    try:
        conn.execute('INSERT INTO channels (login_name, user_id) VALUES (?, ?)', (login_name, g.user['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        current_app.logger.warning(f"[WebAPI] Channel '{login_name}' already exists for user {g.user['username']}.")
        return jsonify({'error': 'Channel already exists'}), 409
    
    # Add to live_streams if not present (global list)
    try:
        current_app.logger.info(f"[WebAPI] Ensuring '{login_name}' is in live_streams table.")
        conn.execute(
            "INSERT OR IGNORE INTO live_streams (login_name, epg_channel_id, display_name, is_live) VALUES (?, ?, ?, ?)",
            (login_name, f"{login_name}.tv", f"[Offline] {login_name.title()}", 0)
        )
        conn.commit()
    except Exception as e:
        current_app.logger.error(f"[WebAPI] Error adding to live_streams table: {e}")
    finally:
        pass
    return jsonify({'success': f"Channel '{login_name}' added"}), 201

@bp.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    current_app.logger.info(f"[WebAPI] DELETE /api/channels/{channel_id} for user {g.user['username']}.")
    conn = get_db()
    
    # We only delete the user's mapping. The poller will clean up live_streams if no one watches it anymore.
    conn.execute('DELETE FROM channels WHERE id = ? AND user_id = ?', (channel_id, g.user['id']))
    conn.commit()
    
    current_app.logger.info(f"[WebAPI] Channel {channel_id} deleted successfully.")
    return jsonify({'success': 'Channel deleted'}), 200

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Loads settings for the Web UI. Merges global settings with user-specific keys."""
    settings = get_all_settings()
    
    # Inject User's Twitch Credentials
    # (Client Secret is never sent back for security, just like global)
    settings['twitch_client_id'] = g.user['client_id'] or ""
    settings['twitch_client_secret'] = "" # Placeholder
    
    current_app.logger.info(f"[WebAPI] GET /api/settings: Loading settings for {g.user['username']}.")
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

        # 1. Save Global Settings
        save('vod_enabled', str(data.get('vod_enabled', 'false')).lower())
        save('vod_count_per_channel', str(data.get('vod_count_per_channel', '5')))
        save('m3u_enabled', str(data.get('m3u_enabled', 'false')).lower())
        save('live_stream_mode', data.get('live_stream_mode', 'proxy'))
        save('log_level', new_log_level_str)
        
        # 2. Save User-Specific Settings (Twitch Credentials)
        user_client_id = data.get('twitch_client_id', '').strip()
        user_client_secret = data.get('twitch_client_secret')
        
        if user_client_secret:
            # Update ID and Secret (if secret is provided)
            conn.execute("UPDATE users SET client_id = ?, client_secret = ? WHERE id = ?", 
                         (user_client_id, user_client_secret, g.user['id']))
            current_app.logger.info(f"[WebAPI] Updated credentials for user {g.user['username']}.")
        else:
            # Only update ID if secret is not changed
            conn.execute("UPDATE users SET client_id = ? WHERE id = ?", 
                         (user_client_id, g.user['id']))
            
        conn.commit()
        
        # *** BUG FIX & FEATURE: Dynamically adjust running app's log level ***
        if new_log_level_str == 'error':
            current_app.logger.setLevel(logging.ERROR)
            current_app.logger.warning("Log level set to ERROR at runtime.")
        else:
            current_app.logger.setLevel(logging.INFO)
            current_app.logger.info("Log level set to INFO at runtime.")
            
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"[WebAPI] Failed to save settings: {e}")
        return jsonify({'error': f'Failed to save settings: {e}'}), 500
    finally:
        conn.close()
        
    current_app.logger.info(f"[WebAPI] Settings saved successfully.")
    return jsonify({'success': 'Settings saved!'}), 200