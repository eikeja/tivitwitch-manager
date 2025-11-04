# --- Basis-Image ---
FROM python:3.11-slim-trixie

# --- System-Abhängigkeiten ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    streamlink \
    supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- App-Setup ---
WORKDIR /app
COPY requirements.txt .

# Installiere Python-Pakete
RUN pip install --no-cache-dir -r requirements.txt

# --- App-Code kopieren ---
COPY . .

# --- VOLUMEN (Bleibt gleich) ---
VOLUME /data

# --- PORTS (Bleibt gleich) ---
EXPOSE 8000

# --- ENTFERNT (DER FEHLER) ---
# RUN python3 init_db.py

# --- NEU: Entrypoint hinzufügen ---
# Kopiere das neue Skript und mache es ausführbar
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# --- START-BEFEHL ---
# Starte das Entrypoint-Skript, das sich um alles kümmert
ENTRYPOINT ["/app/entrypoint.sh"]

# (Das alte CMD-Kommando wird jetzt vom Entrypoint-Skript aufgerufen)