#!/usr/bin/python3
import sqlite3
import os

DB_PATH = '/data/channels.db'
print(f"Connecting to database: {DB_PATH}")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM settings WHERE key = 'password_hash'")
    if cursor.fetchone():
        conn.execute("DELETE FROM settings WHERE key = 'password_hash'")
        conn.commit()
        print("\n--- SUCCESS! ---")
        print("Password has been deleted from the database.")
        print("Open the web UI to set a new one.")
    else:
        print("\n--- INFO ---")
        print("No password was found in the database.")
except Exception as e:
    print(f"\n--- ERROR ---: {e}")
finally:
    if 'conn' in locals():
        conn.close()