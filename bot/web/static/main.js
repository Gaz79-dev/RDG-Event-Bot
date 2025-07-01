// Helper function to get the token
function getAuthToken() {
    return localStorage.getItem('accessToken');
}

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE AND HEADERS ---
    const token = getAuthToken();
    if (!token) { window.location.href = '/login'; return; }
    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [];
    let ALL_ROLES = {};
    let EMOJI_MAP = {};

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
            alert('An API error occurred. Please check the browser console (F12) for details.');
            console.error('API request failed:', response);
            return true;
        }
        return false;
    };

    // --- FIX: New helper function to correctly render any type of emoji ---
    const createEmojiHtml = (emojiString) => {
        if (!emojiString) return '<span>❔</span>';
        const customEmojiRegex = /<a?:.*?:(\d+?)>/;
        const match = emojiString.match(customEmojiRegex);
        if (match) {
            const emojiId = match[1];
            const isAnimated = emojiString.startsWith('<a:');
            const url = `https://cdn.discordapp.com/emojis/${emojiId}.${isAnimated ? 'gif' : 'png'}`;
            return `<img src="${url}" alt="emoji" class="w-6 h-6 inline-block">`;
        }
        // It's a standard Unicode emoji
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

    // --- All other event listeners and functions remain the same as the last version ---
    // The only change is inside the 'renderWorkshop' function below.
    
    // --- RENDER & HELPER FUNCTIONS ---
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

                // --- FIX: Use the new helper to generate emoji HTML ---
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

        // ... (The SortableJS init and all other functions remain the same) ...
    }
});
