// ============================================================
// Admin Dashboard Configuration
// ============================================================
// This file contains configuration for the admin dashboard
// Update API_BASE_URL when deploying to production

const ADMIN_CONFIG = {
    // API URL - Update this to your production API URL
    API_BASE_URL: 'https://ics-api-72kz.onrender.com',
    API_URL: 'https://ics-api-72kz.onrender.com',  // Alias for compatibility
    
    // Company Information
    COMPANY_NAME: 'Intelligence Cleaning Services',
    COMPANY_PHONE: '+599 968 402 98',
    COMPANY_EMAIL: 'info@ics.cw',
    
    // Currency Settings
    CURRENCY: 'XCG',
    CURRENCY_SYMBOL: 'ƒ',
    
    // Tax Settings
    TAX_RATE: 0.06,
    TAX_NAME: 'OB'
};

// Also define these directly for backwards compatibility
const API_BASE_URL = ADMIN_CONFIG.API_BASE_URL;
const API_URL = ADMIN_CONFIG.API_URL;

// Log config loaded (for debugging)
console.log('Admin config loaded. API URL:', API_URL);
