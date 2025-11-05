import sqlite3
import os

DB_PATH = '/data/channels.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"Initializing database at {DB_PATH}")

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

# Add default settings for VODs, if they don't exist
default_settings = {
    'password_hash': None, # This one is handled by the app
    'vod_enabled': 'false',
    'twitch_client_id': '',
    'twitch_client_secret': '',
    'vod_count_per_channel': '5'
}

for key, value in default_settings.items():
    if value is not None:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

conn.commit()
conn.close()
print(f"Database {DB_PATH} is ready.")