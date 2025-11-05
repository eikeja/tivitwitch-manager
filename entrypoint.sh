#!/bin/sh
set -e

echo "[Entrypoint] Initializing database (if not exists)..."
# Run the DB init script on every start.
# This is safe because of "IF NOT EXISTS" in the SQL.
python3 init_db.py

echo "[Entrypoint] Database is ready. Starting Supervisor..."
# Start supervisor, which manages Nginx, Gunicorn, and the Poller
exec /usr/bin/supervisord -c /app/supervisord.conf