document.addEventListener('DOMContentLoaded', () => {
    // --- STATE AND HEADERS ---
    const token = getAuthToken();
    if (!token) { window.location.href = '/login'; return; }
    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [];
    let ALL_ROLES = {};

    // --- ELEMENT SELECTORS ---
    const eventDropdown = document.getElementById('event-dropdown');
    const rosterAndBuildSection = document.getElementById('roster-and-build');
    const rosterList = document.getElementById('roster-list');
    const buildFormContainer = document.getElementById('build-form-container');
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
            console.error('API request failed:', response);
            alert('An API error occurred. Please check the console.');
            return true;
        }
        return false;
    };

    // --- INITIAL DATA FETCHES ---
    Promise.all([
        fetch('/api/users/me', { headers }),
        fetch('/api/squads/roles', { headers }),
        fetch('/api/events', { headers })
    ]).then(async ([userResponse, rolesResponse, eventsResponse]) => {
        if (handleApiError(userResponse) || handleApiError(rolesResponse) || handleApiError(eventsResponse)) return;
        
        const user = await userResponse.json();
        if (user && user.is_admin) adminLink.classList.remove('hidden');

        ALL_ROLES = await rolesResponse.json();

        const events = await eventsResponse.json();
        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            const option = document.createElement('option');
            option.value = event.event_id;
            option.textContent = `${event.title} (${new Date(event.event_time).toLocaleString()})`;
            eventDropdown.appendChild(option);
        });
    }).catch(error => { console.error("Failed to load initial page data:", error); });

    // --- EVENT LISTENERS ---

    eventDropdown.addEventListener('change', async () => {
        workshopSection.classList.add('hidden');
        rosterAndBuildSection.classList.add('hidden');
        const eventId = eventDropdown.value;
        if (!eventId) return;

        try {
            const squadsResponse = await fetch(`/api/events/${eventId}/squads`, { headers });
            if(handleApiError(squadsResponse)) return;
            const existingSquads = await squadsResponse.json();

            if (existingSquads && existingSquads.length > 0) {
                renderWorkshop(existingSquads);
            } else {
                const rosterResponse = await fetch(`/api/events/${eventId}/signups`, { headers });
                if(handleApiError(rosterResponse)) return;
                const roster = await rosterResponse.json();
                
                rosterList.innerHTML = '';
                roster.forEach(player => {
                    const div = document.createElement('div');
                    div.className = 'p-2 bg-gray-700 rounded-md text-sm';
                    div.textContent = `${player.display_name} (${player.role_name} / ${player.subclass_name})`;
                    rosterList.appendChild(div);
                });
                
                populateBuildForm();
                buildFormContainer.style.display = 'block';
                rosterAndBuildSection.classList.remove('hidden');
            }
        } catch (error) {
            console.error("Error loading event data:", error);
        }
    });

    buildBtn.addEventListener('click', async () => {
        const eventId = eventDropdown.value;
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
            alert('Error building squads. Check console for details.');
        } finally {
            buildBtn.textContent = 'Build Squads';
            buildBtn.disabled = false;
        }
    });
    
    // --- All other event listeners for refresh, send, modals go here ---
    // ...

    // --- RENDER & HELPER FUNCTIONS ---

    function renderWorkshop(squads) {
        currentSquads = squads;
        workshopArea.innerHTML = '';
        reservesArea.innerHTML = '';

        squads.forEach(squad => {
            const isReserves = squad.squad_type === 'Reserves';
            const targetContainer = isReserves ? reservesArea : workshopArea;
            const squadDiv = document.createElement('div');
            if (!isReserves) {
                squadDiv.className = 'bg-gray-700 p-4 rounded-lg';
                squadDiv.innerHTML = `<h3 class="font-bold text-white border-b border-gray-600 pb-2 mb-2">${squad.name}</h3>`;
            }
            const memberList = document.createElement('div');
            memberList.className = 'member-list space-y-1 min-h-[40px]';
            memberList.dataset.squadId = squad.squad_id;

            squad.members.forEach(member => {
                const memberEl = document.createElement('div');
                memberEl.className = 'p-2 bg-gray-800 rounded-md flex justify-between items-center member-item cursor-grab';
                memberEl.dataset.memberId = member.squad_member_id;
                memberEl.innerHTML = `
                    <span class="member-info">
                        <strong class="member-role">${member.assigned_role_name}:</strong>
                        <span class="member-name">${member.display_name}</span>
                    </span>
                    <span class="edit-member-btn cursor-pointer text-xs text-gray-400 hover:text-white px-2">EDIT</span>`;
                memberList.appendChild(memberEl);
            });
            squadDiv.appendChild(memberList);
            targetContainer.appendChild(squadDiv);
        });

        document.querySelectorAll('.member-list').forEach(list => {
            new Sortable(list, {
                group: 'squads',
                animation: 150,
                onEnd: async (evt) => {
                    const memberId = evt.item.dataset.memberId;
                    const newSquadId = evt.to.dataset.squadId;
                    try {
                        const response = await fetch(`/api/squads/members/${memberId}/move`, {
                            method: 'PUT',
                            headers: { ...headers, 'Content-Type': 'application/json' },
                            body: JSON.stringify({ new_squad_id: parseInt(newSquadId) })
                        });
                        if(handleApiError(response)) throw new Error('Move failed on server');
                    } catch (err) { alert("Error: Could not move member."); }
                }
            });
        });
        
        rosterAndBuildSection.classList.add('hidden');
        workshopSection.classList.remove('hidden');
        loadChannels();
    }
    
    // ... all other functions and modal logic from the previous proposal ...
});
