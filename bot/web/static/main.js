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

    // --- FIX: Add a robust error handler for failed API calls ---
    const handleApiError = (response) => {
        if (response.status === 401) {
            // If unauthorized, the token is bad. Clear it and force a re-login.
            localStorage.removeItem('accessToken');
            window.location.href = '/login';
            return true;
        }
        if (!response.ok) {
            // For other errors, log them and stop.
            console.error('API request failed:', response);
            return true;
        }
        return false;
    };

    // --- INITIAL DATA FETCHES ---
    // Fetch all necessary data, using the error handler
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

    }).catch(error => {
        console.error("Failed to load initial page data:", error);
        // Handle network errors or other issues by redirecting to login
        localStorage.removeItem('accessToken');
        window.location.href = '/login';
    });
    
    // --- All other event listeners and functions from the previous version should be kept below ---
    // (eventDropdown, buildBtn, refreshRosterBtn, sendBtn, modal listeners, etc.)
});
