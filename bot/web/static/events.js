document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }
    const headers = { 
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };

    // Page sections and buttons
    const recurringView = document.getElementById('recurring-events-view');
    const deletedView = document.getElementById('deleted-events-view');
    const viewRecurringBtn = document.getElementById('view-recurring-btn');
    const viewDeletedBtn = document.getElementById('view-deleted-btn');
    const recurringEventsBody = document.getElementById('recurring-events-body');
    const deletedEventsBody = document.getElementById('deleted-events-body');
    
    // Modal elements
    const modal = document.getElementById('edit-event-modal');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const editEventForm = document.getElementById('edit-event-form');
    const editEventIdInput = document.getElementById('edit-event-id');

    // --- VIEW TOGGLING ---
    viewRecurringBtn.addEventListener('click', () => {
        recurringView.classList.remove('hidden');
        deletedView.classList.add('hidden');
        viewRecurringBtn.classList.add('bg-gray-700', 'text-white');
        viewDeletedBtn.classList.remove('bg-gray-700', 'text-white');
    });

    viewDeletedBtn.addEventListener('click', () => {
        deletedView.classList.remove('hidden');
        recurringView.classList.add('hidden');
        viewDeletedBtn.classList.add('bg-gray-700', 'text-white');
        viewRecurringBtn.classList.remove('bg-gray-700', 'text-white');
    });

    // --- DATA FETCHING AND RENDERING ---

    const formatDate = (dateString) => {
        if (!dateString) return 'N/A';
        return new Date(dateString).toLocaleString('en-GB', {
            day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    };
    
    const loadRecurringEvents = async () => {
        try {
            const response = await fetch('/api/events/recurring', { headers });
            if (!response.ok) throw new Error('Failed to fetch recurring events.');
            const events = await response.json();
            
            recurringEventsBody.innerHTML = '';
            events.forEach(event => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-700';
                tr.innerHTML = `
                    <td class="px-6 py-4">${event.title}</td>
                    <td class="px-6 py-4 capitalize">${event.recurrence_rule || 'N/A'}</td>
                    <td class="px-6 py-4">${formatDate(event.last_recreated_at)}</td>
                    <td class="px-6 py-4 space-x-2">
                        <button class="edit-btn text-blue-400 hover:text-blue-600" data-id="${event.event_id}">Edit</button>
                        <button class="delete-btn text-red-500 hover:text-red-700" data-id="${event.event_id}">Delete</button>
                    </td>
                `;
                recurringEventsBody.appendChild(tr);
            });
        } catch (error) {
            recurringEventsBody.innerHTML = `<tr><td colspan="4" class="text-center p-4 text-red-400">${error.message}</td></tr>`;
        }
    };
    
    const loadDeletedEvents = async () => {
        try {
            const response = await fetch('/api/events/deleted', { headers });
            if (!response.ok) throw new Error('Failed to fetch deleted events.');
            const events = await response.json();
            
            deletedEventsBody.innerHTML = '';
            events.forEach(event => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-700';
                tr.innerHTML = `
                    <td class="px-6 py-4 font-mono">${event.event_id}</td>
                    <td class="px-6 py-4">${event.title}</td>
                    <td class="px-6 py-4">${formatDate(event.deleted_at)}</td>
                `;
                deletedEventsBody.appendChild(tr);
            });
        } catch (error) {
            deletedEventsBody.innerHTML = `<tr><td colspan="3" class="text-center p-4 text-red-400">${error.message}</td></tr>`;
        }
    };
    
    // --- MODAL AND FORM LOGIC ---
    
    // Function to convert UTC ISO string to local datetime-local input format
    const toLocalISOString = (dateString) => {
        if (!dateString) return '';
        const date = new Date(dateString);
        const tzOffset = date.getTimezoneOffset() * 60000;
        const localISOTime = (new Date(date - tzOffset)).toISOString().slice(0, 16);
        return localISOTime;
    };

    recurringEventsBody.addEventListener('click', async (e) => {
        if (e.target.classList.contains('edit-btn')) {
            const eventId = e.target.dataset.id;
            try {
                const response = await fetch(`/api/events/${eventId}`, { headers });
                if (!response.ok) throw new Error('Could not fetch event details.');
                const event = await response.json();
                
                // Populate the form
                editEventIdInput.value = event.event_id;
                document.getElementById('edit-title').value = event.title;
                document.getElementById('edit-description').value = event.description || '';
                document.getElementById('edit-event-time').value = toLocalISOString(event.event_time);
                document.getElementById('edit-end-time').value = toLocalISOString(event.end_time);
                document.getElementById('edit-timezone').value = event.timezone;
                document.getElementById('edit-recurrence-rule').value = event.recurrence_rule;
                document.getElementById('edit-recreation-hours').value = event.recreation_hours;

                modal.classList.remove('hidden');
            } catch (error) {
                alert(error.message);
            }
        }
        
        if (e.target.classList.contains('delete-btn')) {
            const eventId = e.target.dataset.id;
            alert(`To permanently delete this recurring series, please use the Discord command:\n\n/event delete event_id:${eventId}`);
        }
    });
    
    modalCancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
    });
    
    editEventForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const eventId = editEventIdInput.value;
        
        // FastAPI needs ISO 8601 format with timezone info
        const eventTime = new Date(document.getElementById('edit-event-time').value).toISOString();
        const endTime = new Date(document.getElementById('edit-end-time').value).toISOString();

        const eventData = {
            title: document.getElementById('edit-title').value,
            description: document.getElementById('edit-description').value,
            event_time: eventTime,
            end_time: endTime,
            timezone: document.getElementById('edit-timezone').value,
            is_recurring: true, // It must be recurring to be on this page
            recurrence_rule: document.getElementById('edit-recurrence-rule').value,
            recreation_hours: parseInt(document.getElementById('edit-recreation-hours').value, 10),
            // The API doesn't support changing roles via this form for now.
            mention_role_ids: [],
            restrict_to_role_ids: []
        };
        
        try {
            const response = await fetch(`/api/events/${eventId}`, {
                method: 'PUT',
                headers: headers,
                body: JSON.stringify(eventData)
            });
            if (!response.ok) {
                 const errorData = await response.json();
                 throw new Error(errorData.detail || 'Failed to save changes.');
            }
            modal.classList.add('hidden');
            await loadRecurringEvents(); // Refresh the table
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    // --- INITIALIZATION ---
    loadRecurringEvents();
    loadDeletedEvents();
});
