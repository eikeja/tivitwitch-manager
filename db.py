import sqlite3
from werkzeug.security import check_password_hash
from flask import current_app, g

DB_PATH = '/data/channels.db'

def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Closes the database again at the end of the request."""
    db = g.pop('db', None)

    if db is not None:
        db.close()

def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    app.teardown_appcontext(close_db)

def get_user_by_username(username):
    """Fetches a user by username."""
    try:
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return row
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Error fetching user '{username}': {e}")
        return None

def get_user_by_token(token):
    """Fetches a user by their API token."""
    try:
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE api_token = ?", (token,)).fetchone()
        return row
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Error fetching user by token: {e}")
        return None

def get_setting(key, default=None):
    """Fetches a single value from the settings table."""
    try:
        db = get_db()
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else default
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Error fetching setting '{key}': {e}")
        return default

def get_all_settings():
    """Fetches all settings (except the secret)."""
    try:
        db = get_db()
        settings_raw = db.execute("SELECT key, value FROM settings").fetchall()
        settings = {row['key']: row['value'] for row in settings_raw}
        if 'twitch_client_secret' in settings:
            settings['twitch_client_secret'] = "" # Never send secret to client
        return settings
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Error fetching all settings: {e}")
        return {}

def check_xc_auth(username, password):
    """Checks credentials against the users table."""
    if not username or not password:
        return False
        
    user = get_user_by_username(username)
    if not user:
        current_app.logger.warning(f"[Auth] Check_xc_auth failed: User '{username}' not found.")
        return False

    is_valid = check_password_hash(user['password_hash'], password)
    if not is_valid:
        current_app.logger.warning(f"[Auth] Check_xc_auth failed: Invalid password for user '{username}'.")
        
    return is_valid
