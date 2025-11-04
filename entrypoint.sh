#!/bin/sh

# Setze 'set -e' damit das Skript bei einem Fehler abbricht
set -e

echo "[Entrypoint] Initialisiere Datenbank (falls nicht vorhanden)..."
# Führe das DB-Init-Skript JEDES Mal aus. 
# Dank "IF NOT EXISTS" in unserem SQL-Code ist das sicher.
python3 init_db.py

echo "[Entrypoint] Datenbank ist bereit. Starte Supervisor (Webserver + Poller)..."
# Führe den ursprünglichen Startbefehl aus (den, der vorher im Dockerfile CMD stand)
exec /usr/bin/supervisord -c /app/supervisord.conf