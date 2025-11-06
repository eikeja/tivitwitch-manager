document.addEventListener('DOMContentLoaded', () => {
    
    // --- Dynamic Setup Infos (ANGEPASST) ---
    function setDynamicUrls() {
        const host = window.location.host; 
        const protocol = window.location.protocol; 
        const baseUrl = `${protocol}//${host}`;
        
        // NEU: XC URL (jetzt ein <input>)
        const serverUrlElement = document.getElementById('server-url-display');
        if (serverUrlElement) {
            serverUrlElement.value = baseUrl; // .value statt .textContent
        }
        
        // M3U Playlist URL
        const m3uUrlElement = document.getElementById('m3u-url-display');
        if (m3uUrlElement) {
            m3uUrlElement.value = `${baseUrl}/playlist.m3u?password=YOUR_PASSWORD_HERE`;
        }
        
        // M3U EPG URL
        const m3uEpgUrlElement = document.getElementById('m3u-epg-url-display');
        if (m3uEpgUrlElement) {
            m3uEpgUrlElement.value = `${baseUrl}/epg.xml?password=YOUR_PASSWORD_HERE`;
        }
    }
    setDynamicUrls();

    // --- NEU: Click-to-Copy Logic ---
    document.querySelectorAll('.copy-btn').forEach(button => {
        button.addEventListener('click', () => {
            const targetId = button.dataset.copyTarget;
            const targetInput = document.querySelector(targetId);
            
            if (targetInput) {
                targetInput.select();
                targetInput.setSelectionRange(0, 99999); // FÃ¼r Mobile
                
                try {
                    navigator.clipboard.writeText(targetInput.value);
                    
                    // Visuelles Feedback
                    const originalText = button.textContent;
                    button.textContent = 'Copied!';
                    button.style.backgroundColor = 'var(--accent-green)';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.backgroundColor = ''; // ZurÃ¼ck zum CSS-Standard
                    }, 2000);
                    
                } catch (err) {
                    console.error('Failed to copy text: ', err);
                }
            }
        });
    });

    
    // --- Channel Management (Formular ist jetzt im Modal) ---
    const addChannelModal = document.getElementById('add-channel-modal'); // NEU
    const form = document.getElementById('add-channel-form');
    const channelNameInput = document.getElementById('channel-name');
    const channelList = document.getElementById('channels');
    const errorMessage = document.getElementById('error-message');

    async function fetchChannels() {
        // ... (unverÃ¤ndert)
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
                addChannelModal.style.display = 'none'; // NEU: Modal bei Erfolg schlieÃŸen
            } catch (error) {
                errorMessage.textContent = error.message;
            }
        });
    }

    if (channelList) {
        // ... (unverÃ¤ndert)
    }
    
    
    // --- Settings Management (unverÃ¤ndert) ---
    // ...
    
    // --- Modal Logic ---
    
    // "How To" Modal (unverÃ¤ndert)
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

    // NEU: "Add Channel" Modal Logic
    const openAddBtn = document.getElementById('open-add-modal-btn');
    const closeAddBtn = document.querySelector('#add-channel-modal .close-btn');

    if (addChannelModal && openAddBtn && closeAddBtn) {
        openAddBtn.addEventListener('click', (e) => {
            e.preventDefault();
            errorMessage.textContent = ''; // Fehler zurÃ¼cksetzen
            addChannelModal.style.display = 'block';
        });
        closeAddBtn.addEventListener('click', () => {
            addChannelModal.style.display = 'none';
        });
    }

    // FÃ¼r beide Modals: AuÃŸerhalb klicken
    window.addEventListener('click', (e) => {
        if (e.target == howtoModal) {
            howtoModal.style.display = 'none';
        }
        if (e.target == addChannelModal) {
            addChannelModal.style.display = 'none';
        }
    });
});