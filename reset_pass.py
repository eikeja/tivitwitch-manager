#!/usr/bin/python3
import sqlite3
import os

DB_PATH = '/data/channels.db' # NEU
print(f"Verbinde mit Datenbank: {DB_PATH}")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM settings WHERE key = 'password_hash'")
    if cursor.fetchone():
        conn.execute("DELETE FROM settings WHERE key = 'password_hash'")
        conn.commit()
        print("\n--- ERFOLG! ---")
        print("Passwort wurde aus der Datenbank gelöscht.")
    else:
        print("\n--- INFO ---")
        print("Es war kein Passwort in der Datenbank gespeichert.")
except Exception as e:
    print(f"\n--- FEHLER ---: {e}")
finally:
    if 'conn' in locals():
        conn.close()