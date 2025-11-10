import gevent
from gevent import monkey
monkey.patch_all() 

from flask import Flask
import logging
import sys
import os
import sqlite3

# --- Helfer-Funktion (nur für Boot-Zeit) ---
def get_startup_log_level():
    """Liest den Log-Level aus der DB, *bevor* die App läuft."""
    level_str = 'info' # Standard
    try:
        conn = sqlite3.connect('/data/channels.db')
        row = conn.execute("SELECT value FROM settings WHERE key = 'log_level'").fetchone()
        conn.close()
        if row and row[0] == 'error':
            level_str = 'error'
    except Exception as e:
        # DB existiert vielleicht noch nicht (selten), nutze Standard
        print(f"[Boot-Warnung] Konnte Log-Level nicht aus DB lesen: {e}")
        pass
    
    print(f"[Boot] Log-Level wird auf '{level_str}' gesetzt.")
    return logging.ERROR if level_str == 'error' else logging.INFO

# --- Haupt-App ---
def create_app():
    app = Flask(__name__)
    
    # --- Logging Config (Dynamisch) ---
    log_level = get_startup_log_level()
    
    app.logger.setLevel(log_level)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [Flask] [%(filename)s:%(lineno)d] - %(message)s'
    ))
    app.logger.addHandler(stream_handler)
    app.logger.warning("------------------------------------")
    app.logger.warning(f"Flask-Anwendung startet... (Log-Level: {logging.getLevelName(log_level)})")
    app.logger.warning("------------------------------------")

    # --- Konfiguration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')
    
    app.logger.info("Gevent monkey-patching angewendet.")

    # --- Blueprints registrieren ---
    try:
        from auth import bp as auth_bp
        app.register_blueprint(auth_bp)

        from views import bp as views_bp
        app.register_blueprint(views_bp)
        
        from streaming import bp as streaming_bp
        app.register_blueprint(streaming_bp)

        app.logger.info("Alle Blueprints erfolgreich registriert.")
    except Exception as e:
        app.logger.critical(f"FEHLER beim Registrieren der Blueprints: {e}")
    
    return app

# Diese Instanz wird von Gunicorn verwendet
app = create_app()