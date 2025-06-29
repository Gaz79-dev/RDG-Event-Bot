document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }

    const headers = { 'Authorization': `Bearer ${token}` };
    const userListBody = document.getElementById('user-list-body');
    const createUserForm = document.getElementById('create-user-form');

    // Fetch and display all users
    async function loadUsers() {
        try {
            const response = await fetch('/api/users/', { headers });
            if (response.status === 401) {
                 window.location.href = '/login';
                 return;
            }
            if (!response.ok) throw new Error('Failed to fetch users');
            
            const users = await response.json();
            userListBody.innerHTML = ''; // Clear existing list
            users.forEach(user => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-700';
                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap">${user.username}</td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${user.is_active ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}">
                            ${user.is_active ? 'Active' : 'Disabled'}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">${user.is_admin ? 'Admin' : 'User'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                        <button data-action="toggle-active" data-id="${user.id}" class="text-yellow-400 hover:text-yellow-600">${user.is_active ? 'Disable' : 'Enable'}</button>
                        <button data-action="toggle-admin" data-id="${user.id}" class="text-indigo-400 hover:text-indigo-600">${user.is_admin ? 'Revoke Admin' : 'Make Admin'}</button>
                        <button data-action="delete" data-id="${user.id}" class="text-red-500 hover:text-red-700">Delete</button>
                    </td>
                `;
                userListBody.appendChild(tr);
            });
        } catch (error) {
            console.error('Error loading users:', error);
            alert('Could not load user data.');
        }
    }

    // Handle create user form submission
    createUserForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = e.target['new-username'].value;
        const password = e.target['new-password'].value;
        const isAdmin = e.target['new-is-admin'].checked;

        try {
            const response = await fetch('/api/users/', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, is_admin: isAdmin })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to create user');
            }
            
            createUserForm.reset();
            loadUsers(); // Refresh the list
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    // Handle actions on the user list (delete, toggle status)
    userListBody.addEventListener('click', async (e) => {
        if (e.target.tagName !== 'BUTTON') return;

        const action = e.target.dataset.action;
        const userId = e.target.dataset.id;

        if (action === 'delete') {
            if (!confirm('Are you sure you want to delete this user? This cannot be undone.')) return;
            try {
                await fetch(`/api/users/${userId}`, { method: 'DELETE', headers });
                loadUsers();
            } catch {
                alert('Failed to delete user.');
            }
        }

        if (action === 'toggle-active' || action === 'toggle-admin') {
            const row = e.target.closest('tr');
            const isActive = row.cells[1].textContent.trim() === 'Active';
            const isAdmin = row.cells[2].textContent.trim() === 'Admin';
            
            let updatePayload = {};
            if (action === 'toggle-active') {
                updatePayload.is_active = !isActive;
            }
            if (action === 'toggle-admin') {
                updatePayload.is_admin = !isAdmin;
            }

            try {
                await fetch(`/api/users/${userId}`, {
                    method: 'PUT',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify(updatePayload)
                });
                loadUsers();
            } catch {
                alert('Failed to update user.');
            }
        }
    });

    // Initial load
    loadUsers();
});
