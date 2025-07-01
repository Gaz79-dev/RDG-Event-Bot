// Helper function to get the token, accessible globally
function getAuthToken() {
    return localStorage.getItem('accessToken');
}

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE AND HEADERS ---
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }
    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [];
    let ALL_ROLES = {};
    let EMOJI_MAP = {};

    // --- ELEMENT SELECTORS ---
    const eventDropdown = document.getElementById('event-dropdown');
    const rosterAndBuildSection = document.getElementById('roster-and-build');
    const rosterList = document.getElementById('roster-list');
    const buildForm = document.getElementById('build-form');
    const buildBtn = document.getElementById('build-btn');
    const workshopSection = document.getElementById('workshop-section');
    const workshopArea = document.getElementById('workshop-area');
    const reservesArea = document.getElementById('reserves-list');
    const channelDropdown = document.getElementById('channel-dropdown');
    const sendBtn = document.getElementById('send-btn');
    const refreshRosterBtn = document.getElementById('refresh-roster-btn');
    const adminLink = document.getElementById('admin-link');
    const editModal = document.getElementById('edit-member-modal');
    const editMemberForm = document.getElementById('edit-member-form');
    const modalMemberName = document.getElementById('modal-member-name');
    const modalMemberIdInput = document.getElementById('modal-member-id');
    const modalRoleSelect = document.getElementById('modal-role-select');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');

    // --- UTILITY FUNCTIONS ---
    const handleApiError = (response) => {
        if (response.status === 401) {
            localStorage.removeItem('accessToken');
            window.location.href = '/login';
            return true;
        }
        if (!response.ok) {
            alert('An API error occurred. Please check the browser console (F12) for details.');
            console.error('API request failed:', response);
            return true;
        }
        return false;
    };

    const createEmojiHtml = (emojiString) => {
        if (!emojiString) return '<span>❔</span>';
        const match = emojiString.match(/<a?:.*?:(\d+?)>/);
        if (match) {
            const url = `https://cdn.discordapp.com/emojis/${match[1]}.${emojiString.startsWith('<a:') ? 'gif' : 'png'}`;
            return `<img src="${url}" alt="emoji" class="w-6 h-6 inline-block">`;
        }
        return `<span class="text-xl">${emojiString}</span>`;
    };

    // --- INITIAL DATA FETCHES ---
    Promise.all([
        fetch('/api/users/me', { headers }),
        fetch('/api/squads/roles', { headers }),
        fetch('/api/events', { headers }),
        fetch('/api/squads/emojis', { headers })
    ]).then(async ([userRes, rolesRes, eventsRes, emojiRes]) => {
        if ([userRes, rolesRes, eventsRes, emojiRes].some(handleApiError)) return;
        
        const user = await userRes.json();
        if (user?.is_admin) adminLink.classList.remove('hidden');

        ALL_ROLES = await rolesRes.json();
        EMOJI_MAP = await emojiRes.json();
        const events = await eventsRes.json();

        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            eventDropdown.add(new Option(`${event.title} (${new Date(event.event_time).toLocaleString()})`, event.event_id));
        });
    }).catch(err => console.error("Failed to load initial page data:", err));

    // --- EVENT LISTENERS ---

    eventDropdown.addEventListener('change', async () => {
        workshopSection.classList.add('hidden');
        const eventId = eventDropdown.value;
        if (!eventId) { rosterAndBuildSection.classList.add('hidden'); return; }

        try {
            const rosterResponse = await fetch(`/api/events/${eventId}/signups`, { headers });
            if(handleApiError(rosterResponse)) return;
            displayRoster(await rosterResponse.json());
            
            populateBuildForm();
            rosterAndBuildSection.classList.remove('hidden');

            const squadsResponse = await fetch(`/api/events/${eventId}/squads`, { headers });
            if(handleApiError(squadsResponse)) return;
            const existingSquads = await squadsResponse.json();

            if (existingSquads?.length > 0) {
                buildBtn.textContent = 'Re-Build Squads';
                renderWorkshop(existingSquads);
            } else {
                buildBtn.textContent = 'Build Squads';
            }
        } catch (error) { console.error("Error loading event data:", error); }
    });

    buildBtn.addEventListener('click', async () => {
        const eventId = eventDropdown.value;
        const formData = new FormData(buildForm);
        const buildRequest = {};
        ['infantry_squad_size', 'commander_squads', 'attack_squads', 'defence_squads', 'flex_squads', 'pathfinder_squads', 'armour_squads', 'recon_squads', 'arty_squads'].forEach(key => {
            buildRequest[key] = parseInt(formData.get(key), 10) || 0;
        });
        buildBtn.textContent = 'Building...';
        buildBtn.disabled = true;
        try {
            const response = await fetch(`/api/events/${eventId}/build-squads`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify(buildRequest)
            });
            if (handleApiError(response)) return;
            renderWorkshop(await response.json());
        } catch (error) {
            alert('Error building squads.');
        } finally {
            buildBtn.textContent = 'Re-Build Squads';
            buildBtn.disabled = false;
        }
    });
    
    refreshRosterBtn.addEventListener('click', async () => {
        const eventId = eventDropdown.value;
        if (!eventId || currentSquads.length === 0) return;
        refreshRosterBtn.textContent = 'Refreshing...';
        refreshRosterBtn.disabled = true;
        try {
            const response = await fetch(`/api/events/${eventId}/refresh-roster`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ squads: currentSquads })
            });
            if (handleApiError(response)) return;
            renderWorkshop(await response.json());
            alert('Roster has been updated!');
        } catch (error) {
            alert('Error refreshing roster.');
        } finally {
            refreshRosterBtn.textContent = 'Refresh Roster';
            refreshRosterBtn.disabled = false;
        }
    });

    sendBtn.addEventListener('click', async () => {
        // --- FIX: Logic moved inside the listener to get the live value ---
        const selectedChannelId = document.getElementById('channel-dropdown').value;
        
        if (!selectedChannelId || currentSquads.length === 0) {
            alert('Please select a channel and build squads first.');
            return;
        }
        
        sendBtn.textContent = 'Sending...';
        sendBtn.disabled = true;
        
        try {
            const response = await fetch('/api/events/send-embed', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(selectedChannelId, 10), squads: currentSquads })
            });
            if(handleApiError(response)) throw new Error("Failed to send");
            alert('Squad embed sent successfully!');
        } catch (error) {
            alert('Failed to send embed.');
        } finally {
            sendBtn.textContent = 'Send to Discord Channel';
            sendBtn.disabled = false;
        }
    });

    // ... The rest of the file (modal listeners, render functions, etc.) remains the same
