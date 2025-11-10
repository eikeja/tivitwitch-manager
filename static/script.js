document.addEventListener('DOMContentLoaded', () => {

    // --- 1. Alle DOM-Elemente sicher auswählen ---
    // ... (alte Elemente)
    const channelList = document.getElementById('channels');
    
    // Settings
    const settingsForm = document.getElementById('settings-form');
    const liveStreamMode = document.getElementById('setting-live-mode'); // *** NEU ***
    const m3uEnabled = document.getElementById('setting-m3u-enabled');
    const m3uInfoBox = document.getElementById('m3u-setup-info');
    const vodEnabled = document.getElementById('setting-vod-enabled');
    const clientId = document.getElementById('setting-client-id');
    const clientSecret = document.getElementById('setting-client-secret');
    const vodCount = document.getElementById('setting-vod-count');
    const saveBtn = document.getElementById('save-settings-btn');
    const settingsStatus = document.getElementById('settings-status');
    // ... (Modal-Elemente)

    
    // --- 2. Alle Funktionen definieren ---
    
    function setDynamicUrls() {
        // ... (unverändert)
    }

    async function fetchChannels() {
        try {
            const response = await fetch('/api/channels');
            if (!response.ok) {
                if (response.status === 401 || response.redirected) {
                    window.location.href = '/login'; // Leitet zur Blueprint-Route weiter
                    return;
                }
                throw new Error('Network error');
            }
            // ... (Rest unverändert)
        } catch (error) {
            // ... (unverändert)
        }
    }

    async function loadSettings() {
        try {
            const response = await fetch('/api/settings');
            if (!response.ok) throw new Error('Failed to load settings');
            const settings = await response.json();
            
            if (liveStreamMode) liveStreamMode.value = settings.live_stream_mode || 'proxy'; // *** NEU ***
            if (vodEnabled) vodEnabled.checked = settings.vod_enabled === 'true';
            if (clientId) clientId.value = settings.twitch_client_id || '';
            if (vodCount) vodCount.value = settings.vod_count_per_channel || '5';
            
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

    
    // --- 3. Alle Event-Listener registrieren ---

    // ... (Copy-Buttons, Add Channel, Delete Channel unverändert) ...
    
    // "Settings" Formular-Elemente
    if (settingsForm) {
        if (m3uEnabled && m3uInfoBox) {
            m3uEnabled.addEventListener('change', () => {
                 m3uInfoBox.style.display = m3uEnabled.checked ? 'block' : 'none';
            });
        }
        
        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                if (settingsStatus) {
                    settingsStatus.textContent = 'Saving...';
                    settingsStatus.style.color = '#333';
                }
                
                const data = {
                    live_stream_mode: liveStreamMode ? liveStreamMode.value : 'proxy', // *** NEU ***
                    vod_enabled: vodEnabled ? vodEnabled.checked : false,
                    twitch_client_id: clientId ? clientId.value : '',
                    twitch_client_secret: clientSecret ? clientSecret.value : '',
                    vod_count_per_channel: vodCount ? vodCount.value : '5',
                    m3u_enabled: m3uEnabled ? m3uEnabled.checked : false
                };

                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.error || 'Failed to save');
                    
                    if (settingsStatus) {
                        settingsStatus.textContent = result.success;
                        settingsStatus.style.color = '#2b7d3d';
                    }
                    if (clientSecret) clientSecret.value = ''; 
                    
                } catch (error) {
                    if (settingsStatus) {
                        settingsStatus.textContent = error.message;
                        settingsStatus.style.color = '#fa3e3e';
                    }
                }
            });
        }
    } // Ende if(settingsForm)

    // ... (Modal-Listener und globaler Klick-Listener unverändert) ...
    
    // --- 4. Erst jetzt die Daten laden ---
    setDynamicUrls();
    if (channelList) {
        fetchChannels();
    }
    if (settingsForm) {
        loadSettings();
    }
    
});