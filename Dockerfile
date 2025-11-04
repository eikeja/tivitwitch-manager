# --- Basis-Image ---
# Wir nehmen ein schlankes Debian 13 (Trixie), das Python 3.11+ enthält
FROM python:3.11-slim-trixie

# --- System-Abhängigkeiten ---
# Wir brauchen 'streamlink' (für die Twitch-Logik)
# und 'supervisor' (unser Prozess-Manager)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    streamlink \
    supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- App-Setup ---
WORKDIR /app
COPY requirements.txt .

# Installiere Python-Pakete (Flask, Gunicorn, gevent, streamlink-Lib)
RUN pip install --no-cache-dir -r requirements.txt

# --- App-Code kopieren ---
# Wir kopieren alles aus unserem Ordner in das /app Verzeichnis im Container
COPY . .

# --- Volumes ---
# Wir definieren einen Mount-Punkt für die persistenten Daten
VOLUME /data

# --- Initialisierung ---
# Führe das DB-Init-Skript beim Bauen aus, um sicherzustellen, dass die Tabellen existieren
# (Es wird auf die /data/channels.db zugreifen, sobald der Container läuft)
RUN python3 init_db.py

# --- Ports ---
# Gunicorn wird (intern) auf Port 8000 laufen
EXPOSE 8000

# --- Start-Befehl ---
# Starte 'supervisord', der sich um alles andere kümmert
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]