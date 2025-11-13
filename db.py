import sqlite3
from werkzeug.security import check_password_hash
from flask import current_app, g

DB_PATH = 'instance/channels.db'

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

def get_password_hash():
    """Fetches only the master password hash."""
    try:
        db = get_db()
        row = db.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
        return row['value'] if row else None
    except Exception as e:
        # Logger might not be available here if error happens early
        print(f"[DB-Helper-ERROR] Error fetching password hash: {e}")
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
    """Checks TiviMate credentials against the master password."""
    if not password:
        current_app.logger.warning("[Auth] Check_xc_auth failed: No password provided.")
        return False
        
    pw_hash = get_password_hash()
    if not pw_hash: 
        current_app.logger.error("[Auth] Check_xc_auth failed: No master password set in DB.")
        return False
        
    is_valid = check_password_hash(pw_hash, password)
    if not is_valid:
        current_app.logger.warning(f"[Auth] Check_xc_auth failed: Invalid password for user '{username}'.")
        
    return is_valid
