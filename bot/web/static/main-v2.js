// A heavily instrumented version of main.js for diagnostics.

document.addEventListener('DOMContentLoaded', () => {
    console.log('[DEBUG] DOMContentLoaded: Script starting.');

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
    let lockInterval = null;
    let currentUser = null;
    let isPageInitialized = false;

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
    const logoutBtn = document.getElementById('logout-btn');
    const editModal = document.getElementById('edit-member-modal');
    const editMemberForm = document.getElementById('edit-member-form');
    const modalMemberName = document.getElementById('modal-member-name');
    const modalMemberIdInput = document.getElementById('modal-member-id');
    const modalRoleSelect = document.getElementById('modal-role-select');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const lockOverlay = document.getElementById('lock-overlay');
    const lockMessage = document.getElementById('lock-message');
    const mainContent = document.getElementById('main-content');
    const clearLockBtn = document.getElementById('clear-lock-btn');

    // --- UTILITY FUNCTIONS ---
    const handleApiError = (response) => {
        if (response.status === 401) {
            localStorage.removeItem('accessToken');
            window.location.href = '/login';
            return true;
        }
        if (response.status === 423) {
            console.log('[DEBUG] API returned 423 (Locked).');
            return false;
        }
        if (!response.ok) {
            alert('An API error occurred. Please check the browser console for details.');
            console.error('[DEBUG] API request failed:', response);
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

    // --- LOCKING FUNCTIONS (with logging) ---
    const setLockedState = (isLocked, message = '') => {
        console.log(`[DEBUG] setLockedState called with isLocked: ${isLocked}`);
        if (isLocked) {
            lockMessage.textContent = message;
            lockOverlay.classList.remove('hidden');
            mainContent.classList.add('pointer-events-none', 'opacity-50');
            console.log('[DEBUG] Lock overlay is now VISIBLE.');
        } else {
            lockOverlay.classList.add('hidden');
            mainContent.classList.remove('pointer-events-none', 'opacity-50');
            console.log('[DEBUG] Lock overlay is now HIDDEN.');
        }
    };

    const acquireLock = async (eventId) => {
        console.log(`[DEBUG] acquireLock: Attempting to lock event ${eventId}.`);
        if (!currentUser) {
            console.warn("[DEBUG] acquireLock called before currentUser is loaded. Aborting.");
            return false;
        }
        try {
            const response = await fetch(`/api/events/${eventId}/lock`, { method: 'POST', headers });
            if (response.status === 423) {
                const lockStatusRes = await fetch(`/api/events/${eventId}/lock-status`, { headers });
                const lockStatus = await lockStatusRes.json();
                console.log('[DEBUG] acquireLock: Lock status from server:', lockStatus);
                console.log('[DEBUG] acquireLock: Current user ID:', currentUser.id);

                if (lockStatus.is_locked && lockStatus.locked_by_user_id !== currentUser.id) {
                    console.log('[DEBUG] acquireLock: Lock is held by another user. Showing popup.');
                    setLockedState(true, `This event is currently locked for editing by: ${lockStatus.locked_by_username}. The page is in read-only mode.`);
                } else {
                    console.log('[DEBUG] acquireLock: Lock is held by me or is expired. Hiding popup.');
                    setLockedState(false);
                }
                return false;
            }
            if (handleApiError(response)) return false;
            
            console.log('[DEBUG] acquireLock: Lock successfully acquired/refreshed. Hiding popup.');
            setLockedState(false);
            if (lockInterval) clearInterval(lockInterval);
            lockInterval = setInterval(() => {
                fetch(`/api/events/${eventId}/lock`, { method: 'POST', headers });
            }, 60000);
            return true;
        } catch (error) {
            console.error("[DEBUG] Error in acquireLock:", error);
            return false;
        }
    };

    const releaseLock = async (eventId) => {
        console.log(`[DEBUG] releaseLock: Attempting to release lock for event ${eventId}.`);
        if (lockInterval) clearInterval(lockInterval);
        lockInterval = null;
        if (!eventId) return;
        try {
            await fetch(`/api/events/${eventId}/unlock`, { method: 'POST', headers, keepalive: true });
        } catch(e) { /* ignore */ }
    };

    window.addEventListener('beforeunload', () => {
        const eventId = eventDropdown.value;
        if (eventId) {
            releaseLock(eventId);
        }
    });

    // --- EVENT LISTENERS ---
    clearLockBtn.addEventListener('click', async () => {
        console.log('[DEBUG] clearLockBtn clicked.');
        const eventId = eventDropdown.value;
        if (eventId) {
            await releaseLock(eventId);
        }
        setLockedState(false);
        eventDropdown.value = '';
        rosterAndBuildSection.classList.add('hidden');
        workshopSection.classList.add('hidden');
    });

    logoutBtn.addEventListener('click', () => {
        const eventId = eventDropdown.value;
        if (eventId) releaseLock(eventId);
        localStorage.removeItem('accessToken');
        window.location.href = '/login';
    });
    
    sendBtn.addEventListener('click', async () => {
        const selectedChannelId = channelDropdown.value;
        const eventId = eventDropdown.value;
        
        if (!selectedChannelId || currentSquads.length === 0) {
            alert('Please select a channel and build squads first.');
            return;
        }
        
        // --- NEW DIAGNOSTIC LOGGING ---
        console.log("--- DEBUG: Data being sent to /api/events/send-embed ---");
        console.log("Channel ID:", selectedChannelId);
        // We use JSON.parse(JSON.stringify(...)) to log a clean, deep copy of the object
        console.log("Squads Payload:", JSON.parse(JSON.stringify(currentSquads))); 
        // --- END DIAGNOSTIC LOGGING ---

        sendBtn.textContent = 'Sending...';
        sendBtn.disabled = true;
        
        try {
            const payload = { channel_id: selectedChannelId, squads: currentSquads };
            const response = await fetch('/api/events/send-embed', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if(handleApiError(response)) throw new Error("Failed to send");
            alert('Squad embed sent successfully!');
            await releaseLock(eventId);
            setLockedState(true, 'Squads sent. This event is now read-only.');
        } catch (error) {
            alert('Failed to send embed.');
        } finally {
            sendBtn.textContent = 'Send to Discord Channel';
            sendBtn.disabled = false;
        }
    });

    // --- MAIN LOGIC ---
    console.log('[DEBUG] Starting initial data fetch with Promise.all.');
    Promise.all([
        fetch('/api/users/me', { headers }),
        fetch('/api/squads/roles', { headers }),
        fetch('/api/events', { headers }),
        fetch('/api/squads/emojis', { headers })
    ]).then(async ([userRes, rolesRes, eventsRes, emojiRes]) => {
        console.log('[DEBUG] Promise.all resolved. Processing results.');
        
        if ([userRes, rolesRes, eventsRes, emojiRes].some(handleApiError)) return;
        
        currentUser = await userRes.json();
        console.log('[DEBUG] Current user loaded:', currentUser);
        if (currentUser?.is_admin) adminLink.classList.remove('hidden');

        ALL_ROLES = await rolesRes.json();
        EMOJI_MAP = await emojiRes.json();
        const events = await eventsRes.json();
        console.log(`[DEBUG] ${events.length} events loaded.`);

        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            eventDropdown.add(new Option(`${event.title} (${new Date(event.event_time).toLocaleString()})`, event.event_id));
        });
        console.log('[DEBUG] Event dropdown populated.');

        console.log('[DEBUG] Attaching event listener to dropdown.');
        eventDropdown.addEventListener('change', handleEventSelection);

        console.log('[DEBUG] Page initialization is complete.');
        isPageInitialized = true;

    }).catch(err => console.error("[DEBUG] FATAL: Initial page data failed to load:", err));

    // --- HANDLER FUNCTION ---
    async function handleEventSelection() {
        console.log(`[DEBUG] handleEventSelection triggered. isPageInitialized: ${isPageInitialized}. Dropdown value: "${eventDropdown.value}"`);
        if (!isPageInitialized) {
            console.log('[DEBUG] handleEventSelection blocked by isPageInitialized flag.');
            return;
        }

        if (!currentUser) {
            console.warn("[DEBUG] User data not loaded yet, ignoring event change.");
            return;
        }

        const previousEventId = eventDropdown.dataset.previousEventId;
        console.log(`[DEBUG] Previous event ID was: ${previousEventId}`);
        if (previousEventId) {
            await releaseLock(previousEventId);
        }
        setLockedState(false);
        workshopSection.classList.add('hidden');
        rosterAndBuildSection.classList.add('hidden');

        const eventId = eventDropdown.value;
        eventDropdown.dataset.previousEventId = eventId;
        console.log(`[DEBUG] New event ID is: ${eventId}`);
        if (!eventId) {
            console.log('[DEBUG] No event ID selected. Stopping.');
            return;
        }
        
        await acquireLock(eventId);

        // This part only runs after a lock is acquired or deemed not an issue.
        try {
            console.log(`[DEBUG] Fetching data for event ${eventId}.`);
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
        } catch (error) { console.error(`[DEBUG] Error loading event data for ${eventId}:`, error); }
    }
    
    // The rest of the functions (displayRoster, renderWorkshop, etc.) must be present below this point.
    function displayRoster(roster) {
        rosterList.innerHTML = '';
        (roster || []).forEach(player => {
            const div = document.createElement('div');
            div.className = 'p-2 bg-gray-700 rounded-md text-sm flex items-center';
            const emojiKey = player.subclass_name || player.role_name;
            const emojiHtml = createEmojiHtml(EMOJI_MAP[emojiKey]);
            div.innerHTML = `
                <span class="flex-shrink-0 w-6 h-6 flex items-center justify-center">${emojiHtml}</span>
                <span class="ml-2">${player.display_name}</span>
            `;
            rosterList.appendChild(div);
        });
    }

    function populateBuildForm() {
        const formFields = [
            { label: 'Infantry Squad Size', id: 'infantry_squad_size', value: 6 },
            { label: 'Attack Squads', id: 'attack_squads', value: 3 },
            { label: 'Defence Squads', id: 'defence_squads', value: 3 },
            { label: 'Flex Squads', id: 'flex_squads', value: 1 },
            { label: 'Pathfinder Squads', id: 'pathfinder_squads', value: 1 },
            { label: 'Armour Squads', id: 'armour_squads', value: 2 },
            { label: 'Recon Squads', id: 'recon_squads', value: 1 },
            { label: 'Arty Squads', id: 'arty_squads', value: 1 },
        ];
        buildForm.innerHTML = formFields.map(field => `
            <div>
                <label for="${field.id}" class="block text-sm font-medium">${field.label}</label>
                <input type="number" id="${field.id}" name="${field.id}" value="${field.value}" min="0" required class="mt-1 w-full bg-gray-700 border-gray-600 rounded-md p-2">
            </div>
        `).join('');
    }

    async function loadChannels() {
        try {
            const response = await fetch('/api/events/channels', { headers });
            if (handleApiError(response)) return;
            const channels = await response.json();
            channelDropdown.innerHTML = '<option value="">-- Select a Channel --</option>';
            (channels || []).forEach(channel => {
                channelDropdown.add(new Option(channel.name, channel.id));
            });
        } catch(err) { console.error("Could not load channels", err)}
    }

    function renderWorkshop(squads) {
        currentSquads = squads;
        workshopArea.innerHTML = '';
        reservesArea.innerHTML = '';

        (squads || []).forEach(squad => {
            const isReserves = squad.squad_type === 'Reserves';
            const targetContainer = isReserves ? reservesArea : workshopArea;
            const squadDiv = document.createElement('div');
            const memberList = document.createElement('div');
            memberList.className = 'member-list space-y-1 min-h-[40px] p-2 rounded-lg';
            if (!isReserves) {
                squadDiv.className = 'bg-gray-700 p-4 rounded-lg';
                squadDiv.innerHTML = `<h3 class="font-bold text-white border-b border-gray-600 pb-2 mb-2">${squad.name}</h3>`;
            }
            memberList.dataset.squadId = squad.squad_id;

            (squad.members || []).forEach(member => {
                const memberEl = document.createElement('div');
                memberEl.className = 'p-2 bg-gray-800 rounded-md flex justify-between items-center member-item cursor-grab';
                memberEl.dataset.memberId = member.squad_member_id;
                const emojiHtml = createEmojiHtml(EMOJI_MAP[member.assigned_role_name]);
                memberEl.innerHTML = `
                    <span class="member-info flex items-center">
                        <span class="member-emoji mr-2 flex-shrink-0 w-6 h-6 flex items-center justify-center">${emojiHtml}</span>
                        <span class="member-name">${member.display_name}</span>
                        <span class="assigned-role-text hidden">${member.assigned_role_name}</span>
                    </span>
                    <span class="edit-member-btn cursor-pointer text-xs text-gray-400 hover:text-white px-2">EDIT</span>`;
                memberList.appendChild(memberEl);
            });
            squadDiv.appendChild(memberList);
            targetContainer.appendChild(squadDiv);
        });

        document.querySelectorAll('.member-list').forEach(list => {
            new Sortable(list, { group: 'squads', animation: 150, onEnd: async (evt) => {
                const memberId = evt.item.dataset.memberId;
                const newSquadId = evt.to.dataset.squadId;
                try {
                    const response = await fetch(`/api/squads/members/${memberId}/move`, {
                        method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
                        body: JSON.stringify({ new_squad_id: parseInt(newSquadId) })
                    });
                    if(handleApiError(response)) throw new Error('Move failed on server');
                } catch (err) { alert("Error: Could not move member."); }
            }});
        });
        
        workshopSection.classList.remove('hidden');
        loadChannels();
    }
});
