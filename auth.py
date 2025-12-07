from flask import (
    Blueprint, render_template, request, session, redirect, url_for, flash, g, current_app
)
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, get_user_by_username
import secrets

bp = Blueprint('auth', __name__)

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        error = None
        if not username:
            error = 'Username is required.'
        elif not password or len(password) < 4:
            error = 'Password must be at least 4 characters long.'
        elif get_user_by_username(username):
            error = f"User {username} is already registered."

        if error is None:
            conn = get_db()
            try:
                # Generate a random API token for this user
                api_token = secrets.token_urlsafe(16)
                pw_hash = generate_password_hash(password)
                
                conn.execute(
                    "INSERT INTO users (username, password_hash, api_token) VALUES (?, ?, ?)",
                    (username, pw_hash, api_token)
                )
                conn.commit()
                current_app.logger.info(f"[Auth] New user registered: {username}")
                flash('Registration successful! Please login.', 'success')
                return redirect(url_for('auth.login'))
            except Exception as e:
                error = f"Registration failed: {e}"
        
        flash(error, 'error')

    return render_template('register.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = get_user_by_username(username)
        error = None
        
        if user is None:
            error = 'Incorrect username.'
        elif not check_password_hash(user['password_hash'], password):
            error = 'Incorrect password.'
            
        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username'] 
            current_app.logger.info(f"[Auth] User '{username}' logged in.")
            return redirect(url_for('views.index'))
            
        flash(error, 'error')
            
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

@bp.before_app_request
def check_web_ui_auth():
    """Middleware checks session for protected endpoints."""
    
    # Public paths that do not require Web UI auth
    public_paths = [
        '/static/',
        '/login',
        '/register',
        '/player_api.php',     
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
            return 

    if g.user is None:
         current_app.logger.info(f"[Auth] Access denied to {request.path}, redirecting to login.")
         return redirect(url_for('auth.login'))