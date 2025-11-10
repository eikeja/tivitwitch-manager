import sqlite3
from werkzeug.security import check_password_hash
from flask import current_app

DB_PATH = '/data/channels.db'

def get_db_connection():
    """Establishes a connection to the DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_password_hash():
    """Fetches only the master password hash."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
        conn.close()
        return row['value'] if row else None
    except Exception as e:
        # Logger might not be available here if error happens early
        print(f"[DB-Helper-ERROR] Error fetching password hash: {e}")
        return None

def get_setting(key, default=None):
    """Fetches a single value from the settings table."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Error fetching setting '{key}': {e}")
        return default

def get_all_settings():
    """Fetches all settings (except the secret)."""
    try:
        conn = get_db_connection()
        settings_raw = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
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