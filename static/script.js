document.addEventListener('DOMContentLoaded', () => {

    // --- 1. Alle DOM-Elemente sicher auswählen ---
    const addChannelModal = document.getElementById('add-channel-modal');
    const form = document.getElementById('add-channel-form');
    const channelNameInput = document.getElementById('channel-name');
    const channelList = document.getElementById('channels');
    const errorMessage = document.getElementById('error-message');

    // Settings
    const settingsForm = document.getElementById('settings-form');
    const logLevel = document.getElementById('setting-log-level'); // *** NEU ***
    const liveStreamMode = document.getElementById('setting-live-mode');
    const m3uEnabled = document.getElementById('setting-m3u-enabled');
    const m3uInfoBox = document.getElementById('m3u-setup-info');
    const vodEnabled = document.getElementById('setting-vod-enabled');
    const clientId = document.getElementById('setting-client-id');
    const clientSecret = document.getElementById('setting-client-secret');
    const vodCount = document.getElementById('setting-vod-count');
    const saveBtn = document.getElementById('save-settings-btn');
    const settingsStatus = document.getElementById('settings-status');

    // Modals
    const howtoModal = document.getElementById('howto-modal');
    const openHowtoBtn = document.getElementById('open-modal-btn');
    const closeHowtoBtn = document.querySelector('#howto-modal .close-btn');
    const openAddBtn = document.getElementById('open-add-modal-btn');
    const closeAddBtn = document.querySelector('#add-channel-modal .close-btn');


    // --- 2. Alle Funktionen definieren ---

    function setDynamicUrls() {
        const host = window.location.host;
        const protocol = window.location.protocol;
        const baseUrl = `${protocol}//${host}`;
        const apiToken = document.body.dataset.apiToken;

        const serverUrlElement = document.getElementById('server-url-display');
        if (serverUrlElement) {
            serverUrlElement.value = baseUrl;
        }

        const m3uUrlElement = document.getElementById('m3u-url-display');
        if (m3uUrlElement) {
            m3uUrlElement.value = apiToken ? `${baseUrl}/playlist.m3u?token=${apiToken}` : 'Error: No Token Found';
        }

        const m3uEpgUrlElement = document.getElementById('m3u-epg-url-display');
        if (m3uEpgUrlElement) {
            m3uEpgUrlElement.value = apiToken ? `${baseUrl}/epg.xml?token=${apiToken}` : 'Error: No Token Found';
        }
    }

    async function fetchChannels() {
        try {
            const response = await fetch('/api/channels', {
                credentials: 'same-origin'
            });

            if (!response.ok) {
                if (response.status === 401 || response.redirected) {
                    window.location.href = '/login';
                    return;
                }
                throw new Error('Network error');
            }
            const channels = await response.json();

            if (channelList) {
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
            }
        } catch (error) {
            if (channelList) {
                channelList.innerHTML = '<li>Error loading channels.</li>';
            }
        }
    }

    async function loadSettings() {
        try {
            const response = await fetch('/api/settings', {
                credentials: 'same-origin'
            });

            if (!response.ok) throw new Error('Failed to load settings');
            const settings = await response.json();

            if (logLevel) logLevel.value = settings.log_level || 'info'; // *** NEU ***
            if (liveStreamMode) liveStreamMode.value = settings.live_stream_mode || 'proxy';
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

    // Copy-Buttons
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

    // "Add Channel" Formular
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const channelName = channelNameInput.value.trim();
            if (channelName === '') return;
            if (errorMessage) errorMessage.textContent = '';

            try {
                const response = await fetch('/api/channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: channelName }),
                    credentials: 'same-origin'
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
                if (errorMessage) errorMessage.textContent = error.message;
            }
        });
    }

    // "Delete Channel" Button (in der Liste)
    if (channelList) {
        channelList.addEventListener('click', async (e) => {
            if (e.target.classList.contains('delete-btn')) {
                const channelId = e.target.dataset.id;
                if (!confirm('Are you sure you want to delete this channel?')) return;
                try {
                    const response = await fetch(`/api/channels/${channelId}`, {
                        method: 'DELETE',
                        credentials: 'same-origin'
                    });

                    if (!response.ok) throw new Error('Error deleting channel');
                    fetchChannels();
                } catch (error) {
                    alert(error.message);
                }
            }
        });
    }

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
                    log_level: logLevel ? logLevel.value : 'info', // *** NEU ***
                    live_stream_mode: liveStreamMode ? liveStreamMode.value : 'proxy',
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
                        body: JSON.stringify(data),
                        credentials: 'same-origin'
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

    // "How To" Modal-Listener
    if (howtoModal && openHowtoBtn && closeHowtoBtn) {
        openHowtoBtn.addEventListener('click', (e) => {
            e.preventDefault();
            howtoModal.style.display = 'block';
        });
        closeHowtoBtn.addEventListener('click', () => {
            howtoModal.style.display = 'none';
        });
    }

    // "Add Channel" Modal-Listener
    if (addChannelModal && openAddBtn && closeAddBtn) {
        openAddBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (errorMessage) errorMessage.textContent = '';
            addChannelModal.style.display = 'block';
        });
        closeAddBtn.addEventListener('click', () => {
            addChannelModal.style.display = 'none';
        });
    }

    // Globaler Klick-Listener (für Modals schließen)
    window.addEventListener('click', (e) => {
        if (e.target == howtoModal) {
            howtoModal.style.display = 'none';
        }
        if (e.target == addChannelModal) {
            addChannelModal.style.display = 'none';
        }
    });


    // --- 4. Credentials Logic ---
    const credentialsModal = document.getElementById('credentials-modal');
    const credentialsForm = document.getElementById('credentials-form');
    const credError = document.getElementById('credentials-error');
    const modalHowtoLink = document.getElementById('modal-howto-link');

    if (credentialsForm) {
        credentialsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const cid = document.getElementById('modal-client-id').value.trim();
            const csecret = document.getElementById('modal-client-secret').value.trim();

            if (!cid || !csecret) {
                if (credError) credError.textContent = "Both Client ID and Secret are required.";
                return;
            }

            try {
                if (credError) { credError.textContent = "Saving..."; credError.style.color = "#333"; }

                // Reuse the settings API to save
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        twitch_client_id: cid,
                        twitch_client_secret: csecret
                        // other settings are not sent, so they remain unchanged (backend handles this?)
                        // actually backend expects full object usually, but let's check view.py
                        // View.py implementation handles partial updates gracefully for ID/Secret logic we added?
                        // Actually our view logic rewrites all settings. We should send current values if possible, 
                        // OR update view to handle partials. 
                        // Let's rely on the fact that we loaded settings before? 
                        // No, if we force modal before loadSettings completes?
                        // Safest: just send these two. View logic:
                        // "save('vod_enabled', ...)" -> if keys missing in data, .get() returns default/None?
                        // Wait, view.py does: data.get('vod_enabled', 'false'). 
                        // If we don't send it, it defaults to false! CAREFUL.
                        // We must read current settings first OR change view.py.
                        // Let's change this to merge with current known settings.
                    }),
                    credentials: 'same-origin'
                });

                // WAIT! sending only ID/Secret will RESET other settings to defaults in current view.py implementation.
                // We need to fetch settings first.
            } catch (error) {
                // ...
            }
        });
    }

    // --- REVISED LOGIC: Fetch settings, check keys, show modal if needed ---

    async function checkAndEnforceCredentials() {
        try {
            const response = await fetch('/api/settings', { credentials: 'same-origin' });
            if (!response.ok) return; // Login redirect handles itself
            const settings = await response.json();

            // Populate main settings form too
            if (logLevel) logLevel.value = settings.log_level || 'info';
            if (liveStreamMode) liveStreamMode.value = settings.live_stream_mode || 'proxy';
            if (vodEnabled) vodEnabled.checked = settings.vod_enabled === 'true';
            if (clientId) clientId.value = settings.twitch_client_id || '';
            if (vodCount) vodCount.value = settings.vod_count_per_channel || '5';
            if (m3uEnabled && m3uInfoBox) {
                m3uEnabled.checked = settings.m3u_enabled === 'true';
                m3uInfoBox.style.display = m3uEnabled.checked ? 'block' : 'none';
            }

            // CHECK: Is Client ID set?
            if (!settings.twitch_client_id && credentialsModal) {
                credentialsModal.style.display = 'block';
            } else if (credentialsModal) {
                credentialsModal.style.display = 'none';
            }

            return settings; // Return for use in save (to avoid overwriting defaults)

        } catch (e) {
            console.error(e);
        }
    }

    // Handle Modal Save (Safe Version)
    if (credentialsForm) {
        // Remove old listener if any (not really possible here but for clarity)
        credentialsForm.replaceWith(credentialsForm.cloneNode(true));

        // Re-select fresh element
        const newForm = document.getElementById('credentials-form');
        newForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const cid = document.getElementById('modal-client-id').value.trim();
            const csecret = document.getElementById('modal-client-secret').value.trim();
            const errorBox = document.getElementById('credentials-error');

            if (!cid || !csecret) {
                errorBox.textContent = "Both fields are required.";
                return;
            }

            errorBox.textContent = "Saving...";

            try {
                // get current settings to merge
                const responseGet = await fetch('/api/settings', { credentials: 'same-origin' });
                const currentSettings = await responseGet.json();

                const data = {
                    ...currentSettings, // Merge existing
                    twitch_client_id: cid,
                    twitch_client_secret: csecret
                };

                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                    credentials: 'same-origin'
                });

                if (!response.ok) throw new Error("Failed to save.");

                // Success
                document.getElementById('credentials-modal').style.display = 'none';
                loadSettings(); // Reload UI

            } catch (err) {
                errorBox.textContent = "Error saving credentials: " + err.message;
            }
        });
    }

    // Modal 'How To' Toggle
    const toggleHowtoBtn = document.getElementById('toggle-howto-btn');
    const howtoBox = document.getElementById('credentials-howto-box');

    if (toggleHowtoBtn && howtoBox) {
        toggleHowtoBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const isHidden = howtoBox.style.display === 'none';
            howtoBox.style.display = isHidden ? 'block' : 'none';
            toggleHowtoBtn.textContent = isHidden ? 'Hide Instructions ▲' : 'How do I get these? ▼';
        });
    }

    // Init
    setDynamicUrls();
    if (channelList) fetchChannels();
    // Replaces the old loadSettings call
    checkAndEnforceCredentials();

});