"""
Intelligence Cleaning Solutions - Configuration File
Customize these settings for your installation
"""

import os

class Config:
    """Main configuration class"""
    
    # ==================== SERVER CONFIGURATION ====================
    
    # API Server Settings
    API_HOST = '0.0.0.0'  # Listen on all network interfaces
    API_PORT = 5000        # API server port
    API_DEBUG = True       # Set to False in production
    
    # Admin Dashboard Settings
    ADMIN_HOST = '0.0.0.0'  # Listen on all network interfaces
    ADMIN_PORT = 5001        # Admin dashboard port
    ADMIN_DEBUG = True       # Set to False in production
    
    # ==================== DATABASE CONFIGURATION ====================
    
    # Database file path
    DATABASE_PATH = 'cleaning_service.db'
    
    # Database backup settings
    BACKUP_DIR = 'backups'
    AUTO_BACKUP = True  # Automatically backup on system start
    MAX_BACKUPS = 10    # Keep only last 10 backups
    
    # ==================== SECURITY CONFIGURATION ====================
    
    # Secret key for JWT tokens (CHANGE THIS IN PRODUCTION!)
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
    
    # JWT token expiration (in hours)
    JWT_EXPIRATION_HOURS = 24
    
    # Password requirements
    MIN_PASSWORD_LENGTH = 8
    REQUIRE_SPECIAL_CHAR = False
    REQUIRE_NUMBER = True
    REQUIRE_UPPERCASE = True
    
    # Session timeout (in minutes)
    SESSION_TIMEOUT = 60
    
    # ==================== BUSINESS CONFIGURATION ====================
    
    # Currency
    CURRENCY = 'XCG'  # Netherlands Antillean Guilder
    CURRENCY_SYMBOL = 'ƒ'
    
    # Time slots configuration
    TIME_SLOTS = {
        'morning': {
            'label': 'Morning',
            'time': '8:00 AM - 12:00 PM',
            'max_bookings': 2
        },
        'afternoon': {
            'label': 'Afternoon',
            'time': '1:00 PM - 5:00 PM',
            'max_bookings': 2
        },
        'evening': {
            'label': 'Evening',
            'time': '6:00 PM - 8:00 PM',
            'max_bookings': 1
        }
    }
    
    # Service pricing (in currency units)
    PRICING = {
        'basic_cleaning_bedroom': 20,
        'basic_cleaning_bathroom': 15,
        'deep_cleaning_bedroom': 30,
        'deep_cleaning_bathroom': 25,
        'office_cleaning_office': 35,
        'office_cleaning_bathroom': 20,
        'sofa_cleaning': 25,
        'mattress_cleaning': 30,
        'electrostatic_room': 20,
        'pool_cleaning': 50
    }
    
    # Service availability
    SERVICES_AVAILABLE = [
        'basic_cleaning',
        'deep_cleaning',
        'office_cleaning',
        'sofa_cleaning',
        'mattress_cleaning',
        'electrostatic_cleaning',
        'pool_cleaning'
    ]
    
    # ==================== CONTACT INFORMATION ====================
    
    # Company details
    COMPANY_NAME = 'Intelligence Cleaning Solutions'
    COMPANY_EMAIL = 'info@intelligentcleaning.com'
    COMPANY_PHONE = '+599 9 XXX XXXX'
    COMPANY_ADDRESS = 'Curaçao'
    
    # Support email
    SUPPORT_EMAIL = 'support@intelligentcleaning.com'
    
    # ==================== EMAIL CONFIGURATION ====================
    # (For future email notification features)
    
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_USE_TLS = True
    
    EMAIL_FROM = os.environ.get('EMAIL_FROM', 'noreply@intelligentcleaning.com')
    EMAIL_FROM_NAME = 'Intelligence Cleaning Solutions'
    
    # ==================== NOTIFICATION SETTINGS ====================
    
    # Email notifications
    NOTIFY_NEW_BOOKING = True
    NOTIFY_STATUS_CHANGE = True
    NOTIFY_CANCELLATION = True
    
    # Admin notification email
    ADMIN_EMAIL = 'admin@intelligentcleaning.com'
    
    # ==================== CORS CONFIGURATION ====================
    
    # Allowed origins for CORS (add your domains here)
    CORS_ORIGINS = [
        'http://localhost:5001',
        'http://127.0.0.1:5001',
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        # Add your production domain:
        # 'https://yourdomain.com',
    ]
    
    # ==================== LOGGING CONFIGURATION ====================
    
    # Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    LOG_LEVEL = 'INFO'
    
    # Log file settings
    LOG_FILE = 'booking_system.log'
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT = 5
    
    # ==================== RATE LIMITING ====================
    # (For future rate limiting features)
    
    RATE_LIMIT_ENABLED = False
    RATE_LIMIT_REQUESTS = 100  # Max requests per window
    RATE_LIMIT_WINDOW = 3600   # Window in seconds (1 hour)
    
    # ==================== DEVELOPMENT SETTINGS ====================
    
    # Enable/disable features
    ENABLE_REGISTRATION = True
    ENABLE_SOCIAL_LOGIN = False
    ENABLE_API_DOCS = True  # Swagger/OpenAPI documentation
    
    # Demo mode (use sample data)
    DEMO_MODE = False


class DevelopmentConfig(Config):
    """Development-specific configuration"""
    API_DEBUG = True
    ADMIN_DEBUG = True
    LOG_LEVEL = 'DEBUG'


class ProductionConfig(Config):
    """Production-specific configuration"""
    API_DEBUG = False
    ADMIN_DEBUG = False
    LOG_LEVEL = 'WARNING'
    
    # Override with environment variables
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production!")


class TestingConfig(Config):
    """Testing-specific configuration"""
    DATABASE_PATH = 'test_cleaning_service.db'
    API_DEBUG = True
    ADMIN_DEBUG = True


# Configuration selector
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

# Get configuration based on environment
environment = os.environ.get('FLASK_ENV', 'development')
active_config = config.get(environment, config['default'])
