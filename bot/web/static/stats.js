document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }
    const headers = { 'Authorization': `Bearer ${token}` };
    const tableBody = document.getElementById('stats-table-body');
    const searchInput = document.getElementById('search-input');
    let allStats = [];
    let currentSort = { column: 'days_since_last_signup', order: 'desc' };

    const renderTable = (stats) => {
        tableBody.innerHTML = '';
        if (stats.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" class="text-center p-8">No player data found.</td></tr>';
            return;
        }

        stats.forEach(player => {
            const daysSince = player.days_since_last_signup;
            let daysCell = '';
            let rowClass = '';

            if (daysSince === null) {
                daysCell = '<span class="text-gray-500">Never</span>';
            } else {
                daysCell = `${daysSince} days`;
                if (daysSince > 60) rowClass = 'bg-red-900 bg-opacity-30';
                else if (daysSince > 30) rowClass = 'bg-yellow-900 bg-opacity-30';
            }

            const tr = document.createElement('tr');
            // --- FIX: Added classes and data attribute to make rows clickable ---
            tr.className = `border-b border-gray-700 hover:bg-gray-700 cursor-pointer ${rowClass}`;
            tr.dataset.userId = player.user_id;
            // --- END FIX ---
            
            tr.innerHTML = `
                <td class="px-6 py-4 whitespace-nowrap">${player.display_name}</td>
                <td class="px-6 py-4 whitespace-nowrap text-center text-green-400 font-semibold">${player.accepted_count}</td>
                <td class="px-6 py-4 whitespace-nowrap text-center text-yellow-400 font-semibold">${player.tentative_count}</td>
                <td class="px-6 py-4 whitespace-nowrap text-center text-red-400 font-semibold">${player.declined_count}</td>
                <td class="px-6 py-4 whitespace-nowrap">${daysCell}</td>
            `;
            tableBody.appendChild(tr);
        });
    };

    const sortData = (stats) => {
        const { column, order } = currentSort;
        return [...stats].sort((a, b) => {
            let valA = a[column];
            let valB = b[column];

            if (column === 'days_since_last_signup') {
                valA = valA === null ? Infinity : valA;
                valB = valB === null ? Infinity : valB;
            }
            
            if (valA < valB) return order === 'asc' ? -1 : 1;
            if (valA > valB) return order === 'asc' ? 1 : -1;
            return 0;
        });
    };

    const updateSortHeaders = () => {
        document.querySelectorAll('.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            if (th.dataset.sort === currentSort.column) {
                th.classList.add(currentSort.order === 'asc' ? 'sort-asc' : 'sort-desc');
            }
        });
    };
    
    document.querySelectorAll('.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const column = th.dataset.sort;
            if (currentSort.column === column) {
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.column = column;
                currentSort.order = 'desc';
            }
            renderTable(sortData(allStats.filter(p => p.display_name.toLowerCase().includes(searchInput.value.toLowerCase()))));
            updateSortHeaders();
        });
    });

    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const filteredStats = allStats.filter(player => player.display_name.toLowerCase().includes(searchTerm));
        renderTable(sortData(filteredStats));
    });

    // --- ADDITION: Event listener for clicking on a table row ---
    tableBody.addEventListener('click', (e) => {
        const row = e.target.closest('tr');
        if (row && row.dataset.userId) {
            window.location.href = `/stats/player/${row.dataset.userId}`;
        }
    });
    // --- END ADDITION ---

    fetch('/api/stats/engagement', { headers })
        .then(response => {
            if (!response.ok) throw new Error('Failed to fetch stats');
            return response.json();
        })
        .then(data => {
            allStats = data;
            renderTable(sortData(allStats));
            updateSortHeaders();
        })
        .catch(error => {
            console.error('Error loading stats:', error);
            tableBody.innerHTML = '<tr><td colspan="5" class="text-center p-8 text-red-400">Could not load player stats.</td></tr>';
        });
});
