import gevent
from gevent import monkey
monkey.patch_all() 

from flask import Flask
import logging
import sys
import os
import sqlite3

# --- Helper function (boot time only) ---
def get_startup_log_level():
    """Reads the log level from the DB *before* the app is running."""
    level_str = 'info' # Default
    try:
        # Use generated instance path
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, 'instance', 'channels.db')
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT value FROM settings WHERE key = 'log_level'").fetchone()
        conn.close()
        if row and row[0] == 'error':
            level_str = 'error'
    except Exception as e:
        # DB might not exist yet (rare), use default
        print(f"[Boot-Warning] Could not read log level from DB: {e}")
        pass
    
    print(f"[Boot] Setting log level to '{level_str}'.")
    return logging.ERROR if level_str == 'error' else logging.INFO

# --- Main App ---
def create_app():
    app = Flask(__name__)
    
    # --- Logging Config (Dynamic) ---
    log_level = get_startup_log_level()
    
    app.logger.setLevel(log_level)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [Flask] [%(filename)s:%(lineno)d] - %(message)s'
    ))
    app.logger.addHandler(stream_handler)
    app.logger.warning("-------------------------------------")
    app.logger.warning(f"Flask application starting... (Log Level: {logging.getLevelName(log_level)})")
    app.logger.warning("-------------------------------------")

    # --- Configuration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')
    
    app.logger.info("Gevent monkey-patching applied.")

    # --- Register Blueprints ---
    try:
        from auth import bp as auth_bp
        app.register_blueprint(auth_bp)

        from views import bp as views_bp
        app.register_blueprint(views_bp)
        
        from streaming import bp as streaming_bp
        app.register_blueprint(streaming_bp)

        app.logger.info("All blueprints registered successfully.")
    except Exception as e:
        app.logger.critical(f"FATAL: Failed to register blueprints: {e}")
    
    from db import init_app
    init_app(app)

    return app

# This instance is used by Gunicorn
app = create_app()