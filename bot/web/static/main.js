document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }

    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [];

    const eventDropdown = document.getElementById('event-dropdown');
    const rosterAndBuildSection = document.getElementById('roster-and-build');
    const rosterList = document.getElementById('roster-list');
    const buildForm = document.getElementById('build-form');
    const buildBtn = document.getElementById('build-btn');
    const workshopSection = document.getElementById('workshop-section');
    const workshopArea = document.getElementById('workshop-area');
    const channelDropdown = document.getElementById('channel-dropdown');
    const sendBtn = document.getElementById('send-btn');
    const adminLink = document.getElementById('admin-link');

    // Check user role to show admin link
    fetch('/api/users/me', { headers })
        .then(response => response.json())
        .then(user => {
            if (user.is_admin) {
                adminLink.classList.remove('hidden');
            }
        });

    // Load events
    fetch('/api/events', { headers })
        .then(response => response.json())
        .then(events => {
            eventDropdown.innerHTML = '<option value="">-- Select an Event --</option>';
            events.forEach(event => {
                const option = document.createElement('option');
                option.value = event.event_id;
                option.textContent = `${event.title} (${new Date(event.event_time).toLocaleString()})`;
                eventDropdown.appendChild(option);
            });
        });

    // Event selection change
    eventDropdown.addEventListener('change', async () => {
        const eventId = eventDropdown.value;
        if (!eventId) {
            rosterAndBuildSection.classList.add('hidden');
            workshopSection.classList.add('hidden');
            return;
        }
        
        const response = await fetch(`/api/events/${eventId}/signups`, { headers });
        const roster = await response.json();
        rosterList.innerHTML = '';
        roster.forEach(player => {
            const div = document.createElement('div');
            div.className = 'p-2 bg-gray-700 rounded-md text-sm';
            div.textContent = `${player.display_name} (${player.role_name} / ${player.subclass_name})`;
            rosterList.appendChild(div);
        });

        const formFields = [
            { label: 'Infantry Squad Size', id: 'infantry_squad_size', value: 6 },
            { label: 'Attack Squads', id: 'attack_squads', value: 2 },
            { label: 'Defence Squads', id: 'defence_squads', value: 2 },
            { label: 'Flex Squads', id: 'flex_squads', value: 1 },
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

        rosterAndBuildSection.classList.remove('hidden');
    });

    // Build squads button
    buildBtn.addEventListener('click', async () => {
        const eventId = eventDropdown.value;
        const formData = new FormData(buildForm);
        const buildRequest = {};
        for (const [key, value] of formData.entries()) {
            buildRequest[key] = parseInt(value, 10);
        }

        buildBtn.textContent = 'Building...';
        buildBtn.disabled = true;

        try {
            const response = await fetch(`/api/events/${eventId}/build-squads`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify(buildRequest)
            });
            if (!response.ok) throw new Error('Failed to build squads');
            
            currentSquads = await response.json();
            displayWorkshop(currentSquads);
            loadChannels();
            workshopSection.classList.remove('hidden');

        } catch (error) {
            alert('Error building squads. Check console for details.');
            console.error(error);
        } finally {
            buildBtn.textContent = 'Build Squads';
            buildBtn.disabled = false;
        }
    });

    // Send to Discord button
    sendBtn.addEventListener('click', async () => {
        const channelId = channelDropdown.value;
        if (!channelId || currentSquads.length === 0) {
            alert('Please select a channel and build squads first.');
            return;
        }

        sendBtn.textContent = 'Sending...';
        sendBtn.disabled = true;

        try {
            // --- FIX: Changed URL from '/api/send-embed' to '/api/events/send-embed' ---
            await fetch('/api/events/send-embed', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: parseInt(channelId), squads: currentSquads })
            });
            alert('Squad embed sent successfully!');
        } catch (error) {
            alert('Failed to send embed. Check console for details.');
            console.error(error);
        } finally {
            sendBtn.textContent = 'Send to Discord Channel';
            sendBtn.disabled = false;
        }
    });

    function displayWorkshop(squads) {
        workshopArea.innerHTML = '';
        squads.forEach(squad => {
            const squadDiv = document.createElement('div');
            squadDiv.className = 'bg-gray-700 p-4 rounded-lg';
            const membersHtml = squad.members.map(m => `<p class="text-sm">${m.assigned_role_name}: ${m.display_name}</p>`).join('');
            squadDiv.innerHTML = `
                <h3 class="font-bold text-white border-b border-gray-600 pb-2 mb-2">${squad.name}</h3>
                <div class="space-y-1">${membersHtml || '<p class="text-sm italic">Empty</p>'}</div>
            `;
            workshopArea.appendChild(squadDiv);
        });
    }

    async function loadChannels() {
        const response = await fetch('/api/events/channels', { headers });
        const channels = await response.json();
        channelDropdown.innerHTML = '<option value="">-- Select a Channel --</option>';
        channels.forEach(channel => {
            const option = document.createElement('option');
            option.value = channel.id;
            option.textContent = channel.name;
            channelDropdown.appendChild(option);
        });
    }
});
