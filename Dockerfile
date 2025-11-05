# --- Basis-Image ---
FROM python:3.11-slim-trixie

# --- System-Abhängigkeiten ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    streamlink \
    supervisor \
    nginx \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- App-Setup ---
WORKDIR /app
COPY requirements.txt .

# Installiere Python-Pakete
RUN pip install --no-cache-dir -r requirements.txt

# --- App-Code kopieren ---
COPY . .

# --- Nginx-Konfiguration kopieren ---
COPY nginx.conf /etc/nginx/nginx.conf

# --- VOLUMEN / PORTS ---
VOLUME /data
EXPOSE 8000

# --- Entrypoint (unverändert) ---
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]