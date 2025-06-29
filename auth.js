document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const logoutBtn = document.getElementById('logout-btn');

    // Handle Login
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = e.target.username.value;
            const password = e.target.password.value;
            const errorMessage = document.getElementById('error-message');

            try {
                const response = await fetch('/token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({ username, password })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Login failed');
                }

                const data = await response.json();
                localStorage.setItem('accessToken', data.access_token);
                window.location.href = '/'; // Redirect to main page

            } catch (error) {
                errorMessage.textContent = error.message;
            }
        });
    }

    // Handle Logout
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('accessToken');
            window.location.href = '/login';
        });
    }
});

// Helper function to get the token
function getAuthToken() {
    return localStorage.getItem('accessToken');
}
