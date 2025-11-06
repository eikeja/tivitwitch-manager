# TiviTwitch-Manager

Tired of the bloated Twitch app and website? TiviTwitch-Manager is a lightweight, self-hosted service that scans your favorite Twitch channels and provides them as a clean IPTV source for players like TiviMate.

It provides a full **Xtream Codes API** for a rich experience (Live TV, VODs, EPG) and a fallback **.m3u playlist** for simple players (Live TV only). It features a simple, password-protected web interface to manage your channel list and API credentials.

## Key Features

* **Full Xtream Codes API:** The primary way to connect. Provides separate, clean categories for Live TV (with EPG) and VODs (in the "Movies" tab).
* **VOD & EPG Support:** Automatically fetches Twitch VODs (past broadcasts) and EPG data (current stream title and game) for all managed channels.
* **M3U Fallback:** Includes an optional, password-protected `.m3u` & `epg.xml` output for simple players like VLC that don't support Xtream Codes.
* **Smart Polling:** A background poller runs every 60 seconds to query the official Twitch API for live status, EPG data, and VODs, saving everything to a persistent database.
* **Efficient Streaming:** Live streams are proxied through the server to ensure compatibility. VODs are redirected directly to the Twitch CDN for efficient playback and seeking (spooling).
* **Simple Web UI:** A clean interface to add/remove channels and manage settings.
* **Password Protected:** The Web UI and all player endpoints are secured with a single master password.
* **Easy Deployment:** Runs as a single, lightweight Docker container.

## How it Works (Architecture)

This application runs as a multi-process container managed by `supervisord`:

1.  **Nginx:** Acts as the public-facing web server. It proxies all requests (GUI, API, Streams) to the Gunicorn application.
2.  **Gunicorn (Flask):** The Python web application "brain". It serves the Web UI, the Xtream Codes API (`/player_api.php`), the dynamic M3U/EPG endpoints, and handles all stream requests.
3.  **Poller (Python):** A separate background service that runs every 60 seconds. It polls the Twitch API for the status of all channels, fetching live status, EPG data, and recent VODs, and writes this information to the `/data/channels.db` SQLite database.

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

6.  Click **"Deploy the stack"**.

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

## Configuration & Player Setup

Once the container is running, all configuration is done in the Web UI.

1.  Access the Web UI: `http://<YOUR-SERVER-IP>:8998`
2.  You will be asked to create a master password on first launch. This password is used for both the UI and the player login.
3.  Add your favorite Twitch channels by name.
4.  **(Optional for VODs):** Go to **Settings**.
    * Enable **"Enable Twitch VODs"**.
    * Click the "How do I get Twitch Credentials?" link and follow the modal to get a Client ID and Secret from Twitch.
    * Enter your credentials and click **Save**.
5.  **(Optional for M3U):** Go to **Settings** and enable **"Enable M3U Playlist"**.

### Method 1: Xtream Codes (Recommended for TiviMate)

This is the best method, providing Live TV, EPG, and VODs automatically.

* **Playlist Type:** `Xtream Codes`
* **Server Address:** `http://<YOUR-SERVER-IP>:8998`
* **Username:** `(can be anything, e.g. "twitch")`
* **Password:** `(your master password)`

TiviMate will automatically load Live TV, EPG data, and place VODs in the "Movies" section.

### Method 2: M3U Playlist (For VLC & Simple Players)

This method provides **Live TV and EPG only**. It must be enabled in the Web UI settings first.

* **Playlist URL:**
    `http://<YOUR-SERVER-IP>:8998/playlist.m3u?password=<YOUR_PASSWORD>`
* **EPG URL:**
    `http://<YOUR-SERVER-IP>:8998/epg.xml?password=<YOUR_PASSWORD>`

*(Replace `<YOUR_PASSWORD>` with your actual master password)*

## How to Reset the Password

If you forget your password, you can reset it via the console.

1.  Find the name of your running container (e.g., `tivitwitch-manager`).
2.  Execute the `reset_pass.py` script inside the container:
    ```bash
    docker exec -it tivitwitch-manager python3 reset_pass.py
    ```
3.  This will delete the old password. The next time you visit the Web UI, you will be asked to set a new one.