import gevent
from gevent import monkey
monkey.patch_all() 

from flask import Flask
import logging
import sys
import os

def create_app():
    app = Flask(__name__)
    
    # --- Logging Config ---
    app.logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [Flask] [%(filename)s:%(lineno)d] - %(message)s'
    ))
    app.logger.addHandler(stream_handler)
    app.logger.info("Flask application starting...")

    # --- Konfiguration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-please-change')
    
    app.logger.info("Gevent monkey-patching angewendet.")

    # --- Blueprints registrieren ---
    from auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from views import bp as views_bp
    app.register_blueprint(views_bp)
    
    from streaming import bp as streaming_bp
    app.register_blueprint(streaming_bp)

    app.logger.info("Alle Blueprints erfolgreich registriert.")
    
    return app

# Diese Instanz wird von Gunicorn verwendet
app = create_app()