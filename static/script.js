// Dieser Event-Listener stellt sicher, dass das Skript erst läuft,
// wenn die HTML-Seite komplett geladen ist.
document.addEventListener('DOMContentLoaded', () => {
    
    // --- NEUER BLOCK: Dynamische M3U-URL-Anzeige ---
    function setDynamicPlaylistUrl() {
        const playlistUrlInput = document.getElementById('playlist-url-display');
        if (playlistUrlInput) {
            // Ermittelt Host (z.B. "192.168.178.217" oder "twitch.meinedomain.de")
            const host = window.location.host; 
            // Ermittelt Protokoll (z.B. "http:")
            const protocol = window.location.protocol; 
            
            const m3uUrl = `${protocol}//${host}/playlist.m3u`;
            playlistUrlInput.value = m3uUrl;
        }
    }
    // Führe die Funktion beim Laden der Seite aus
    setDynamicPlaylistUrl();
    // --- ENDE NEUER BLOCK ---

    
    // --- BESTEHENDER CODE: Kanal-Verwaltung ---
    const form = document.getElementById('add-channel-form');
    const channelNameInput = document.getElementById('channel-name');
    const channelList = document.getElementById('channels');
    const errorMessage = document.getElementById('error-message');

    // Funktion zum Laden der Kanäle von der API
    async function fetchChannels() {
        try {
            const response = await fetch('/api/channels');
            if (!response.ok) {
                // Wenn wir nicht eingeloggt sind, leitet der Server um,
                // was einen Fehler wirft. Wir fangen das ab.
                if (response.status === 401 || response.redirected) {
                    window.location.href = '/login'; // Leite zum Login um
                    return;
                }
                throw new Error('Netzwerkfehler');
            }
            const channels = await response.json();
            
            channelList.innerHTML = ''; // Liste leeren
            
            if (channels.length === 0) {
                channelList.innerHTML = '<li>Noch keine Kanäle hinzugefügt.</li>';
            }
            
            channels.forEach(channel => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span>${channel.login_name}</span>
                    <button data-id="${channel.id}" class="delete-btn">Löschen</button>
                `;
                channelList.appendChild(li);
            });
        } catch (error) {
            // Verhindere Fehlermeldung beim Laden der Login-Seite
            if (channelList) { 
                channelList.innerHTML = '<li>Fehler beim Laden der Kanäle.</li>';
            }
        }
    }

    // Funktion zum Hinzufügen eines Kanals
    // Stelle sicher, dass das Formular existiert (es existiert nicht auf login/setup)
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const channelName = channelNameInput.value.trim();
            if (channelName === '') return;
            
            errorMessage.textContent = ''; // Alte Fehler löschen

            try {
                const response = await fetch('/api/channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: channelName })
                });
                
                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Unbekannter Fehler');
                }
                
                channelNameInput.value = ''; // Input leeren
                fetchChannels(); // Liste neu laden
                
            } catch (error) {
                errorMessage.textContent = error.message;
            }
        });
    }

    // Funktion zum Löschen eines Kanals (Event Delegation)
    // Stelle sicher, dass die Liste existiert
    if (channelList) {
        channelList.addEventListener('click', async (e) => {
            if (e.target.classList.contains('delete-btn')) {
                const channelId = e.target.dataset.id;
                
                if (!confirm('Soll dieser Kanal wirklich gelöscht werden?')) return;

                try {
                    const response = await fetch(`/api/channels/${channelId}`, {
                        method: 'DELETE'
                    });
                    
                    if (!response.ok) throw new Error('Fehler beim Löschen');
                    
                    fetchChannels(); // Liste neu laden
                    
                } catch (error) {
                    alert(error.message);
                }
            }
        });

        // Initialen Ladevorgang starten (nur auf der Hauptseite)
        fetchChannels();
    }
});