// Admin Dashboard Configuration
// API URL - Since API and Admin are on the same domain, use the same origin
const API_URL = 'https://admin.ics.cw';

// Or use relative URL (works because API and admin are on same server)
// const API_URL = '';

// Admin configuration object
const ADMIN_CONFIG = {
    apiUrl: API_URL,
    version: '1.0.0',
    environment: 'production'
};

console.log('Admin config loaded. API URL:', API_URL);
