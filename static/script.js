document.addEventListener('DOMContentLoaded', () => {
    
    // --- NEW: Dynamic XC Setup Info ---
    function setDynamicSetupUrl() {
        const serverUrlElement = document.getElementById('server-url');
        if (serverUrlElement) {
            const host = window.location.host; 
            const protocol = window.location.protocol; 
            const serverUrl = `${protocol}//${host}`;
            serverUrlElement.textContent = serverUrl;
        }
    }
    setDynamicSetupUrl();

    
    // --- Channel Management (unchanged) ---
    const form = document.getElementById('add-channel-form');
    const channelNameInput = document.getElementById('channel-name');
    const channelList = document.getElementById('channels');
    const errorMessage = document.getElementById('error-message');

    async function fetchChannels() {
        try {
            const response = await fetch('/api/channels');
            if (!response.ok) {
                if (response.status === 401 || response.redirected) {
                    window.location.href = '/login'; 
                    return;
                }
                throw new Error('Network error');
            }
            const channels = await response.json();
            
            channelList.innerHTML = ''; 
            
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
            if (channelList) { 
                channelList.innerHTML = '<li>Error loading channels.</li>';
            }
        }
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const channelName = channelNameInput.value.trim();
            if (channelName === '') return;
            
            errorMessage.textContent = ''; 

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
                
                channelNameInput.value = ''; 
                fetchChannels(); 
                
            } catch (error) {
                errorMessage.textContent = error.message;
            }
        });
    }

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
                    
                    fetchChannels(); 
                    
                } catch (error) {
                    alert(error.message);
                }
            }
        });
        
        fetchChannels();
    }
    
    
    // --- Settings Management (unchanged) ---
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        const vodEnabled = document.getElementById('setting-vod-enabled');
        const clientId = document.getElementById('setting-client-id');
        const clientSecret = document.getElementById('setting-client-secret');
        const vodCount = document.getElementById('setting-vod-count');
        const saveBtn = document.getElementById('save-settings-btn');
        const settingsStatus = document.getElementById('settings-status');

        async function loadSettings() {
            try {
                const response = await fetch('/api/settings');
                if (!response.ok) throw new Error('Failed to load settings');
                const settings = await response.json();
                
                vodEnabled.checked = settings.vod_enabled === 'true';
                clientId.value = settings.twitch_client_id || '';
                vodCount.value = settings.vod_count_per_channel || '5';
                
            } catch (error) {
                settingsStatus.textContent = error.message;
                settingsStatus.style.color = '#fa3e3e';
            }
        }
        
        saveBtn.addEventListener('click', async () => {
            settingsStatus.textContent = 'Saving...';
            settingsStatus.style.color = '#333';
            
            const data = {
                vod_enabled: vodEnabled.checked,
                twitch_client_id: clientId.value,
                twitch_client_secret: clientSecret.value,
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
                clientSecret.value = ''; 
                
            } catch (error) {
                settingsStatus.textContent = error.message;
                settingsStatus.style.color = '#fa3e3e';
            }
        });

        loadSettings();
    }

    // --- Modal Logic (unchanged) ---
    const modal = document.getElementById('howto-modal');
    const openBtn = document.getElementById('open-modal-btn');
    const closeBtn = document.querySelector('.modal .close-btn');

    if (modal && openBtn && closeBtn) {
        openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            modal.style.display = 'block';
        });

        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });

        window.addEventListener('click', (e) => {
            if (e.target == modal) {
                modal.style.display = 'none';
            }
        });
    }
});