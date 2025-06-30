document.addEventListener('DOMContentLoaded', () => {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/login';
        return;
    }

    const headers = { 'Authorization': `Bearer ${token}` };
    const userListBody = document.getElementById('user-list-body');
    const createUserForm = document.getElementById('create-user-form');
    const changePasswordForm = document.getElementById('change-password-form');

    // --- Modal Elements ---
    const adminModal = document.getElementById('admin-change-password-modal');
    const adminModalForm = document.getElementById('admin-change-password-form-modal');
    const modalUsername = document.getElementById('modal-username');
    const modalUserId = document.getElementById('modal-user-id');
    const modalNewPassword = document.getElementById('modal-new-password');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalMessageEl = document.getElementById('modal-password-change-message');

    // --- Password Validation Function ---
    function validatePassword(password) {
        const validations = {
            length: password.length >= 8,
            case: /[a-z]/.test(password) && /[A-Z]/.test(password),
            number: /[0-9]/.test(password),
            special: /[!@#$%^&*()_+\-=\[\]{}|;':",./<>?]/.test(password)
        };
        return Object.values(validations).every(Boolean);
    }

    // --- Load Users Function ---
    async function loadUsers() {
        try {
            const response = await fetch('/api/users/', { headers });
            if (response.status === 401) {
                 window.location.href = '/login';
                 return;
            }
            if (!response.ok) {
                let errorMsg = 'Failed to fetch users';
                try { errorMsg = (await response.json()).detail || errorMsg; } catch (e) {}
                throw new Error(errorMsg);
            }
            
            const users = await response.json();
            userListBody.innerHTML = '';
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
                        <button data-action="change-password" data-id="${user.id}" data-username="${user.username}" class="text-blue-400 hover:text-blue-600">Change Password</button>
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

    // --- Create User Form ---
    createUserForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = e.target['new-username'].value;
        const password = e.target['new-password'].value;
        const isAdmin = e.target['new-is-admin'].checked;
        if (!validatePassword(password)) {
            alert('Error: New user password does not meet all requirements.');
            return;
        }
        try {
            const response = await fetch('/api/users/', {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, is_admin: isAdmin })
            });
            if (!response.ok) { throw new Error((await response.json()).detail || 'Failed to create user'); }
            createUserForm.reset();
            loadUsers();
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    });

    // --- Self Password Change Form ---
    if (changePasswordForm) {
        const newPasswordInput = document.getElementById('new-password-change');
        const messageEl = document.getElementById('password-change-message');
        const pwValidators = {
            length: document.getElementById('pw-length'),
            case: document.getElementById('pw-case'),
            number: document.getElementById('pw-number'),
            special: document.getElementById('pw-special'),
        };

        function updateValidationUI(password) {
            const validations = {
                length: password.length >= 8,
                case: /[a-z]/.test(password) && /[A-Z]/.test(password),
                number: /[0-9]/.test(password),
                special: /[!@#$%^&*()_+\-=\[\]{}|;':",./<>?]/.test(password)
            };
            pwValidators.length.style.color = validations.length ? 'lightgreen' : 'inherit';
            pwValidators.case.style.color = validations.case ? 'lightgreen' : 'inherit';
            pwValidators.number.style.color = validations.number ? 'lightgreen' : 'inherit';
            pwValidators.special.style.color = validations.special ? 'lightgreen' : 'inherit';
        }

        newPasswordInput.addEventListener('input', () => updateValidationUI(newPasswordInput.value));

        changePasswordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const currentPassword = document.getElementById('current-password').value;
            const newPassword = newPasswordInput.value;
            const confirmPassword = document.getElementById('confirm-new-password').value;
            
            messageEl.textContent = '';
            messageEl.classList.remove('text-red-400', 'text-green-400');

            if (newPassword !== confirmPassword) {
                messageEl.textContent = 'Error: New passwords do not match.';
                messageEl.classList.add('text-red-400');
                return;
            }
            if (!validatePassword(newPassword)) {
                messageEl.textContent = 'Error: New password does not meet all requirements.';
                messageEl.classList.add('text-red-400');
                return;
            }

            try {
                const response = await fetch('/api/users/me/password', {
                    method: 'PUT',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
                });
                if (!response.ok) { throw new Error((await response.json()).detail || 'Failed to change password'); }
                
                messageEl.textContent = 'Password changed successfully!';
                messageEl.classList.add('text-green-400');
                changePasswordForm.reset();
                updateValidationUI('');
            } catch (error) {
                messageEl.textContent = `Error: ${error.message}`;
                messageEl.classList.add('text-red-400');
            }
        });
    }

    // --- User List Actions (Delegated) ---
    userListBody.addEventListener('click', async (e) => {
        const targetButton = e.target.closest('button');
        if (!targetButton) return;

        const action = targetButton.dataset.action;
        const userId = targetButton.dataset.id;

        if (action === 'delete') {
            if (!window.confirm('Are you sure you want to delete this user?')) return;
            try {
                await fetch(`/api/users/${userId}`, { method: 'DELETE', headers });
                loadUsers();
            } catch { alert('Failed to delete user.'); }
        } else if (action === 'toggle-active' || action === 'toggle-admin') {
            const row = targetButton.closest('tr');
            const isActive = row.cells[1].textContent.trim() === 'Active';
            const isAdmin = row.cells[2].textContent.trim() === 'Admin';
            const updatePayload = action === 'toggle-active' ? { is_active: !isActive } : { is_admin: !isAdmin };
            try {
                await fetch(`/api/users/${userId}`, {
                    method: 'PUT',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify(updatePayload)
                });
                loadUsers();
            } catch { alert('Failed to update user.'); }
        } else if (action === 'change-password') {
            modalUsername.textContent = targetButton.dataset.username;
            modalUserId.value = userId;
            adminModal.classList.remove('hidden');
        }
    });

    // --- Admin Modal Logic ---
    modalCancelBtn.addEventListener('click', () => {
        adminModal.classList.add('hidden');
        adminModalForm.reset();
        modalMessageEl.textContent = '';
    });

    adminModalForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const userId = modalUserId.value;
        const newPassword = modalNewPassword.value;
        modalMessageEl.textContent = '';
        modalMessageEl.classList.remove('text-red-400', 'text-green-400');

        if (!validatePassword(newPassword)) {
            modalMessageEl.textContent = 'Password does not meet requirements.';
            modalMessageEl.classList.add('text-red-400');
            return;
        }

        try {
            const response = await fetch(`/api/users/${userId}/password`, {
                method: 'PUT',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_password: newPassword })
            });
            if (!response.ok) { throw new Error((await response.json()).detail || 'Failed to change password'); }
            
            modalMessageEl.textContent = 'Password changed successfully!';
            modalMessageEl.classList.add('text-green-400');
            adminModalForm.reset();
            setTimeout(() => {
                adminModal.classList.add('hidden');
                modalMessageEl.textContent = '';
            }, 2000);

        } catch (error) {
            modalMessageEl.textContent = `Error: ${error.message}`;
            modalMessageEl.classList.add('text-red-400');
        }
    });

    // Initial load
    loadUsers();
});
