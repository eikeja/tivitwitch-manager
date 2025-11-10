import sqlite3
from werkzeug.security import check_password_hash
from flask import current_app

DB_PATH = '/data/channels.db'

def get_db_connection():
    """Stellt eine Verbindung zur DB her."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_password_hash():
    """Holt nur den Master-Passwort-Hash."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
        conn.close()
        return row['value'] if row else None
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Fehler beim Holen des Passwort-Hashes: {e}")
        return None

def get_setting(key, default=None):
    """Holt einen beliebigen Wert aus der Settings-Tabelle."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Fehler beim Holen der Einstellung '{key}': {e}")
        return default

def get_all_settings():
    """Holt alle Einstellungen (außer dem Secret)."""
    try:
        conn = get_db_connection()
        settings_raw = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
        settings = {row['key']: row['value'] for row in settings_raw}
        if 'twitch_client_secret' in settings:
            settings['twitch_client_secret'] = "" # Secret nie an Client senden
        return settings
    except Exception as e:
        current_app.logger.error(f"[DB-Helper] Fehler beim Holen aller Einstellungen: {e}")
        return {}

def check_xc_auth(username, password):
    """Prüft TiviMate-Anmeldedaten gegen das Master-Passwort."""
    if not password:
        current_app.logger.warning("[Auth] Check_xc_auth fehlgeschlagen: Kein Passwort angegeben.")
        return False
        
    pw_hash = get_password_hash()
    if not pw_hash: 
        current_app.logger.error("[Auth] Check_xc_auth fehlgeschlagen: Kein Master-Passwort in der DB gesetzt.")
        return False
        
    is_valid = check_password_hash(pw_hash, password)
    if not is_valid:
        current_app.logger.warning(f"[Auth] Check_xc_auth fehlgeschlagen: Falsches Passwort für User '{username}'.")
        
    return is_valid