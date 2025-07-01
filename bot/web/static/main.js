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

    // --- INITIAL DATA FETCHES ---
    // Fetch user admin status
    fetch('/api/users/me', { headers }).then(res => res.json()).then(user => {
        if (user && user.is_admin) adminLink.classList.remove('hidden');
    });

    // Fetch all possible roles for the edit dropdown
    fetch('/api/squads/roles', { headers }).then(res => res.json()).then(data => { ALL_ROLES = data; });

    // Fetch events for the main dropdown
    fetch('/api/events', { headers }).then(res => res.json()).then(events => {
        eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
        events.forEach(event => {
            const option = document.createElement('option');
            option.value = event.event_id;
            option.textContent = `${event.title} (${new Date(event.event_time).toLocaleString()})`;
            eventDropdown.appendChild(option);
        });
    });

    // --- CORE LOGIC ---

    // Main handler when an event is selected
    eventDropdown.addEventListener('change', async () => {
        workshopSection.classList.add('hidden');
        const eventId = eventDropdown.value;
        if (!eventId) {
            rosterAndBuildSection.classList.add('hidden');
            return;
        }

        // Check for existing squads first to persist the layout
        const squadsResponse = await fetch(`/api/events/${eventId}/squads`, { headers });
        const existingSquads = await squadsResponse.json();

        if (existingSquads && existingSquads.length > 0) {
            handleSquadData(existingSquads);
        } else {
            // If no squads exist, show the build form
            const rosterResponse = await fetch(`/api/events/${eventId}/signups`, { headers });
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
    });

    // Build Squads button action
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
            if (!response.ok) throw new Error('Failed to build squads');
            handleSquadData(await response.json());
        } catch (error) {
            alert('Error building squads. Check console for details.');
            console.error(error);
        } finally {
            buildBtn.textContent = 'Build Squads';
            buildBtn.disabled = false;
        }
    });

    // Refresh Roster button action
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
            if (!response.ok) throw new Error('Failed to refresh roster');
            handleSquadData(await response.json());
            alert('Roster has been updated!');
        } catch (error) {
            alert('Error refreshing roster. Check console for details.');
        } finally {
            refreshRosterBtn.textContent = 'Refresh Roster';
            refreshRosterBtn.disabled = false;
        }
    });
    
    // --- HELPER FUNCTIONS ---

    // Central function to process and display squad data
    function handleSquadData(squads) {
        currentSquads = squads;
        displayWorkshopAndReserves(squads);
        loadChannels();
        rosterAndBuildSection.classList.add('hidden');
        workshopSection.classList.remove('hidden');
    }

    // Renders the workshop and initializes drag-and-drop
    function displayWorkshopAndReserves(squads) {
        workshopArea.innerHTML = '';
        reservesArea.innerHTML = '';

        (squads || []).forEach(squad => {
            const isReserves = squad.squad_type === 'Reserves';
            const targetContainer = isReserves ? reservesArea : workshopArea;

            const squadDiv = document.createElement('div');
            squadDiv.className = isReserves ? '' : 'bg-gray-700 p-4 rounded-lg';
            if (!isReserves) {
                 squadDiv.innerHTML = `<h3 class="font-bold text-white border-b border-gray-600 pb-2 mb-2">${squad.name}</h3>`;
            }

            const memberList = document.createElement('div');
            memberList.className = 'member-list space-y-1 min-h-[40px]';
            memberList.setAttribute('data-squad-id', squad.squad_id);

            squad.members.forEach(member => {
                const memberEl = document.createElement('div');
                memberEl.className = 'p-2 bg-gray-800 rounded-md flex justify-between items-center member-item cursor-grab';
                memberEl.setAttribute('data-member-id', member.squad_member_id);
                memberEl.innerHTML = `
                    <span class="member-info">
                        <strong class="member-role">${member.assigned_role_name}:</strong>
                        <span class="member-name">${member.display_name}</span>
                    </span>
                    <span class="edit-member-btn cursor-pointer text-xs text-gray-400 hover:text-white px-2">EDIT</span>
                `;
                memberList.appendChild(memberEl);
            });
            
            squadDiv.appendChild(memberList);
            targetContainer.appendChild(squadDiv);
        });

        // Initialize SortableJS on all member lists
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
                        if(!response.ok) throw new Error('Move failed on server');
                    } catch (err) {
                        alert("Error: Could not move member.");
                        // For a robust UI, you would move the item back to evt.from here
                    }
                }
            });
        });
    }

    // --- MODAL AND FORM LOGIC ---

    // Use event delegation for edit buttons
    document.body.addEventListener('click', (e) => {
        if (e.target.classList.contains('edit-member-btn')) {
            const memberItem = e.target.closest('.member-item');
            const memberId = memberItem.dataset.memberId;
            const memberName = memberItem.querySelector('.member-name').textContent;
            
            modalMemberName.textContent = memberName;
            modalMemberIdInput.value = memberId;

            modalRoleSelect.innerHTML = '';
            const allRoles = [...new Set([...ALL_ROLES.roles, ...Object.values(ALL_ROLES.subclasses).flat()])].sort();
            allRoles.forEach(role => {
                const option = document.createElement('option');
                option.value = role;
                option.textContent = role;
                modalRoleSelect.appendChild(option);
            });
            
            editModal.classList.remove('hidden');
        }
    });

    modalCancelBtn.addEventListener('click', () => editModal.classList.add('hidden'));

    editMemberForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const memberId = modalMemberIdInput.value;
        const newRole = modalRoleSelect.value;
        try {
            const response = await fetch(`/api/squads/members/${memberId}/role`, {
                method: 'PUT',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_role_name: newRole })
            });
            if (!response.ok) throw new Error('Failed to update role');
            const memberEl = document.querySelector(`[data-member-id='${memberId}'] .member-role`);
            if(memberEl) memberEl.textContent = newRole + ':';
            editModal.classList.add('hidden');
        } catch (err) {
            alert("Error: Could not update role.");
        }
    });
    
    function populateBuildForm() {
        // This function can be expanded with the new squad types
        const formFields = [
            { label: 'Infantry Squad Size', id: 'infantry_squad_size', value: 6 },
            { label: 'Attack Squads', id: 'attack_squads', value: 2 },
            { label: 'Defence Squads', id: 'defence_squads', value: 2 },
            { label: 'Flex Squads', id: 'flex_squads', value: 1 },
            { label: 'Pathfinder Squads', id: 'pathfinder_squads', value: 0 },
            { label: 'Armour Squads', id: 'armour_squads', value: 1 },
            { label: 'Recon Squads', id: 'recon_squads', value: 1 },
            { label: 'Arty Squads', id: 'arty_squads', value: 0 },
        ];
        buildForm.innerHTML = formFields.map(field => `
            <div>
                <label for="${field.id}" class="block text-sm font-medium">${field.label}</label>
                <input type="number" id="${field.id}" name="${field.id}" value="${field.value}" min="0" required class="mt-1 w-full bg-gray-700 border-gray-600 rounded-md p-2">
            </div>
        `).join('');
    }

    async function loadChannels() {
        // This function remains the same
    }
});
