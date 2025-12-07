import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_FOLDER = os.path.join(BASE_DIR, 'instance')
if not os.path.exists(INSTANCE_FOLDER):
    os.makedirs(INSTANCE_FOLDER)

DB_PATH = os.path.join(INSTANCE_FOLDER, 'channels.db')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"Initializing database at {DB_PATH}")

# --- 1. Create tables ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    api_token TEXT UNIQUE,
    client_id TEXT,
    client_secret TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    login_name TEXT NOT NULL,
    UNIQUE(login_name, user_id),
    FOREIGN KEY(user_id) REFERENCES users(id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS live_streams (
    login_name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    is_live BOOLEAN NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'Twitch Live',
    epg_channel_id TEXT,
    stream_title TEXT,
    stream_game TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS vod_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vod_id TEXT NOT NULL,
    channel_login TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    thumbnail_url TEXT,
    UNIQUE(vod_id, channel_login)
)
''')

# --- 2. Migration block ---
print("Running database migrations (if needed)...")
def add_column(table, column, type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type}")
        print(f"  > Added '{column}' column to {table}.")
    except sqlite3.OperationalError:
        pass # Column already exists

# users table migration
add_column('users', 'client_id', 'TEXT')
add_column('users', 'client_secret', 'TEXT')
# New fields for Admin/Premium/Email
add_column('users', 'is_admin', 'INTEGER DEFAULT 0')
add_column('users', 'subscription_tier', "TEXT DEFAULT 'free'")
add_column('users', 'paypal_sub_id', 'TEXT')
add_column('users', 'subscription_end', 'TEXT')
add_column('users', 'email', 'TEXT')

# Create index for email (since ADD COLUMN cannot have UNIQUE constraint in SQLite)
try:
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email)")
    print("  > Created unique index for email.")
except Exception as e:
    print(f"  > Warning: Could not create email index: {e}")
add_column('users', 'reset_token', 'TEXT')
add_column('users', 'reset_token_expiry', 'TEXT')

add_column('live_streams', 'epg_channel_id', 'TEXT')
add_column('live_streams', 'stream_title', 'TEXT')
add_column('live_streams', 'stream_game', 'TEXT')
add_column('vod_streams', 'thumbnail_url', 'TEXT')

# --- 3. Add default settings ---
default_settings = {
    'vod_enabled': 'false',
    'twitch_client_id': '',
    'twitch_client_secret': '',
    'vod_count_per_channel': '5',
    'm3u_enabled': 'false',
    'live_stream_mode': 'proxy',
    'log_level': 'info',
    # PayPal Defaults
    'paypal_client_id': '',
    'paypal_client_secret': '',
    'paypal_plan_id': '',
    # SMTP Defaults
    'smtp_host': 'smtp.example.com',
    'smtp_port': '587',
    'smtp_user': '',
    'smtp_password': '',
    'smtp_from': 'noreply@example.com',
    'email_subject_register': 'Welcome to TiviTwitch!',
    'email_body_register': 'Welcome! Please login to start adding streams.',
    'email_subject_reset': 'Password Reset Request',
    'email_body_reset': 'Click this link to reset your password: {link}'
}

# users table migration
add_column('users', 'client_id', 'TEXT')
add_column('users', 'client_secret', 'TEXT')
# New fields for Admin/Premium/Email
add_column('users', 'is_admin', 'INTEGER DEFAULT 0')
add_column('users', 'subscription_tier', "TEXT DEFAULT 'free'")
add_column('users', 'paypal_sub_id', 'TEXT')
add_column('users', 'subscription_end', 'TEXT')
add_column('users', 'email', 'TEXT UNIQUE')
add_column('users', 'reset_token', 'TEXT')
add_column('users', 'reset_token_expiry', 'TEXT')

add_column('live_streams', 'epg_channel_id', 'TEXT')

for key, value in default_settings.items():
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

conn.commit()
conn.close()
print(f"Database {DB_PATH} is ready and migrated.")