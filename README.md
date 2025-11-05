# TiviTwitch-Manager

Tired of the bloated Twitch app and website? TiviTwitch-Manager is a lightweight, self-hosted service that scans your favorite Twitch channels and generates a dynamic `.m3u` playlist compatible with IPTV players like TiviMate, VLC, and more.

It features a simple, password-protected web interface to manage your channel list.

## Key Features

* **VLC & TiviMate Compatible:** Uses an Nginx proxy to serve the playlist, ensuring compatibility with picky players like VLC.
* **Dynamic Offline Tags:** The poller runs every 60 seconds. Offline channels are automatically tagged with `[Offline]` in your playlist.
* **Built-in Stream Proxy:** Live streams are proxied through the server (`/play/...`) to avoid Twitch IP/token issues.
* **Simple Web UI:** A clean interface to add/remove channels by name.
* **Password Protected:** The web UI is secured with a master password, which you set on first run.
* **Easy Deployment:** Runs as a single, lightweight Docker container.

## How it Works (Architecture)

This application runs as a multi-process container managed by `supervisord`:

1.  **Nginx:** Acts as the public-facing web server. It directly serves the static `playlist.m3u` file (for speed and VLC compatibility) and proxies all other requests (GUI, API, Streams) to Gunicorn.
2.  **Gunicorn (Flask):** The Python web application that serves the password-protected GUI, the API (`/api/...`), and the stream proxy (`/play/...`).
3.  **Poller (Python):** A separate background service that runs every 60 seconds. It checks the live status of all channels in the database and overwrites the static `/tmp/playlist.m3u` file.

## How to Install (using Portainer & Git)

This is the easiest way to deploy the service.

1.  **In Portainer,** go to **Stacks** -> **Add Stack**.
2.  Select **"Git Repository"** as the build method.
3.  **Repository URL:**
    ```
    [https://github.com/eikeja/tivitwitch-manager.git](https://github.com/eikeja/tivitwitch-manager.git)
    ```
4.  **Compose path:**
    ```
    docker-compose.yml
    ```
5.  Scroll down to **Environment variables** and click **"Add environment variable"**.
    * **Name:** `HOST_URL`
    * **Value:** `http://<YOUR-SERVER-IP>:8998`
    *(This is crucial. Replace `<YOUR-SERVER-IP>` with the IP address of your Docker/Portainer host. The port `8998` must match the host port you defined in the `docker-compose.yml`.)*

6.  Click **"Deploy the stack"**. The first build may take 5-10 minutes.

7.  **Done!** After the stack is running, wait 60 seconds for the poller to run, then access the services:
    * **Web UI:** `http://<YOUR-SERVER-IP>:8998` (You will be asked to create a password on first launch).
    * **TiviMate/VLC URL:** `http://<YOUR-SERVER-IP>:8998/playlist.m3u`

## How to Install (using Docker Compose)

1.  Clone this repository:
    ```bash
    git clone [https://github.com/eikeja/tivitwitch-manager.git](https://github.com/eikeja/tivitwitch-manager.git)
    cd tivitwitch-manager
    ```
2.  Edit the `docker-compose.yml` file and adjust the `ports` mapping if needed.
3.  Run the stack, making sure to set the `HOST_URL` variable:
    ```bash
    # Replace the URL with your server's public IP and port
    HOST_URL="[http://192.168.1.100:8998](http://192.168.1.100:8998)" docker-compose up -d
    ```
4.  Access the services as described above.

## How to Reset the Password

If you forget your password, you can reset it via the console.

1.  Find the name of your running container (e.g., `tivitwitch-manager`).
2.  Execute the `reset_pass.py` script inside the container:
    ```bash
    docker exec -it tivitwitch-manager python3 reset_pass.py
    ```
3.  This will delete the old password. The next time you visit the Web UI, you will be asked to set a new one.