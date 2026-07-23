# --- Base Image ---
FROM python:3.11-slim-trixie

# --- System Dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    streamlink \
    supervisor \
    nginx \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- App Setup ---
WORKDIR /app
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy App Code ---
COPY . .

# --- Copy Nginx Config ---
COPY nginx.conf /etc/nginx/nginx.conf

# --- Volumes & Ports ---
VOLUME /app/instance
# Nginx listens on this port inside the container
EXPOSE 8000

# --- Healthcheck (used by Docker/Coolify to detect a working deployment) ---
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# --- Entrypoint ---
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]