document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }
    const headers = { 'Authorization': `Bearer ${token}` };
    const tableBody = document.getElementById('events-table-body');
    const pathParts = window.location.pathname.split('/');
    const userId = pathParts[pathParts.length - 1];

    if (!userId) {
        tableBody.innerHTML = '<tr><td colspan="2" class="text-center p-8 text-red-400">Could not identify the player.</td></tr>';
        return;
    }

    fetch(`/api/stats/player/${userId}/accepted-events`, { headers })
        .then(response => {
            if (!response.ok) throw new Error('Failed to fetch event history');
            return response.json();
        })
        .then(data => {
            tableBody.innerHTML = '';
            if (data.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="2" class="text-center p-8">This player has not accepted any events.</td></tr>';
                return;
            }
            data.forEach(event => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-700';
                const eventDate = new Date(event.event_time).toLocaleString('en-GB', {
                    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
                });
                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap">${event.title}</td>
                    <td class="px-6 py-4 whitespace-nowrap">${eventDate}</td>
                `;
                tableBody.appendChild(tr);
            });
        })
        .catch(error => {
            console.error('Error loading event history:', error);
            tableBody.innerHTML = '<tr><td colspan="2" class="text-center p-8 text-red-400">Could not load event history.</td></tr>';
        });
});
