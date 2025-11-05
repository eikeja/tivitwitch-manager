# --- Base Image ---
FROM python:3.11-slim-trixie

# --- System Dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    streamlink \
    supervisor \
    nginx \
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
VOLUME /data
# Nginx listens on this port inside the container
EXPOSE 8000

# --- Entrypoint ---
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]