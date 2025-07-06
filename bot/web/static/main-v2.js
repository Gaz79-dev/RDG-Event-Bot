alert("This is the newer main-v2.js script!");
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
        if (response.status === 423) { return false; }
        if (!response.ok) {
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

    // --- LOCKING FUNCTIONS ---
    const setLockedState = (isLocked, message = '') => {
        if (isLocked) {
            lockMessage.textContent = message;
            lockOverlay.classList.remove('hidden');
            mainContent.classList.add('pointer-events-none', 'opacity-50');
        } else {
            lockOverlay.classList.add('hidden');
            mainContent.classList.remove('pointer-events-none', 'opacity-50');
        }
    };

    const acquireLock = async (eventId) => {
        if (!currentUser) return false;
        try {
            const response = await fetch(`/api/events/${eventId}/lock`, { method: 'POST', headers });
            if (response.status === 423) {
                const lockStatusRes = await fetch(`/api/events/${eventId}/lock-status`, { headers });
                const lockStatus = await lockStatusRes.json();
                if (lockStatus.is_locked && lockStatus.locked_by_user_id !== currentUser.id) {
                    setLockedState(true, `This event is currently locked for editing by: ${lockStatus.locked_by_username}. The page is in read-only mode.`);
                } else {
                    setLockedState(false);
                }
                return false;
            }
            if (handleApiError(response)) return false;
            setLockedState(false);
            if (lockInterval) clearInterval(lockInterval);
            lockInterval = setInterval(() => { fetch(`/api/events/${eventId}/lock`, { method: 'POST', headers }); }, 60000);
            return true;
        } catch (error) {
            console.error("Error in acquireLock:", error);
            return false;
        }
    };

    const releaseLock = async (eventId) => {
        if (lockInterval) clearInterval(lockInterval);
        lockInterval = null;
        if (!eventId) return;
        try {
            await fetch(`/api/events/${eventId}/unlock`, { method: 'POST', headers, keepalive: true });
        } catch (e) { /* ignore */ }
    };

    window.addEventListener('beforeunload', () => {
        if (eventDropdown.value) releaseLock(eventDropdown.value);
    });

    // --- EVENT LISTENERS ---
    buildBtn.addEventListener('click', async () => {
        const eventId = eventDropdown.value;
        if (!eventId) return;
        const formData = new FormData(buildForm);
        const buildRequest = {};
        ['infantry_squad_size', 'attack_squads', 'defence_squads', 'flex_squads', 'pathfinder_squads', 'armour_squads', 'recon_squads', 'arty_squads'].forEach(key => {
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

    clearLockBtn.addEventListener('click', async () => {
        if (eventDropdown.value) await releaseLock(eventDropdown.value);
        setLockedState(false);
        eventDropdown.value = '';
        rosterAndBuildSection.classList.add('hidden');
        workshopSection.classList.add('hidden');
    });

    logoutBtn.addEventListener('click', () => {
        if (eventDropdown.value) releaseLock(eventDropdown.value);
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
        
        sendBtn.textContent = 'Sending...';
        sendBtn.disabled = true;
        
        try {
            const url = `/api/events/send-embed?event_id=${eventId}`;

            const response = await fetch(url, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: selectedChannelId, squads: currentSquads })
            });
            
            if (!response.ok) {
                if (response.status === 422) {
                    const errorData = await response.json();
                    console.error("--- 422 VALIDATION ERROR ---");
                    console.error("The server rejected the data. Details:", JSON.stringify(errorData, null, 2));
                    alert("A data validation error occurred. See the F12 console for the exact details.");
                } else {
                     alert('An API error occurred. Please check the browser console for details.');
                }
                throw new Error(`Server responded with status: ${response.status}`);
            }
            
            alert('Squad embed sent successfully!');
            await releaseLock(eventId);
            setLockedState(true, 'Squads sent. This event is now read-only.');

        } catch (error) {
            console.error("Error in sendBtn listener:", error.message);
        } finally {
            sendBtn.textContent = 'Send to Discord Channel';
            sendBtn.disabled = false;
        }
    });

    document.body.addEventListener('click', (e) => {
        if (e.target.classList.contains('edit-member-btn')) {
            const memberItem = e.target.closest('.member-item');
            modalMemberName.textContent = memberItem.querySelector('.member-name').textContent;
            modalMemberIdInput.value = memberItem.dataset.memberId;
            const currentRole = memberItem.querySelector('.assigned-role-text').textContent;
            
            modalRoleSelect.innerHTML = '';
            const allRoles = [...new Set([...ALL_ROLES.roles, ...Object.values(ALL_ROLES.subclasses).flat()])].sort();
            allRoles.forEach(role => {
                const option = new Option(role, role);
                if (role === currentRole) option.selected = true;
                modalRoleSelect.add(option);
            });
            
            editModal.classList.remove('hidden');
        }
    });

    modalCancelBtn.addEventListener('click', () => editModal.classList.add('hidden'));

    editMemberForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const memberId = modalMemberIdInput.value;
        const newRole = modalRoleSelect.value;
        const eventId = eventDropdown.value;
        try {
            const response = await fetch(`/api/squads/members/${memberId}/role`, {
                method: 'PUT',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_role_name: newRole, event_id: parseInt(eventId) })
            });
            if (handleApiError(response)) return;
            
            const memberEl = document.querySelector(`[data-member-id='${memberId}']`);
            if (memberEl) {
                memberEl.querySelector('.member-emoji').innerHTML = createEmojiHtml(EMOJI_MAP[newRole]);
                memberEl.querySelector('.assigned-role-text').textContent = newRole;
            }
            editModal.classList.add('hidden');
        } catch (err) { alert("Error: Could not update role."); }
    });

    // --- MAIN LOGIC ---
    Promise.all([
        fetch('/api/users/me', { headers }),
        fetch('/api/squads/roles', { headers }),
        fetch('/api/events', { headers }),
        fetch('/api/squads/emojis', { headers })
    ]).then(async ([userRes, rolesRes, eventsRes, emojiRes]) => {
        if ([userRes, rolesRes, eventsRes, emojiRes].some(handleApiError)) return;
        
        currentUser = await userRes.json();
        if (currentUser?.is_admin) adminLink.classList.remove('hidden');

        ALL_ROLES = await rolesRes.json();
        EMOJI_MAP = await emojiRes.json();
        const events = await eventsRes.json();

        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            eventDropdown.add(new Option(`${event.title} (${new Date(event.event_time).toLocaleString()})`, event.event_id));
        });

        eventDropdown.addEventListener('change', handleEventSelection);
        isPageInitialized = true;

    }).catch(err => console.error("FATAL: Initial page data failed to load:", err));

    // --- HANDLER FUNCTION ---
    async function handleEventSelection() {
        if (!isPageInitialized) return;
        if (!currentUser) return;

        const previousEventId = eventDropdown.dataset.previousEventId;
        if (previousEventId) {
            await releaseLock(previousEventId);
        }
        setLockedState(false);
        workshopSection.classList.add('hidden');
        rosterAndBuildSection.classList.add('hidden');

        const eventId = eventDropdown.value;
        eventDropdown.dataset.previousEventId = eventId;
        if (!eventId) return;
        
        await acquireLock(eventId);

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
        } catch (error) { console.error(`Error loading event data for ${eventId}:`, error); }
    }
    
    // --- UI RENDER FUNCTIONS ---
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
