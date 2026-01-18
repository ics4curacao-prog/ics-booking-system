/**
 * Admin Utilities Configuration
 * This file must be loaded BEFORE any admin page scripts
 */

// Configuration
const ADMIN_CONFIG = {
    API_URL: 'http://127.0.0.1:5000',           // Used by admin pages
    API_BASE_URL: 'http://127.0.0.1:5000',      // Alias for compatibility
    ADMIN_URL: 'http://127.0.0.1:5001',
    TOKEN_KEY: 'auth_token',
    USER_KEY: 'user_data'
};

// Utility Functions
const AdminUtils = {
    // Get auth token
    getToken() {
        return localStorage.getItem(ADMIN_CONFIG.TOKEN_KEY);
    },
    
    // Get user data
    getUser() {
        const userData = localStorage.getItem(ADMIN_CONFIG.USER_KEY);
        return userData ? JSON.parse(userData) : null;
    },
    
    // Check if logged in
    isLoggedIn() {
        return this.getToken() !== null;
    },
    
    // Check if admin
    isAdmin() {
        const user = this.getUser();
        return user && user.role === 'admin';
    },
    
    // Redirect to login if not authenticated
    requireAuth() {
        if (!this.isLoggedIn() || !this.isAdmin()) {
            window.location.href = '/admin_login.html';
            return false;
        }
        return true;
    },
    
    // Logout
    logout() {
        localStorage.removeItem(ADMIN_CONFIG.TOKEN_KEY);
        localStorage.removeItem(ADMIN_CONFIG.USER_KEY);
        window.location.href = '/admin_login.html';
    },
    
    // API call helper
    async apiCall(endpoint, method = 'GET', data = null) {
        const token = this.getToken();
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        };
        
        if (data && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(data);
        }
        
        try {
            const response = await fetch(`${ADMIN_CONFIG.API_URL}${endpoint}`, options);
            const result = await response.json();
            
            if (response.status === 401) {
                // Token expired or invalid
                this.logout();
                return null;
            }
            
            return {
                success: response.ok,
                status: response.status,
                data: result
            };
        } catch (error) {
            console.error('API call failed:', error);
            return {
                success: false,
                error: error.message
            };
        }
    },
    
    // Show message
    showMessage(message, type = 'info') {
        // Remove existing messages
        const existing = document.querySelector('.admin-message');
        if (existing) {
            existing.remove();
        }
        
        // Create message element
        const messageDiv = document.createElement('div');
        messageDiv.className = `admin-message admin-message-${type}`;
        messageDiv.textContent = message;
        
        // Add to page
        document.body.appendChild(messageDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            messageDiv.classList.add('fade-out');
            setTimeout(() => messageDiv.remove(), 300);
        }, 5000);
    },
    
    // Format date
    formatDate(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    },
    
    // Format currency
    formatCurrency(amount) {
        return `${amount} XCG`;
    },
    
    // Capitalize first letter
    capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
};

// Message styles (inject into page)
const messageStyles = `
<style>
.admin-message {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 15px 25px;
    border-radius: 8px;
    font-weight: 600;
    z-index: 10000;
    animation: slideIn 0.3s ease-out;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.admin-message-success {
    background: #10b981;
    color: white;
}

.admin-message-error {
    background: #ef4444;
    color: white;
}

.admin-message-info {
    background: #3b82f6;
    color: white;
}

.admin-message-warning {
    background: #f59e0b;
    color: white;
}

.admin-message.fade-out {
    animation: slideOut 0.3s ease-out forwards;
}

@keyframes slideIn {
    from {
        transform: translateX(400px);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

@keyframes slideOut {
    from {
        transform: translateX(0);
        opacity: 1;
    }
    to {
        transform: translateX(400px);
        opacity: 0;
    }
}
</style>
`;

// Inject styles
document.head.insertAdjacentHTML('beforeend', messageStyles);

console.log('Admin utilities loaded. API URL:', ADMIN_CONFIG.API_URL);
