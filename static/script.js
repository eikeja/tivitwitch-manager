document.addEventListener('DOMContentLoaded', () => {
    
    function setDynamicUrls() {
        const host = window.location.host; 
        const protocol = window.location.protocol; 
        const baseUrl = `${protocol}//${host}`;
        
        const serverUrlElement = document.getElementById('server-url-display');
        if (serverUrlElement) {
            serverUrlElement.value = baseUrl;
        }
        
        const m3uUrlElement = document.getElementById('m3u-url-display');
        if (m3uUrlElement) {
            m3uUrlElement.value = `${baseUrl}/playlist.m3u?password=YOUR_PASSWORD_HERE`;
        }
        
        const m3uEpgUrlElement = document.getElementById('m3u-epg-url-display');
        if (m3uEpgUrlElement) {
            m3uEpgUrlElement.value = `${baseUrl}/epg.xml?password=YOUR_PASSWORD_HERE`;
        }
    }
    setDynamicUrls();

    document.querySelectorAll('.copy-btn').forEach(button => {
        button.addEventListener('click', () => {
            const targetId = button.dataset.copyTarget;
            const targetInput = document.querySelector(targetId);
            
            if (targetInput) {
                targetInput.select();
                targetInput.setSelectionRange(0, 99999); 
                
                try {
                    navigator.clipboard.writeText(targetInput.value);
                    const originalText = button.textContent;
                    button.textContent = 'Copied!';
                    button.style.backgroundColor = 'var(--accent-green)';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.backgroundColor = ''; 
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy text: ', err);
                }
            }
        });
    });

    
    // --- Channel Management ---
    const addChannelModal = document.getElementById('add-channel-modal');
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
                if (addChannelModal) {
                    addChannelModal.style.display = 'none';
                }
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
        // WICHTIG: fetchChannels() wird jetzt hier aufgerufen,
        // nachdem alle Event-Listener sicher registriert wurden.
        fetchChannels();
    }
    
    
    // --- Settings Management ---
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        const m3uEnabled = document.getElementById('setting-m3u-enabled');
        const m3uInfoBox = document.getElementById('m3u-setup-info'); // Das war der Fehlerpunkt
        
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
                
                // KORREKTUR: PrÃ¼fen, ob die M3U-Elemente existieren
                if (m3uEnabled && m3uInfoBox) {
                    m3uEnabled.checked = settings.m3u_enabled === 'true';
                    m3uInfoBox.style.display = m3uEnabled.checked ? 'block' : 'none';
                }
                
            } catch (error) {
                if (settingsStatus) {
                    settingsStatus.textContent = error.message;
                    settingsStatus.style.color = '#fa3e3e';
                }
            }
        }
        
        // KORREKTUR: PrÃ¼fen, ob die M3U-Elemente existieren
        if (m3uEnabled && m3uInfoBox) {
            m3uEnabled.addEventListener('change', () => {
                 m3uInfoBox.style.display = m3uEnabled.checked ? 'block' : 'none';
            });
        }
        
        saveBtn.addEventListener('click', async () => {
            settingsStatus.textContent = 'Saving...';
            settingsStatus.style.color = '#333';
            
            const data = {
                vod_enabled: vodEnabled.checked,
                twitch_client_id: clientId.value,
                twitch_client_secret: clientSecret.value,
                vod_count_per_channel: vodCount.value,
                m3u_enabled: m3uEnabled ? m3uEnabled.checked : false // Sichere PrÃ¼fung
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

        // WICHTIG: loadSettings() wird jetzt hier aufgerufen
        loadSettings();
    }

    // --- Modal Logic ---
    const howtoModal = document.getElementById('howto-modal');
    const openHowtoBtn = document.getElementById('open-modal-btn');
    const closeHowtoBtn = document.querySelector('#howto-modal .close-btn');

    if (howtoModal && openHowtoBtn && closeHowtoBtn) {
        openHowtoBtn.addEventListener('click', (e) => {
            e.preventDefault();
            howtoModal.style.display = 'block';
        });
        closeHowtoBtn.addEventListener('click', () => {
            howtoModal.style.display = 'none';
        });
    }

    const openAddBtn = document.getElementById('open-add-modal-btn');
    const closeAddBtn = document.querySelector('#add-channel-modal .close-btn');

    if (addChannelModal && openAddBtn && closeAddBtn) {
        openAddBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if(errorMessage) errorMessage.textContent = '';
            addChannelModal.style.display = 'block';
        });
        closeAddBtn.addEventListener('click', () => {
            addChannelModal.style.display = 'none';
        });
    }

    window.addEventListener('click', (e) => {
        if (e.target == howtoModal) {
            howtoModal.style.display = 'none';
        }
        if (e.target == addChannelModal) {
            addChannelModal.style.display = 'none';
        }
    });
});