document.addEventListener('DOMContentLoaded', () => {
    // State and Headers
    const token = getAuthToken();
    if (!token) { window.location.href = '/login'; return; }
    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [], ALL_ROLES = {}, EMOJI_MAP = {};

    // Element Selectors
    const eventDropdown = document.getElementById('event-dropdown'),
          rosterAndBuildSection = document.getElementById('roster-and-build'),
          rosterList = document.getElementById('roster-list'),
          buildForm = document.getElementById('build-form'),
          buildBtn = document.getElementById('build-btn'),
          workshopSection = document.getElementById('workshop-section'),
          workshopArea = document.getElementById('workshop-area'),
          reservesArea = document.getElementById('reserves-list'),
          refreshRosterBtn = document.getElementById('refresh-roster-btn'),
          editModal = document.getElementById('edit-member-modal'),
          editMemberForm = document.getElementById('edit-member-form');

    // API Error Handler
    const handleApiError = (response) => {
        if (response.status === 401) {
            localStorage.removeItem('accessToken');
            window.location.href = '/login';
            return true;
        }
        if (!response.ok) {
            alert('An API error occurred. Please check the console.');
            console.error('API request failed:', response);
            return true;
        }
        return false;
    };

    // Initial Data Fetch
    Promise.all([
        fetch('/api/users/me', { headers }),
        fetch('/api/squads/roles', { headers }),
        fetch('/api/events', { headers }),
        fetch('/api/squads/emojis', { headers })
    ]).then(async ([userRes, rolesRes, eventsRes, emojiRes]) => {
        if ([userRes, rolesRes, eventsRes, emojiRes].some(handleApiError)) return;
        
        const user = await userRes.json();
        if (user?.is_admin) document.getElementById('admin-link').classList.remove('hidden');

        ALL_ROLES = await rolesRes.json();
        EMOJI_MAP = await emojiRes.json();
        const events = await eventsRes.json();

        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            eventDropdown.add(new Option(`${event.title} (${new Date(event.event_time).toLocaleString()})`, event.event_id));
        });
    }).catch(err => console.error("Failed to load initial page data:", err));

    // Event Listeners
    eventDropdown.addEventListener('change', async () => {
        workshopSection.classList.add('hidden');
        const eventId = eventDropdown.value;
        if (!eventId) { rosterAndBuildSection.classList.add('hidden'); return; }
        
        try {
            const rosterRes = await fetch(`/api/events/${eventId}/signups`, { headers });
            if (handleApiError(rosterRes)) return;
            displayRoster(await rosterRes.json());
            
            populateBuildForm();
            rosterAndBuildSection.classList.remove('hidden');

            const squadsRes = await fetch(`/api/events/${eventId}/squads`, { headers });
            if (handleApiError(squadsRes)) return;
            const existingSquads = await squadsRes.json();

            if (existingSquads?.length > 0) {
                buildBtn.textContent = 'Re-Build Squads';
                renderWorkshop(existingSquads);
            } else {
                buildBtn.textContent = 'Build Squads';
            }
        } catch (err) { console.error("Error loading event data:", err); }
    });

    buildBtn.addEventListener('click', async () => {
        // ... buildBtn logic remains the same ...
    });
    
    refreshRosterBtn.addEventListener('click', async () => {
        // ... refreshRosterBtn logic remains the same ...
    });

    // Modal Logic
    document.body.addEventListener('click', (e) => {
        if (e.target.classList.contains('edit-member-btn')) {
            // ... edit button click logic to populate and show modal ...
        }
    });

    editMemberForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const memberId = document.getElementById('modal-member-id').value;
        const newRole = document.getElementById('modal-role-select').value;
        const eventId = eventDropdown.value;
        
        try {
            const response = await fetch(`/api/squads/members/${memberId}/role`, {
                method: 'PUT',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_role_name: newRole, event_id: parseInt(eventId) })
            });
            if (handleApiError(response)) throw new Error('Failed to update role');

            const memberEl = document.querySelector(`[data-member-id='${memberId}']`);
            if (memberEl) {
                memberEl.querySelector('.member-emoji').textContent = EMOJI_MAP[newRole] || '❔';
            }
            editModal.classList.add('hidden');
        } catch (err) { alert("Error: Could not update role."); console.error(err); }
    });

    // Helper Functions
    function displayRoster(roster) {
        rosterList.innerHTML = '';
        roster.forEach(player => {
            const div = document.createElement('div');
            div.className = 'p-2 bg-gray-700 rounded-md text-sm';
            div.textContent = `${player.display_name} (${player.role_name} / ${player.subclass_name || 'N/A'})`;
            rosterList.appendChild(div);
        });
    }

    function renderWorkshop(squads) {
        currentSquads = squads;
        workshopArea.innerHTML = '';
        reservesArea.innerHTML = '';

        squads.forEach(squad => {
            const targetContainer = squad.squad_type === 'Reserves' ? reservesArea : workshopArea;
            const squadDiv = document.createElement('div');
            const memberList = document.createElement('div');
            memberList.className = 'member-list space-y-1 min-h-[40px] p-2 rounded-lg';
            memberList.dataset.squadId = squad.squad_id;

            if (squad.squad_type !== 'Reserves') {
                squadDiv.className = 'bg-gray-700 p-4 rounded-lg';
                squadDiv.innerHTML = `<h3 class="font-bold text-white border-b border-gray-600 pb-2 mb-2">${squad.name}</h3>`;
            }

            squad.members?.forEach(member => {
                const memberEl = document.createElement('div');
                memberEl.className = 'p-2 bg-gray-800 rounded-md flex justify-between items-center member-item cursor-grab';
                memberEl.dataset.memberId = member.squad_member_id;
                const emoji = EMOJI_MAP[member.assigned_role_name] || '❔';
                memberEl.innerHTML = `
                    <span class="member-info flex items-center">
                        <span class="member-emoji text-xl mr-2">${emoji}</span>
                        <span class="member-name">${member.display_name}</span>
                    </span>
                    <span class="edit-member-btn cursor-pointer text-xs text-gray-400 hover:text-white px-2">EDIT</span>`;
                memberList.appendChild(memberEl);
            });

            squadDiv.appendChild(memberList);
            targetContainer.appendChild(squadDiv);
        });

        document.querySelectorAll('.member-list').forEach(list => {
            new Sortable(list, { group: 'squads', animation: 150, onEnd: async (evt) => { /* ... */ }});
        });

        workshopSection.classList.remove('hidden');
        loadChannels();
    }
    
    // ... other helper functions like populateBuildForm, loadChannels, etc.
});
