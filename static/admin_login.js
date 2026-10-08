const loginForm = document.getElementById('adminLoginForm');
const loginMessage = document.getElementById('loginMessage');
const submitButton = document.getElementById('submitButton');
const passwordInput = document.getElementById('password');
const passwordToggle = document.getElementById('passwordToggle');

passwordToggle.addEventListener('click', () => {
    const showPassword = passwordInput.type === 'password';
    passwordInput.type = showPassword ? 'text' : 'password';
    passwordToggle.textContent = showPassword ? 'Hide' : 'Show';
    passwordToggle.setAttribute('aria-pressed', String(showPassword));
});

loginForm.addEventListener('submit', async event => {
    event.preventDefault();
    loginMessage.textContent = '';

    if (!loginForm.reportValidity()) return;

    submitButton.disabled = true;
    submitButton.querySelector('span:first-child').textContent = 'Verifying...';

    try {
        const response = await fetch('/api/auth/admin-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            cache: 'no-store',
            body: JSON.stringify({
                email: document.getElementById('email').value.trim(),
                password: passwordInput.value
            })
        });
        const data = await response.json();

        if (!response.ok) {
            loginMessage.textContent = data.error || 'Unable to sign in. Check your credentials and try again.';
            return;
        }

        sessionStorage.setItem('eco_admin_token', data.token);
        window.location.assign('/');
    } catch (error) {
        loginMessage.textContent = 'Sign-in service is unavailable. Please try again.';
    } finally {
        submitButton.disabled = false;
        submitButton.querySelector('span:first-child').textContent = 'Sign in securely';
    }
});