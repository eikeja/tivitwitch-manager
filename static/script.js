// This event listener ensures the script runs only
// after the HTML page is fully loaded.
document.addEventListener('DOMContentLoaded', () => {
    
    // --- Dynamic M3U URL Display ---
    function setDynamicPlaylistUrl() {
        const playlistUrlInput = document.getElementById('playlist-url-display');
        if (playlistUrlInput) {
            // Determines host (e.g., "192.168.178.217" or "twitch.mydomain.com")
            const host = window.location.host; 
            // Determines protocol (e.g., "http:")
            const protocol = window.location.protocol; 
            
            const m3uUrl = `${protocol}//${host}/playlist.m3u`;
            playlistUrlInput.value = m3uUrl;
        }
    }
    // Run the function on page load
    setDynamicPlaylistUrl();
    
    // --- Channel Management ---
    const form = document.getElementById('add-channel-form');
    const channelNameInput = document.getElementById('channel-name');
    const channelList = document.getElementById('channels');
    const errorMessage = document.getElementById('error-message');

    // Function to load channels from the API
    async function fetchChannels() {
        try {
            const response = await fetch('/api/channels');
            if (!response.ok) {
                // If we are not logged in, the server might redirect,
                // which throws an error. We catch this.
                if (response.status === 401 || response.redirected) {
                    window.location.href = '/login'; // Redirect to login
                    return;
                }
                throw new Error('Network error');
            }
            const channels = await response.json();
            
            channelList.innerHTML = ''; // Clear list
            
            if (channels.length === 0) {
                channelList.innerHTML = '<li>No channels added yet.</li>';
            }
            
            channels.forEach(channel => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span>${channel.login_name}</span>
                    <button data-id="${channel.id}" class="delete-btn">Delete</button>
                `;
                channelList.appendChild(li);
            });
        } catch (error) {
            // Prevent error message on login page load
            if (channelList) { 
                channelList.innerHTML = '<li>Error loading channels.</li>';
            }
        }
    }

    // Function to add a channel
    // Ensure the form exists (it doesn't on login/setup)
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const channelName = channelNameInput.value.trim();
            if (channelName === '') return;
            
            errorMessage.textContent = ''; // Clear old errors

            try {
                const response = await fetch('/api/channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: channelName })
                });
                
                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Unknown error');
                }
                
                channelNameInput.value = ''; // Clear input
                fetchChannels(); // Reload list
                
            } catch (error) {
                errorMessage.textContent = error.message;
            }
        });
    }

    // Function to delete a channel (Event Delegation)
    // Ensure the list exists
    if (channelList) {
        channelList.addEventListener('click', async (e) => {
            if (e.target.classList.contains('delete-btn')) {
                const channelId = e.target.dataset.id;
                
                if (!confirm('Are you sure you want to delete this channel?')) return;

                try {
                    const response = await fetch(`/api/channels/${channelId}`, {
                        method: 'DELETE'
                    });
                    
                    if (!response.ok) throw new Error('Error deleting channel');
                    
                    fetchChannels(); // Reload list
                    
                } catch (error) {
                    alert(error.message);
                }
            }
        });

        // Start initial load (only on the main page)
        fetchChannels();
    }
    
    
    // --- NEW: Settings Management ---
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        const vodEnabled = document.getElementById('setting-vod-enabled');
        const clientId = document.getElementById('setting-client-id');
        const clientSecret = document.getElementById('setting-client-secret');
        const vodCount = document.getElementById('setting-vod-count');
        const saveBtn = document.getElementById('save-settings-btn');
        const settingsStatus = document.getElementById('settings-status');

        // Load settings from API
        async function loadSettings() {
            try {
                const response = await fetch('/api/settings');
                if (!response.ok) throw new Error('Failed to load settings');
                const settings = await response.json();
                
                vodEnabled.checked = settings.vod_enabled === 'true';
                clientId.value = settings.twitch_client_id || '';
                vodCount.value = settings.vod_count_per_channel || '5';
                // We don't load the secret, it's write-only
                
            } catch (error) {
                settingsStatus.textContent = error.message;
                settingsStatus.style.color = '#fa3e3e';
            }
        }
        
        // Save settings to API
        saveBtn.addEventListener('click', async () => {
            settingsStatus.textContent = 'Saving...';
            settingsStatus.style.color = '#333';
            
            const data = {
                vod_enabled: vodEnabled.checked,
                twitch_client_id: clientId.value,
                twitch_client_secret: clientSecret.value, // Send empty string if not changed
                vod_count_per_channel: vodCount.value
            };

            try {
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || 'Failed to save');
                
                settingsStatus.textContent = result.success;
                settingsStatus.style.color = '#2b7d3d';
                clientSecret.value = ''; // Clear secret field after save
                
            } catch (error) {
                settingsStatus.textContent = error.message;
                settingsStatus.style.color = '#fa3e3e';
            }
        });

        // Initial load of settings
        loadSettings();
    }

    // --- NEW: Modal Logic ---
    const modal = document.getElementById('howto-modal');
    const openBtn = document.getElementById('open-modal-btn');
    const closeBtn = document.querySelector('.modal .close-btn');

    if (modal && openBtn && closeBtn) {
        // Open modal
        openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            modal.style.display = 'block';
        });

        // Close modal (via 'X' button)
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });

        // Close modal (via clicking background)
        window.addEventListener('click', (e) => {
            if (e.target == modal) {
                modal.style.display = 'none';
            }
        });
    }
});