from flask import (
    Blueprint, render_template, request, session, redirect, url_for, flash, g, current_app
)
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, get_password_hash

bp = Blueprint('auth', __name__)

@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if get_password_hash():
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        if not password or len(password) < 4:
            flash('Password must be at least 4 characters long.', 'error')
            return redirect(url_for('auth.setup'))
            
        pw_hash = generate_password_hash(password)
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ('password_hash', pw_hash))
        conn.commit()
        conn.close()
        
        session['logged_in'] = True
        flash('Password set successfully!', 'success')
        current_app.logger.info("[Auth] New master password has been set.")
        return redirect(url_for('views.index'))
        
    return render_template('setup.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not get_password_hash():
        return redirect(url_for('auth.setup'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        if check_password_hash(get_password_hash(), password):
            session['logged_in'] = True
            current_app.logger.info("[Auth] Web UI login successful.")
            return redirect(url_for('views.index'))
        else:
            current_app.logger.warning("[Auth] Web UI login failed (invalid password).")
            flash('Invalid password.', 'error')
            
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'success')
    current_app.logger.info("[Auth] Web UI logout.")
    return redirect(url_for('auth.login'))

@bp.before_app_request
def check_web_ui_auth():
    """This middleware checks the Web UI session for all protected endpoints."""
    
    # Public paths that do not require auth
    public_paths = [
        '/static/',
        '/login',
        '/setup',
        '/player_api.php',     # Player endpoints
        '/live/',
        '/movie/',
        '/vod-segment-proxy/',
        '/playlist.m3u',
        '/play_live_m3u/',
        '/epg.xml',
        '/xmltv.php'
    ]
    
    for path in public_paths:
        if request.path.startswith(path):
            return # Public path, no auth check needed

    # If we are here, the path is protected.
    
    if not get_password_hash():
         current_app.logger.info(f"[Auth] No password set, redirecting to /setup (from {request.path})")
         return redirect(url_for('auth.setup'))
        
    if 'logged_in' not in session:
        current_app.logger.warning(f"[Auth] Not logged in, redirecting to /login (from {request.path})")
        return redirect(url_for('auth.login'))