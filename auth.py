from flask import (
    Blueprint, render_template, request, session, redirect, url_for, flash, g, current_app
)
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db, get_user_by_username, get_setting
from utils.mail import send_mail
import secrets
import datetime

bp = Blueprint('auth', __name__)

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        
        error = None
        if not username:
            error = 'Username is required.'
        elif not email or '@' not in email:
            error = 'Valid email is required.'
        elif not password or len(password) < 4:
            error = 'Password must be at least 4 characters long.'
        elif get_user_by_username(username):
            error = f"User {username} is already registered."
        else:
            conn = get_db()
            existing_email = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing_email:
                error = f"Email {email} is already registered."

        if error is None:
            try:
                # Generate a random API token for this user
                api_token = secrets.token_urlsafe(16)
                pw_hash = generate_password_hash(password)
                
                conn.execute(
                    "INSERT INTO users (username, password_hash, api_token, email) VALUES (?, ?, ?, ?)",
                    (username, pw_hash, api_token, email)
                )
                conn.commit()
                current_app.logger.info(f"[Auth] New user registered: {username} ({email})")
                
                # Send Welcome Email
                subject = get_setting('email_subject_register', 'Welcome!')
                body = get_setting('email_body_register', 'Welcome to TiviTwitch!')
                send_mail(email, subject, body)

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

@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        
        if user:
            token = secrets.token_urlsafe(32)
            # Token valid for 1 hour
            expiry = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
            
            conn.execute("UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?", (token, expiry, user['id']))
            conn.commit()
            
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            subject = get_setting('email_subject_reset', 'Password Reset')
            body_template = get_setting('email_body_reset', 'Link: {link}')
            body = body_template.replace('{link}', reset_link)
            
            if send_mail(email, subject, body):
                flash('Password reset link sent to your email.', 'success')
            else:
                flash('Failed to send email. Check logs/settings.', 'error')
        else:
            # Don't reveal user existence? Or do? For this app, it's fine.
            flash('Email not found.', 'error')
            
    return render_template('forgot_password.html')

@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE reset_token = ?", (token,)).fetchone()
    
    if not user:
        flash('Invalid or expired token.', 'error')
        return redirect(url_for('auth.login'))
        
    # Check expiry
    expiry = datetime.datetime.fromisoformat(user['reset_token_expiry'])
    if datetime.datetime.now() > expiry:
        flash('Token expired.', 'error')
        return redirect(url_for('auth.forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        if not password or len(password) < 4:
            flash('Password too short.', 'error')
        else:
            pw_hash = generate_password_hash(password)
            conn.execute("UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL WHERE id = ?", (pw_hash, user['id']))
            conn.commit()
            flash('Password reset successful. Please login.', 'success')
            return redirect(url_for('auth.login'))
            
    return render_template('reset_password.html')

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
        '/forgot-password',
        '/reset-password',
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