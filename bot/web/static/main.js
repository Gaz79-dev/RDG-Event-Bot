document.addEventListener('DOMContentLoaded', () => {
    // State and Headers
    const token = getAuthToken();
    if (!token) { window.location.href = '/login'; return; }
    const headers = { 'Authorization': `Bearer ${token}` };
    let currentSquads = [];
    let ALL_ROLES = {};
    let EMOJI_MAP = {};

    // Element Selectors
    const eventDropdown = document.getElementById('event-dropdown');
    const rosterAndBuildSection = document.getElementById('roster-and-build');
    const rosterList = document.getElementById('roster-list');
    const buildForm = document.getElementById('build-form');
    const buildBtn = document.getElementById('build-btn');
    const workshopSection = document.getElementById('workshop-section');
    const workshopArea = document.getElementById('workshop-area');
    const reservesArea = document.getElementById('reserves-list');
    const refreshRosterBtn = document.getElementById('refresh-roster-btn');
    
    // --- Error Handler ---
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

    // --- Initial Data Fetches ---
    // ... This section remains the same as the previous correct version ...

    // --- Event Listener with Enhanced Logging ---
    eventDropdown.addEventListener('change', async () => {
        console.log("Event selection changed.");
        workshopSection.classList.add('hidden');
        const eventId = eventDropdown.value;
        if (!eventId) {
            rosterAndBuildSection.classList.add('hidden');
            return;
        }

        try {
            console.log(`Fetching signups for event ID: ${eventId}`);
            const rosterResponse = await fetch(`/api/events/${eventId}/signups`, { headers });
            if(handleApiError(rosterResponse)) return;
            
            const roster = await rosterResponse.json();
            console.log("Successfully fetched signups:", roster);

            console.log("Rendering roster list...");
            displayRoster(roster);
            
            console.log("Populating and showing build form...");
            populateBuildForm();
            rosterAndBuildSection.classList.remove('hidden');

            console.log("Checking for existing squads...");
            const squadsResponse = await fetch(`/api/events/${eventId}/squads`, { headers });
            if(handleApiError(squadsResponse)) return;
            const existingSquads = await squadsResponse.json();
            console.log("Fetched existing squads:", existingSquads);

            if (existingSquads?.length > 0) {
                console.log("Existing squads found. Rendering workshop.");
                buildBtn.textContent = 'Re-Build Squads';
                renderWorkshop(existingSquads);
            } else {
                console.log("No existing squads found. Hiding workshop.");
                buildBtn.textContent = 'Build Squads';
                workshopSection.classList.add('hidden');
            }
        } catch (error) {
            console.error("Error during event data processing:", error);
            alert("A JavaScript error occurred. Please check the console.");
        }
    });

    // --- All other functions and listeners remain the same ---
    // ... (buildBtn listener, refreshRosterBtn listener, renderWorkshop, etc.) ...
});
