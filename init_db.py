import sqlite3
import os

DB_PATH = '/data/channels.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"Initializing database at {DB_PATH}")

# --- Managed Channels (von dir gepflegt) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login_name TEXT NOT NULL UNIQUE
)
''')

# --- Settings (Passwort, API-Keys) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
)
''')

# --- Live Streams (vom Poller befüllt) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS live_streams (
    id INTEGER PRIMARY KEY,
    login_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    is_live BOOLEAN NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'Twitch Live'
)
''')

# --- VOD Streams (vom Poller befüllt) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS vod_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vod_id TEXT NOT NULL UNIQUE,
    channel_login TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL
)
''')

# --- Add default settings (if they don't exist) ---
default_settings = {
    'vod_enabled': 'false',
    'twitch_client_id': '',
    'twitch_client_secret': '',
    'vod_count_per_channel': '5'
}

for key, value in default_settings.items():
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

conn.commit()
conn.close()
print(f"Database {DB_PATH} is ready.")