import sqlite3
import os

DB_PATH = '/data/channels.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"Initializing database at {DB_PATH}")

# --- 1. Create tables if they don't exist (unverändert) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login_name TEXT NOT NULL UNIQUE
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
    id INTEGER PRIMARY KEY,
    login_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    is_live BOOLEAN NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'Twitch Live'
)
''')

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

# --- 2. NEU: Migrations-Block (fügt EPG-Spalten hinzu, falls sie fehlen) ---
print("Running database migrations (if needed)...")
try:
    cursor.execute("ALTER TABLE live_streams ADD COLUMN epg_channel_id TEXT")
    print("  > Added 'epg_channel_id' column to live_streams.")
except sqlite3.OperationalError:
    pass # Spalte existiert bereits, alles gut

try:
    cursor.execute("ALTER TABLE live_streams ADD COLUMN stream_title TEXT")
    print("  > Added 'stream_title' column to live_streams.")
except sqlite3.OperationalError:
    pass # Spalte existiert bereits, alles gut

try:
    cursor.execute("ALTER TABLE live_streams ADD COLUMN stream_game TEXT")
    print("  > Added 'stream_game' column to live_streams.")
except sqlite3.OperationalError:
    pass # Spalte existiert bereits, alles gut
# --- Ende Migrations-Block ---


# --- 3. Add default settings (unverändert) ---
default_settings = {
    'vod_enabled': 'false',
    'twitch_client_id': '',
    'twitch_client_secret': '',
    'vod_count_per_channel': '5',
    'm3u_enabled': 'false'
}

for key, value in default_settings.items():
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

conn.commit()
conn.close()
print(f"Database {DB_PATH} is ready and migrated.")