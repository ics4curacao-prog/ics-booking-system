// ============================================================
// ICS Website Configuration
// ============================================================
// This file contains configuration settings for the customer website
// Update API_URL when deploying to production

const CONFIG = {
    // ============================================================
    // API URL Configuration
    // ============================================================
    // Uncomment the appropriate line based on your environment:
    
    // LOCAL DEVELOPMENT (uncomment for local testing):
    // API_URL: 'http://localhost:5000',
    
    // PRODUCTION - RENDER (uncomment and update with your actual URL):
    API_URL: 'https://ics-api-72kz.onrender.com',
    
    // ============================================================
    // Other Settings
    // ============================================================
    
    // Company Information
    COMPANY_NAME: 'Intelligence Cleaning Services',
    COMPANY_PHONE: '+599 968 402 98',
    COMPANY_EMAIL: 'info@ics.cw',
    COMPANY_ADDRESS: 'Vredenberg Resort Kavel 4 z/n, Willemstad Curaçao',
    
    // Currency
    CURRENCY: 'XCG',
    CURRENCY_SYMBOL: 'ƒ',
    
    // Tax Rate (OB)
    TAX_RATE: 0.06,
    TAX_NAME: 'OB',
    
    // Time Slots
    TIME_SLOTS: {
        morning: 'Morning (8AM-12PM)',
        afternoon: 'Afternoon (12PM-4PM)',
        evening: 'Evening (4PM-8PM)'
    }
};

// ============================================================
// Helper Functions
// ============================================================

// Get full API endpoint URL
function getApiUrl(endpoint) {
    const baseUrl = CONFIG.API_URL.replace(/\/$/, ''); // Remove trailing slash
    const path = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
    return baseUrl + path;
}

// Format currency
function formatCurrency(amount) {
    return `${parseFloat(amount).toFixed(2)} ${CONFIG.CURRENCY}`;
}

// Calculate tax
function calculateTax(subtotal) {
    return Math.round(subtotal * CONFIG.TAX_RATE * 100) / 100;
}

// Calculate total with tax
function calculateTotal(subtotal) {
    return subtotal + calculateTax(subtotal);
}

// Export for use in other files (if using modules)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CONFIG, getApiUrl, formatCurrency, calculateTax, calculateTotal };
}
