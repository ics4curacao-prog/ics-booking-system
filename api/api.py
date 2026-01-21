from flask import Flask, request, jsonify, render_template, send_from_directory, redirect
from flask_cors import CORS
import sqlite3
import bcrypt
import jwt
import datetime
from functools import wraps
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate
import io
import os
import logging

# Load environment variables from .env file (for local development)
from dotenv import load_dotenv
load_dotenv()

# PDF generation imports
from reportlab.lib.pagesizes import letter, A4
import base64
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.units import inch

# ============================================================
# PRODUCTION CONFIGURATION
# ============================================================

# Determine environment
ENVIRONMENT = os.environ.get('FLASK_ENV', 'development')
IS_PRODUCTION = ENVIRONMENT == 'production'

# Configure logging
logging.basicConfig(
    level=logging.INFO if IS_PRODUCTION else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')

# ============================================================
# SECURITY CONFIGURATION - Use environment variables
# ============================================================
# IMPORTANT: In production, set these as environment variables in Render Dashboard
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', app.config['SECRET_KEY'])

# ============================================================
# CORS CONFIGURATION - Update with your actual domains
# ============================================================
# For production, specify your actual domains
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*')

if ALLOWED_ORIGINS == '*':
    CORS(app)
else:
    # Parse comma-separated origins from environment variable
    origins_list = [origin.strip() for origin in ALLOWED_ORIGINS.split(',')]
    CORS(app, origins=origins_list)

# ============================================================
# DATABASE CONFIGURATION
# ============================================================
# For Render: Use /data for persistent storage (requires Disk to be attached)
# For local: Use current directory
if IS_PRODUCTION:
    # Render persistent storage path - uses /data if Disk is attached
    DATABASE_DIR = os.environ.get('DATABASE_DIR', '/data')
    if not os.path.exists(DATABASE_DIR):
        # Fallback to project src if /data doesn't exist (no disk attached)
        DATABASE_DIR = '/opt/render/project/src'
        if not os.path.exists(DATABASE_DIR):
            os.makedirs(DATABASE_DIR, exist_ok=True)
    DATABASE = os.path.join(DATABASE_DIR, 'cleaning_service.db')
else:
    DATABASE = os.environ.get('DATABASE_PATH', 'cleaning_service.db')

logger.info(f"Database path: {DATABASE}")

# ============================================================
# EMAIL CONFIGURATION - Use environment variables for security
# ============================================================
# Set these in Render Dashboard under Environment Variables:
# - MAIL_USERNAME: Your Gmail address (for invoices) - ics4curacao@gmail.com
# - MAIL_PASSWORD: Your Gmail App Password (16 characters)
# - MAIL_SERVER: smtp.gmail.com (default)
# - MAIL_PORT: 587 (default)

EMAIL_CONFIG = {
    'smtp_server': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.environ.get('MAIL_PORT', 587)),
    'sender_email': os.environ.get('MAIL_USERNAME', ''),
    'sender_password': os.environ.get('MAIL_PASSWORD', ''),
    'sender_name': os.environ.get('MAIL_SENDER_NAME', 'Intelligence Cleaning Services'),
    'enabled': os.environ.get('MAIL_ENABLED', 'true').lower() == 'true'
}

# Validate email configuration
if EMAIL_CONFIG['enabled'] and (not EMAIL_CONFIG['sender_email'] or not EMAIL_CONFIG['sender_password']):
    logger.warning("Email is enabled but credentials are not configured. Set MAIL_USERNAME and MAIL_PASSWORD environment variables.")
    EMAIL_CONFIG['enabled'] = False

# ============================================================
# CONTACT FORM EMAIL CONFIGURATION - Separate account to avoid Gmail loop
# ============================================================
# Set these in Render Dashboard under Environment Variables:
# - CONTACT_MAIL_USERNAME: Separate Gmail for contact form (e.g., afadania74@gmail.com)
# - CONTACT_MAIL_PASSWORD: App Password for that Gmail account
#
# This prevents the Gmail loop problem where emails sent from ics4curacao@gmail.com
# to info@ics.cw (which forwards to ics4curacao@gmail.com) get silently dropped.

CONTACT_EMAIL_CONFIG = {
    'smtp_server': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.environ.get('MAIL_PORT', 587)),
    'sender_email': os.environ.get('CONTACT_MAIL_USERNAME', ''),
    'sender_password': os.environ.get('CONTACT_MAIL_PASSWORD', ''),
    'sender_name': 'ICS Website Contact Form',
    'enabled': True
}

# Validate contact email configuration
if not CONTACT_EMAIL_CONFIG['sender_email'] or not CONTACT_EMAIL_CONFIG['sender_password']:
    logger.warning("Contact form email not configured. Set CONTACT_MAIL_USERNAME and CONTACT_MAIL_PASSWORD environment variables.")
    CONTACT_EMAIL_CONFIG['enabled'] = False
else:
    logger.info(f"Contact form email configured with sender: {CONTACT_EMAIL_CONFIG['sender_email']}")

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    """Hash a password"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def verify_password(password, hashed):
    """Verify a password against a hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def create_token(user_id, email, role='customer'):
    """Create JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def token_required(f):
    """Decorator to require valid token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'success': False, 'message': 'Token missing'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = data
        except:
            return jsonify({'success': False, 'message': 'Token invalid'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(current_user, *args, **kwargs)
    return decorated

def run_migrations():
    """Run database migrations to add any missing columns"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if customer_email column exists in bookings table
        cursor.execute("PRAGMA table_info(bookings)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'customer_email' not in columns:
            logger.info("Adding customer_email column to bookings table...")
            cursor.execute('ALTER TABLE bookings ADD COLUMN customer_email TEXT DEFAULT ""')
            conn.commit()
            logger.info("Migration complete: customer_email column added")
        
        # Add invoice_sent column to track email status
        if 'invoice_sent' not in columns:
            logger.info("Adding invoice_sent column to bookings table...")
            cursor.execute('ALTER TABLE bookings ADD COLUMN invoice_sent INTEGER DEFAULT 0')
            conn.commit()
            logger.info("Migration complete: invoice_sent column added")
        
        # Add invoice_sent_at column to track when email was sent
        if 'invoice_sent_at' not in columns:
            logger.info("Adding invoice_sent_at column to bookings table...")
            cursor.execute('ALTER TABLE bookings ADD COLUMN invoice_sent_at TEXT DEFAULT NULL')
            conn.commit()
            logger.info("Migration complete: invoice_sent_at column added")
        
        conn.close()
    except Exception as e:
        logger.error(f"Migration error: {e}")

# NOTE: init_database() is defined and called first, then run_migrations()

def init_database():
    """Initialize database tables if they don't exist"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            address TEXT,
            password BLOB NOT NULL,
            role TEXT DEFAULT 'customer',
            newsletter INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create bookings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            customer_phone TEXT,
            customer_email TEXT DEFAULT '',
            street_address TEXT,
            neighborhood TEXT,
            service_type TEXT,
            services TEXT,
            booking_date TEXT,
            time_slot TEXT,
            total_cost REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            invoice_sent INTEGER DEFAULT 0,
            invoice_sent_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create service_pricing table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS service_pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            base_price REAL NOT NULL,
            unit TEXT DEFAULT 'per service',
            description TEXT,
            is_active INTEGER DEFAULT 1,
            category TEXT DEFAULT 'Other',
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Check if admin user exists, create if not
    cursor.execute("SELECT id FROM users WHERE role = 'admin'")
    if not cursor.fetchone():
        logger.info("Creating default admin user...")
        admin_password = hash_password('admin123')
        cursor.execute('''
            INSERT INTO users (first_name, last_name, email, phone, password, role)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('Admin', 'User', 'admin@ics.cw', '+599 968 402 98', admin_password, 'admin'))
        conn.commit()
        logger.info("Default admin user created: admin@ics.cw / admin123")
    
    # Check if services exist, seed if not
    cursor.execute("SELECT COUNT(*) as count FROM service_pricing")
    if cursor.fetchone()['count'] == 0:
        logger.info("Seeding initial services...")
        # These service names MUST match the servicePriceMapping in website.html
        services = [
            # Basic Cleaning
            ('Base price for basic residential cleaning', 85.00, 'per service', 'Base price for basic residential cleaning service', 1, 'basic', 1),
            ('Additional bedroom (basic cleaning)', 18.00, 'per bedroom', 'Additional charge per bedroom for basic cleaning', 1, 'basic', 2),
            ('Additional bathroom (basic cleaning)', 20.00, 'per bathroom', 'Additional charge per bathroom for basic cleaning', 1, 'basic', 3),
            # Deep Cleaning
            ('Base price for deep residential cleaning', 130.00, 'per service', 'Base price for deep residential cleaning service', 1, 'deep', 4),
            ('Additional bedroom (deep cleaning)', 18.00, 'per bedroom', 'Additional charge per bedroom for deep cleaning', 1, 'deep', 5),
            ('Additional bathroom (deep cleaning)', 20.00, 'per bathroom', 'Additional charge per bathroom for deep cleaning', 1, 'deep', 6),
            # Add-on Services
            ('Sofa/Couch Cleaning', 40.00, 'per service', 'Deep cleaning for sofas and couches', 1, 'add-on', 7),
            ('Mattress Cleaning', 70.00, 'per service', 'Deep cleaning and sanitization for mattresses', 1, 'add-on', 8),
            ('Electrostatic Cleaning (per room)', 30.00, 'per room', 'Electrostatic disinfection cleaning per room', 1, 'add-on', 9),
            ('Pool Cleaning', 50.00, 'per service', 'Pool cleaning service', 1, 'add-on', 10),
            # Office Cleaning
            ('Base price for office cleaning', 50.00, 'per service', 'Base price for office cleaning service', 1, 'office', 11),
            ('Additional office', 18.00, 'per room', 'Additional charge per office room', 1, 'office', 12),
            ('Additional bathroom (office)', 20.00, 'per bathroom', 'Additional charge per bathroom for office cleaning', 1, 'office', 13),
            ('Office Sofa Cleaning', 40.00, 'per service', 'Deep cleaning for office sofas and couches', 1, 'office', 14),
            ('Office Electrostatic Cleaning', 30.00, 'per room', 'Electrostatic disinfection cleaning for offices', 1, 'office', 15),
        ]
        
        for service in services:
            cursor.execute('''
                INSERT INTO service_pricing (service_name, base_price, unit, description, is_active, category, display_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', service)
        
        conn.commit()
        logger.info(f"Seeded {len(services)} services")
    
    conn.close()
    logger.info("Database initialization complete")

# Initialize database tables FIRST
init_database()

# THEN run migrations to add any missing columns
run_migrations()

# ============================================================
# PDF INVOICE GENERATION - A4 Optimized (210mm x 297mm)
# Margins: 15mm sides, 12mm top/bottom for print-friendly output
# ============================================================

def generate_invoice_pdf(booking):
    """Generate A4 PDF invoice matching HTML invoice design exactly"""
    buffer = io.BytesIO()

    # A4 with print-friendly margins: 15mm sides, 12mm top/bottom
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=42,   # ~15mm
        leftMargin=42,    # ~15mm
        topMargin=34,     # ~12mm
        bottomMargin=34   # ~12mm
    )

    # Content width: 210mm - 30mm margins = 180mm ≈ 510 points
    CONTENT_WIDTH = 510

    # Color definitions matching frontend CSS
    TEAL = colors.HexColor('#1FAFB8')
    DARK_BLUE = colors.HexColor('#2D3E50')
    MEDIUM_GRAY = colors.HexColor('#555555')
    LIGHT_GRAY = colors.HexColor('#666666')
    FOOTER_GRAY = colors.HexColor('#888888')
    TABLE_HEADER_BG = colors.HexColor('#2D3E50')
    TABLE_ALT_ROW = colors.HexColor('#f9f9f9')
    BORDER_COLOR = colors.HexColor('#eeeeee')
    NOTES_BG = colors.HexColor('#f8f9fa')

    styles = getSampleStyleSheet()

    # A4-optimized font sizes
    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading3'],
        fontSize=9,
        textColor=TEAL,
        spaceBefore=8,
        spaceAfter=6,
        fontName='Helvetica-BoldOblique'
    )

    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=8,
        textColor=MEDIUM_GRAY,
        spaceAfter=3,
        leading=11
    )

    elements = []

    # Format dates
    invoice_date = datetime.datetime.now().strftime('%B %d, %Y')
    booking_date_obj = datetime.datetime.strptime(booking['booking_date'], '%Y-%m-%d')
    service_date = booking_date_obj.strftime('%A, %B %d, %Y')
    invoice_number = f"INV-{str(booking['id']).zfill(6)}"

    # ========== HEADER: Logo left, Title right ==========
    logo_path = None
    for path in [os.path.join(app.root_path, 'ics_logo.png'), os.path.join(os.getcwd(), 'ics_logo.png')]:
        if os.path.exists(path):
            logo_path = path
            break

    if logo_path:
        header_left = Image(logo_path, width=130, height=45)
    else:
        header_left = Paragraph("<b>ICS</b>", ParagraphStyle('LogoText', fontSize=20, textColor=TEAL))

    header_right = Paragraph(f"""
        <para align="right">
        <font size="20" color="#2D3E50"><b>INVOICE</b></font><br/>
        <font size="9" color="#666666">{invoice_number}</font><br/>
        <font size="7" color="#0c5460"><b>{booking['status'].upper()}</b></font>
        </para>
    """, styles['Normal'])

    header_table = Table([[header_left, header_right]], colWidths=[CONTENT_WIDTH/2, CONTENT_WIDTH/2])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(header_table)

    # Teal header line
    elements.append(Spacer(1, 8))
    line_table = Table([['']], colWidths=[CONTENT_WIDTH])
    line_table.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 3, TEAL)]))
    elements.append(line_table)
    elements.append(Spacer(1, 12))

    # ========== TWO-COLUMN: Booking Info | Customer Details ==========
    left_content = f"""
    <font size="9" color="#1FAFB8"><b><i>■ Booking Information</i></b></font><br/>
    <font size="8" color="#555555"><b>Invoice Date:</b> {invoice_date}</font><br/>
    <font size="8" color="#555555"><b>Booking ID:</b> #{booking['id']}</font><br/>
    <font size="8" color="#555555"><b>Service Date:</b> {service_date}</font><br/>
    <font size="8" color="#555555"><b>Time Slot:</b> {format_time_slot(booking['time_slot'])}</font>
    """

    right_content = f"""
    <font size="9" color="#1FAFB8"><b><i>■ Customer Details</i></b></font><br/>
    <font size="8" color="#555555"><b>Name:</b> {booking['customer_name'] or 'N/A'}</font><br/>
    <font size="8" color="#555555"><b>Phone:</b> {booking['customer_phone'] or 'N/A'}</font><br/>
    <font size="8" color="#555555"><b>Email:</b> {booking.get('customer_email', '') or 'N/A'}</font>
    """

    two_col = Table([
        [Paragraph(left_content, ParagraphStyle('L', leading=12)), 
         Paragraph(right_content, ParagraphStyle('R', leading=12))]
    ], colWidths=[CONTENT_WIDTH/2, CONTENT_WIDTH/2])
    two_col.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('RIGHTPADDING', (0, 0), (0, 0), 10),
        ('LEFTPADDING', (1, 0), (1, 0), 10),
    ]))
    elements.append(two_col)
    elements.append(Spacer(1, 10))

    # ========== SERVICE LOCATION ==========
    elements.append(Paragraph("<b><i>■ Service Location</i></b>", section_header_style))
    full_address = ', '.join(filter(None, [booking['street_address'], booking['neighborhood']])) or 'N/A'
    elements.append(Paragraph(f"<b>Address:</b> {full_address}", normal_style))
    elements.append(Spacer(1, 10))

    # ========== SERVICES TABLE ==========
    elements.append(Paragraph("<b><i>■ Services</i></b>", section_header_style))
    elements.append(Paragraph(f"<b>Category:</b> {(booking['service_type'] or 'Cleaning').capitalize()}", normal_style))
    elements.append(Spacer(1, 6))

    services_data = parse_services(booking['services'])
    table_data = [['Service', 'Details', 'Price']]
    for service in services_data:
        price_str = f"{service['price']:.2f} XCG" if service['price'] > 0 else '-'
        table_data.append([service['name'], service['details'] or '-', price_str])

    services_table = Table(table_data, colWidths=[CONTENT_WIDTH*0.35, CONTENT_WIDTH*0.45, CONTENT_WIDTH*0.20])
    
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('PADDING', (0, 0), (-1, 0), 6),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('PADDING', (0, 1), (-1, -1), 6),
        ('TEXTCOLOR', (0, 1), (1, -1), MEDIUM_GRAY),
        ('TEXTCOLOR', (2, 1), (2, -1), TEAL),
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, BORDER_COLOR),
    ]
    for i in range(2, len(table_data), 2):
        table_style.append(('BACKGROUND', (0, i), (-1, i), TABLE_ALT_ROW))
    
    services_table.setStyle(TableStyle(table_style))
    elements.append(services_table)
    elements.append(Spacer(1, 10))

    # ========== TOTALS ==========
    subtotal = float(booking['total_cost'] or 0)
    ob = round(subtotal * 0.06, 2)
    grand_total = subtotal + ob

    totals_table = Table([
        ['Sub-Total (Services):', f'{subtotal:.2f} XCG'],
        ['OB (6%):', f'{ob:.2f} XCG'],
    ], colWidths=[CONTENT_WIDTH*0.80, CONTENT_WIDTH*0.20])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('TEXTCOLOR', (0, 0), (-1, -1), MEDIUM_GRAY),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
    ]))
    elements.append(totals_table)

    elements.append(Spacer(1, 4))
    grand_table = Table([['Total:', f'{grand_total:.2f} XCG']], colWidths=[CONTENT_WIDTH*0.80, CONTENT_WIDTH*0.20])
    grand_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (-1, -1), TEAL),
        ('LINEABOVE', (0, 0), (-1, 0), 3, DARK_BLUE),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(grand_table)

    # ========== NOTES ==========
    if booking.get('notes'):
        elements.append(Spacer(1, 12))
        notes_para = Paragraph(f"""
            <font size="9" color="#1FAFB8"><b><i>■ Notes</i></b></font><br/>
            <font size="8" color="#666666">{booking['notes']}</font>
        """, ParagraphStyle('Notes', leading=11))
        notes_table = Table([[notes_para]], colWidths=[CONTENT_WIDTH])
        notes_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), NOTES_BG),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(notes_table)

    # ========== FOOTER ==========
    elements.append(Spacer(1, 20))
    footer_line = Table([['']], colWidths=[CONTENT_WIDTH])
    footer_line.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 1, BORDER_COLOR)]))
    elements.append(footer_line)
    elements.append(Spacer(1, 10))

    footer_style = ParagraphStyle('Footer', fontSize=7, textColor=FOOTER_GRAY, alignment=1)
    footer_small = ParagraphStyle('FooterSmall', fontSize=6, textColor=FOOTER_GRAY, alignment=1)
    
    elements.append(Paragraph("<b>Intelligent Cleaning Services</b>", footer_style))
    elements.append(Paragraph("Vredenberg Resort Kavel 4 z/n, Willemstad Curaçao", footer_style))
    elements.append(Paragraph("Phone: +599 968 402 98 | Email: info@ics.cw | Web: ics.cw", footer_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("Chamber of Commerce: 173068 | MCB Account: 34.298.801", footer_small))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("Thank you for choosing ICS!", footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def format_time_slot(slot):
    """Format time slot for display - matches HTML invoice format"""
    slots = {
        'morning': 'Morning (8AM-12PM)',
        'afternoon': 'Afternoon (12PM-4PM)',
        'evening': 'Evening (4PM-8PM)'
    }
    return slots.get(slot, slot)

def parse_services(services_str):
    """Parse services string into structured data - matches HTML invoice format"""
    services = []
    try:
        # Try to parse as Python literal (dict or list)
        import ast
        services_data = ast.literal_eval(services_str) if services_str else []
        
        if isinstance(services_data, dict):
            for name, details in services_data.items():
                if isinstance(details, dict):
                    # Build details string like HTML version
                    detail_parts = []
                    if details.get('bedrooms'):
                        detail_parts.append(f"{details['bedrooms']} bedroom(s)")
                    if details.get('bathrooms'):
                        detail_parts.append(f"{details['bathrooms']} bathroom(s)")
                    if details.get('offices'):
                        detail_parts.append(f"{details['offices']} office(s)")
                    if details.get('rooms'):
                        detail_parts.append(f"{details['rooms']} room(s)")
                    if details.get('quantity'):
                        detail_parts.append(f"Qty: {details['quantity']}")
                    
                    services.append({
                        'name': name,
                        'details': ', '.join(detail_parts) if detail_parts else '',
                        'price': float(details.get('price', 0))
                    })
                else:
                    services.append({
                        'name': name,
                        'details': str(details),
                        'price': 0
                    })
        elif isinstance(services_data, list):
            for service in services_data:
                if isinstance(service, dict):
                    # Build details string like HTML version
                    detail_parts = []
                    if service.get('bedrooms'):
                        detail_parts.append(f"{service['bedrooms']} bedroom(s)")
                    if service.get('bathrooms'):
                        detail_parts.append(f"{service['bathrooms']} bathroom(s)")
                    if service.get('offices'):
                        detail_parts.append(f"{service['offices']} office(s)")
                    if service.get('rooms'):
                        detail_parts.append(f"{service['rooms']} room(s)")
                    if service.get('quantity'):
                        detail_parts.append(f"Qty: {service['quantity']}")
                    
                    services.append({
                        'name': service.get('name', 'Service'),
                        'details': ', '.join(detail_parts) if detail_parts else service.get('details', ''),
                        'price': float(service.get('price', 0))
                    })
                else:
                    services.append({
                        'name': str(service),
                        'details': '',
                        'price': 0
                    })
    except:
        # If parsing fails, just show the raw string
        services.append({
            'name': 'Services',
            'details': services_str or 'N/A',
            'price': 0
        })
    
    return services if services else [{'name': 'Service', 'details': 'N/A', 'price': 0}]

# ============================================================
# EMAIL FUNCTIONS - Aligned with frontend HTML invoice style
# ============================================================

def generate_invoice_html_for_email(booking):
    """Generate HTML invoice matching the frontend design for email body"""
    
    # Calculate values
    invoice_number = f"INV-{str(booking['id']).zfill(6)}"
    invoice_date = datetime.datetime.now().strftime('%B %d, %Y')
    booking_date_obj = datetime.datetime.strptime(booking['booking_date'], '%Y-%m-%d')
    service_date = booking_date_obj.strftime('%A, %B %d, %Y')
    full_address = ', '.join(filter(None, [booking['street_address'], booking['neighborhood']])) or 'N/A'
    
    subtotal = float(booking['total_cost'] or 0)
    ob = round(subtotal * 0.06, 2)
    grand_total = subtotal + ob
    
    # Parse services for table
    services_data = parse_services(booking['services'])
    services_rows = ''
    for i, service in enumerate(services_data):
        price_str = f"{service['price']:.2f} XCG" if service['price'] > 0 else '-'
        bg_color = '#f9f9f9' if i % 2 == 1 else '#ffffff'
        services_rows += f'''
            <tr style="background: {bg_color};">
                <td style="padding: 10px 12px; border-bottom: 1px solid #eee; color: #555; font-size: 10pt;">{service['name']}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #eee; color: #555; font-size: 10pt;">{service['details'] or '-'}</td>
                <td style="padding: 10px 12px; border-bottom: 1px solid #eee; color: #1FAFB8; font-size: 10pt; text-align: right; font-weight: 500;">{price_str}</td>
            </tr>
        '''
    
    # Notes section (conditional)
    notes_section = ''
    if booking.get('notes'):
        notes_section = f'''
            <div style="background: #f8f9fa; padding: 12px; border-radius: 6px; margin-top: 20px;">
                <h4 style="color: #1FAFB8; margin-bottom: 8px; font-size: 10pt; font-style: italic;">■ Notes</h4>
                <p style="color: #666; margin: 0; font-size: 10pt; line-height: 1.5;">{booking['notes']}</p>
            </div>
        '''
    
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            /* A4 Print Styles for Email */
            @media print {{
                @page {{
                    size: A4 portrait;
                    margin: 12mm 15mm;
                }}
                body {{
                    background: white !important;
                    padding: 0 !important;
                    margin: 0 !important;
                    font-size: 9pt !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }}
                .email-container {{
                    max-width: 180mm !important;
                    box-shadow: none !important;
                    border-radius: 0 !important;
                }}
                .email-footer {{
                    display: none !important;
                }}
            }}
        </style>
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 11pt; line-height: 1.4; color: #333; margin: 0; padding: 20px; background: #f5f5f5;">
        <div class="email-container" style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="padding: 25px 30px; border-bottom: 3px solid #1FAFB8;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="vertical-align: top;">
                            <img src="cid:logo" alt="ICS Logo" style="height: 50px; width: auto; max-width: 150px;" />
                        </td>
                        <td style="text-align: right; vertical-align: top;">
                            <h2 style="font-size: 24pt; color: #2D3E50; margin: 0; font-weight: 700;">INVOICE</h2>
                            <p style="color: #666; font-size: 11pt; margin-top: 3px; margin-bottom: 5px;">{invoice_number}</p>
                            <span style="display: inline-block; padding: 3px 12px; background: #d1ecf1; color: #0c5460; border-radius: 15px; font-weight: 600; font-size: 9pt;">{booking['status'].upper()}</span>
                        </td>
                    </tr>
                </table>
            </div>
            
            <!-- Content -->
            <div style="padding: 25px 30px;">
                
                <!-- Two Column: Booking Info | Customer Details -->
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
                    <tr>
                        <td style="vertical-align: top; width: 50%; padding-right: 15px;">
                            <h3 style="color: #1FAFB8; font-size: 11pt; margin-bottom: 10px; font-style: italic;">■ Booking Information</h3>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Invoice Date:</strong> {invoice_date}</p>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Booking ID:</strong> #{booking['id']}</p>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Service Date:</strong> {service_date}</p>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Time Slot:</strong> {format_time_slot(booking['time_slot'])}</p>
                        </td>
                        <td style="vertical-align: top; width: 50%; padding-left: 15px;">
                            <h3 style="color: #1FAFB8; font-size: 11pt; margin-bottom: 10px; font-style: italic;">■ Customer Details</h3>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Name:</strong> {booking['customer_name'] or 'N/A'}</p>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Phone:</strong> {booking['customer_phone'] or 'N/A'}</p>
                            <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Email:</strong> {booking.get('customer_email', '') or 'N/A'}</p>
                        </td>
                    </tr>
                </table>
                
                <!-- Service Location -->
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #1FAFB8; font-size: 11pt; margin-bottom: 10px; font-style: italic;">■ Service Location</h3>
                    <p style="margin: 5px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Address:</strong> {full_address}</p>
                </div>
                
                <!-- Services -->
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #1FAFB8; font-size: 11pt; margin-bottom: 10px; font-style: italic;">■ Services</h3>
                    <p style="margin: 5px 0 10px 0; color: #555; font-size: 10pt;"><strong style="color: #333;">Category:</strong> {(booking['service_type'] or 'Cleaning').capitalize()}</p>
                    
                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="background: #2D3E50; color: white; padding: 10px 12px; text-align: left; font-weight: 600; font-size: 10pt;">Service</th>
                                <th style="background: #2D3E50; color: white; padding: 10px 12px; text-align: left; font-weight: 600; font-size: 10pt;">Details</th>
                                <th style="background: #2D3E50; color: white; padding: 10px 12px; text-align: right; font-weight: 600; font-size: 10pt; width: 100px;">Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            {services_rows}
                        </tbody>
                    </table>
                </div>
                
                <!-- Totals -->
                <div style="text-align: right; margin-top: 15px; border-top: 1px solid #eee; padding-top: 10px;">
                    <div style="padding: 6px 0; font-size: 11pt; color: #555;">
                        <span style="font-weight: 500;">Sub-Total (Services):</span>
                        <span style="display: inline-block; width: 100px; text-align: right;">{subtotal:.2f} XCG</span>
                    </div>
                    <div style="padding: 6px 0; font-size: 11pt; color: #555;">
                        <span style="font-weight: 500;">OB (6%):</span>
                        <span style="display: inline-block; width: 100px; text-align: right;">{ob:.2f} XCG</span>
                    </div>
                    <div style="padding-top: 10px; margin-top: 8px; border-top: 3px solid #2D3E50; font-size: 14pt; font-weight: 700; color: #1FAFB8;">
                        <span>Total:</span>
                        <span style="display: inline-block; width: 100px; text-align: right;">{grand_total:.2f} XCG</span>
                    </div>
                </div>
                
                {notes_section}
                
            </div>
            
            <!-- Footer -->
            <div style="margin-top: 25px; padding: 20px 30px; border-top: 1px solid #eee; text-align: center; color: #888; font-size: 9pt; background: #fafafa;">
                <p style="margin: 3px 0;"><strong>Intelligent Cleaning Services</strong></p>
                <p style="margin: 3px 0;">Vredenberg Resort Kavel 4 z/n, Willemstad Curaçao</p>
                <p style="margin: 3px 0;">Phone: +599 968 402 98 | Email: info@ics.cw | Web: ics.cw</p>
                <p style="margin: 8px 0 3px 0; font-size: 8pt;">Chamber of Commerce: 173068 | MCB Account: 34.298.801</p>
                <p style="margin: 8px 0 3px 0;">Thank you for choosing ICS!</p>
            </div>
            
        </div>
        
        <!-- Email-specific footer (hidden when printing) -->
        <div class="email-footer" style="text-align: center; padding: 20px; color: #999; font-size: 11px;">
            <p>This is an automated email from Intelligence Cleaning Services.</p>
            <p>If you have any questions, please contact us.</p>
        </div>
    </body>
    </html>
    '''
    
    return html

def send_invoice_email(booking, pdf_buffer):
    """Send invoice email with PDF attachment - uses aligned HTML design"""
    if not EMAIL_CONFIG['enabled']:
        return False, "Email sending is disabled"
    
    if not booking.get('customer_email'):
        return False, "Customer email address is missing"
    
    try:
        # Create message
        msg = MIMEMultipart('related')
        msg['From'] = f"{EMAIL_CONFIG['sender_name']} <{EMAIL_CONFIG['sender_email']}>"
        msg['To'] = booking['customer_email']
        msg['Date'] = formatdate(localtime=True)
        
        invoice_number = f"INV-{str(booking['id']).zfill(6)}"
        msg['Subject'] = f"Your ICS Invoice - {invoice_number}"
        
        # Create alternative part for text and HTML
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        
        # Plain text version
        subtotal = float(booking['total_cost'] or 0)
        ob = round(subtotal * 0.06, 2)
        grand_total = subtotal + ob
        
        text_body = f"""
INTELLIGENCE CLEANING SERVICES
INVOICE: {invoice_number}

Hello {booking['customer_name'] or 'Valued Customer'},

Thank you for choosing Intelligence Cleaning Services! Please find your invoice attached.

■ BOOKING INFORMATION
Invoice Date: {datetime.datetime.now().strftime('%B %d, %Y')}
Booking ID: #{booking['id']}
Service Date: {booking['booking_date']}
Time Slot: {format_time_slot(booking['time_slot'])}

■ CUSTOMER DETAILS
Name: {booking['customer_name'] or 'N/A'}
Phone: {booking['customer_phone'] or 'N/A'}
Email: {booking.get('customer_email', '') or 'N/A'}

■ SERVICE LOCATION
Address: {booking['street_address']}, {booking['neighborhood'] or ''}

■ SERVICES
Category: {(booking['service_type'] or 'Cleaning').capitalize()}

TOTALS
Sub-Total (Services): {subtotal:.2f} XCG
OB (6%): {ob:.2f} XCG
Total: {grand_total:.2f} XCG

{f"■ NOTES: {booking['notes']}" if booking.get('notes') else ''}

---
Intelligent Cleaning Services
Vredenberg Resort Kavel 4 z/n, Willemstad Curaçao
Phone: +599 968 402 98 | Email: info@ics.cw | Web: ics.cw
Chamber of Commerce: 173068 | MCB Account: 34.298.801

Thank you for choosing ICS!

This is an automated email. If you have any questions, please contact us.
        """
        
        # HTML version - using aligned design
        html_body = generate_invoice_html_for_email(booking)
        
        # Attach text and HTML parts
        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach logo for HTML email (optional - will show placeholder if not available)
        logo_path = None
        logo_candidates = [
            os.path.join(app.root_path, 'ics_logo.png'),
            os.path.join(os.getcwd(), 'ics_logo.png'),
        ]
        for path in logo_candidates:
            if os.path.exists(path):
                logo_path = path
                break
        
        if logo_path:
            with open(logo_path, 'rb') as f:
                logo_data = f.read()
            logo_attachment = MIMEApplication(logo_data, _subtype='png')
            logo_attachment.add_header('Content-ID', '<logo>')
            logo_attachment.add_header('Content-Disposition', 'inline', filename='ics_logo.png')
            msg.attach(logo_attachment)
        
        # Attach PDF
        pdf_buffer.seek(0)
        pdf_attachment = MIMEApplication(pdf_buffer.read(), _subtype='pdf')
        filename = f"ICS_Invoice_{invoice_number}_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf"
        pdf_attachment.add_header('Content-Disposition', 'attachment', filename=filename)
        msg.attach(pdf_attachment)
        
        # Send email
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.send_message(msg)
        
        logger.info(f"Invoice email sent successfully to {booking['customer_email']}")
        return True, "Invoice sent successfully"
        
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed")
        return False, "SMTP authentication failed. Check your email credentials and app password."
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {str(e)}")
        return False, f"SMTP error: {str(e)}"
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False, f"Failed to send email: {str(e)}"

# ============================================================
# API ENDPOINTS
# ============================================================

# Health check - Used by Render to verify the app is running
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Render deployment"""
    return jsonify({
        'status': 'healthy',
        'environment': ENVIRONMENT,
        'email_enabled': EMAIL_CONFIG['enabled']
    }), 200

# Contact Form Endpoint
@app.route('/api/contact', methods=['POST'])
def contact_form():
    """Handle contact form submissions - sends email to info@ics.cw
    Uses CONTACT_EMAIL_CONFIG (separate Gmail) to avoid loop problem
    """
    try:
        data = request.json
        
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        email = data.get('email', '').strip()
        message = data.get('message', '').strip()
        
        logger.info(f"Contact form submission from: {first_name} {last_name} <{email}>")
        
        # Validate required fields
        if not first_name or not email or not message:
            return jsonify({
                'success': False,
                'message': 'Please fill in all required fields (First Name, Email, Message)'
            }), 400
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({
                'success': False,
                'message': 'Please enter a valid email address'
            }), 400
        
        # Check if contact email is configured
        if not CONTACT_EMAIL_CONFIG['enabled']:
            logger.warning("Contact form submitted but CONTACT email is not configured")
            return jsonify({
                'success': False,
                'message': 'Email service is not configured. Please contact us directly at info@ics.cw'
            }), 500
        
        # Send email to info@ics.cw using CONTACT_EMAIL_CONFIG
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"New Contact Form Message from {first_name} {last_name}"
            msg['From'] = f"{CONTACT_EMAIL_CONFIG['sender_name']} <{CONTACT_EMAIL_CONFIG['sender_email']}>"
            msg['To'] = "info@ics.cw"
            msg['Reply-To'] = email
            
            # Create email body
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #1FAFB8 0%, #188a92 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                    .field {{ margin-bottom: 15px; }}
                    .label {{ font-weight: bold; color: #1FAFB8; }}
                    .value {{ margin-top: 5px; }}
                    .message-box {{ background: white; padding: 15px; border-left: 4px solid #1FAFB8; margin-top: 10px; }}
                    .footer {{ background: #333; color: white; padding: 15px; border-radius: 0 0 10px 10px; font-size: 12px; text-align: center; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>📩 New Contact Form Message</h2>
                    </div>
                    <div class="content">
                        <div class="field">
                            <div class="label">From:</div>
                            <div class="value">{first_name} {last_name}</div>
                        </div>
                        <div class="field">
                            <div class="label">Email:</div>
                            <div class="value"><a href="mailto:{email}">{email}</a></div>
                        </div>
                        <div class="field">
                            <div class="label">Message:</div>
                            <div class="message-box">{message.replace(chr(10), '<br>')}</div>
                        </div>
                    </div>
                    <div class="footer">
                        This message was sent from the ICS website contact form.
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Plain text version
            text_body = f"""
New Contact Form Message
========================

From: {first_name} {last_name}
Email: {email}

Message:
{message}

---
This message was sent from the ICS website contact form.
            """
            
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email using CONTACT credentials
            with smtplib.SMTP(CONTACT_EMAIL_CONFIG['smtp_server'], CONTACT_EMAIL_CONFIG['smtp_port']) as server:
                server.starttls()
                server.login(CONTACT_EMAIL_CONFIG['sender_email'], CONTACT_EMAIL_CONFIG['sender_password'])
                server.send_message(msg)
            
            logger.info(f"Contact form email sent successfully from {email} via {CONTACT_EMAIL_CONFIG['sender_email']}")
            return jsonify({
                'success': True,
                'message': 'Thank you for your message! We will get back to you soon.'
            }), 200
            
        except smtplib.SMTPAuthenticationError:
            logger.error(f"Contact form: SMTP authentication failed for {CONTACT_EMAIL_CONFIG['sender_email']}")
            return jsonify({
                'success': False,
                'message': 'Unable to send message. Please try again later or contact us directly at info@ics.cw'
            }), 500
        except Exception as e:
            logger.error(f"Contact form email error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Unable to send message. Please try again later.'
            }), 500
            
    except Exception as e:
        logger.error(f'Contact form error: {e}')
        return jsonify({'success': False, 'message': 'An error occurred. Please try again.'}), 500

# API Info endpoint - now redirects to admin dashboard
@app.route('/', methods=['GET'])
def api_info():
    """Root endpoint - redirect to admin dashboard"""
    return redirect('/admin_login.html')

# API version info endpoint
@app.route('/api', methods=['GET'])
def api_version():
    """API information endpoint"""
    return jsonify({
        'name': 'Intelligence Cleaning Services API',
        'version': '1.0.0',
        'status': 'running',
        'environment': ENVIRONMENT,
        'endpoints': {
            'health': '/health',
            'register': '/register',
            'login': '/login',
            'bookings': '/api/bookings',
            'pricing': '/api/pricing/public'
        }
    }), 200

# Register
@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('firstName')
        last_name = data.get('lastName')
        phone = data.get('phone', '')
        address = data.get('address', '')
        newsletter = data.get('newsletter', False)
        
        if not email or not password or not first_name or not last_name:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Email already registered'}), 400
        
        # Create user
        hashed_password = hash_password(password)
        cursor.execute('''
            INSERT INTO users (first_name, last_name, email, phone, address, password, newsletter)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (first_name, last_name, email, phone, address, hashed_password, newsletter))
        
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Create token
        token = create_token(user_id, email)
        
        return jsonify({
            'success': True,
            'message': 'Registration successful',
            'token': token,
            'user': {
                'id': user_id,
                'email': email,
                'firstName': first_name,
                'lastName': last_name,
                'phone': phone
            }
        }), 201
        
    except Exception as e:
        logger.error(f'Registration error: {e}')
        return jsonify({'success': False, 'message': 'Registration failed'}), 500

# Login
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
        
        if not verify_password(password, user['password']):
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
        
        # Create token with role
        token = create_token(user['id'], user['email'], user['role'])
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'firstName': user['first_name'],
                'lastName': user['last_name'],
                'phone': user['phone'] or '',
                'role': user['role']
            }
        }), 200
        
    except Exception as e:
        logger.error(f'Login error: {e}')
        return jsonify({'success': False, 'message': 'Login failed'}), 500

# Admin Login
@app.route('/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE email = ? AND role = ?', (email, 'admin'))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'success': False, 'message': 'Invalid admin credentials'}), 401
        
        if not verify_password(password, user['password']):
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
        
        # Create token with admin role
        token = create_token(user['id'], user['email'], 'admin')
        
        return jsonify({
            'success': True,
            'message': 'Admin login successful',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'firstName': user['first_name'],
                'lastName': user['last_name'],
                'role': 'admin'
            }
        }), 200
        
    except Exception as e:
        logger.error(f'Admin login error: {e}')
        return jsonify({'success': False, 'message': 'Login failed'}), 500

# Admin Dashboard Stats
@app.route('/admin/dashboard', methods=['GET'])
@token_required
@admin_required
def admin_dashboard(current_user):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get today's date
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # Total bookings
        cursor.execute('SELECT COUNT(*) as count FROM bookings')
        total_bookings = cursor.fetchone()['count']
        
        # Pending bookings
        cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE status = 'pending'")
        pending_bookings = cursor.fetchone()['count']
        
        # Today's bookings
        cursor.execute('SELECT COUNT(*) as count FROM bookings WHERE booking_date = ?', (today,))
        today_bookings = cursor.fetchone()['count']
        
        # Total revenue (only from completed bookings)
        cursor.execute("""
            SELECT COALESCE(SUM(total_cost), 0) as revenue 
            FROM bookings 
            WHERE status = 'completed'
        """)
        total_revenue = cursor.fetchone()['revenue']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'totalBookings': total_bookings,
                'pendingBookings': pending_bookings,
                'todayBookings': today_bookings,
                'totalRevenue': float(total_revenue)
            }
        }), 200
        
    except Exception as e:
        logger.error(f'Dashboard stats error: {e}')
        return jsonify({'success': False, 'message': 'Failed to load stats'}), 500

# Verify Token
@app.route('/api/verify-token', methods=['GET'])
@token_required
def verify_token(current_user):
    return jsonify({
        'success': True,
        'user': current_user
    }), 200

# ============================================================
# BOOKING ENDPOINTS
# ============================================================

# Check slot availability for a given date
@app.route('/api/bookings/check-availability', methods=['POST'])
def check_availability():
    """Check booking slot availability for a specific date"""
    try:
        data = request.json
        date = data.get('date')
        
        if not date:
            return jsonify({'success': False, 'message': 'Date is required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Define slot limits
        slot_limits = {
            'morning': 2,
            'afternoon': 2,
            'evening': 1
        }
        
        # Count existing bookings for each slot on this date
        availability = {}
        for slot, limit in slot_limits.items():
            cursor.execute('''
                SELECT COUNT(*) as count FROM bookings 
                WHERE booking_date = ? AND time_slot = ? AND status != 'cancelled'
            ''', (date, slot))
            booked = cursor.fetchone()['count']
            remaining = max(0, limit - booked)
            
            availability[slot] = {
                'available': remaining > 0,
                'remaining': remaining,
                'total': limit
            }
        
        conn.close()
        
        return jsonify({
            'success': True,
            'availability': availability
        }), 200
        
    except Exception as e:
        logger.error(f'Error checking availability: {e}')
        return jsonify({'success': False, 'message': 'Failed to check availability'}), 500

# Get bookings for a specific user
@app.route('/api/bookings/user/<int:user_id>', methods=['GET'])
@token_required
def get_user_bookings(current_user, user_id):
    """Get bookings for a specific user"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # First get the user's email
        cursor.execute('SELECT email FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        user_email = user['email']
        
        # Get bookings for this user (match by customer_email)
        cursor.execute('''
            SELECT * FROM bookings 
            WHERE customer_email = ?
            ORDER BY booking_date DESC, created_at DESC
        ''', (user_email,))
        bookings = cursor.fetchall()
        conn.close()
        
        bookings_list = []
        for booking in bookings:
            bookings_list.append({
                'id': booking['id'],
                'customerName': booking['customer_name'],
                'customerPhone': booking['customer_phone'],
                'customerEmail': booking['customer_email'] if 'customer_email' in booking.keys() else '',
                'streetAddress': booking['street_address'],
                'neighborhood': booking['neighborhood'],
                'serviceType': booking['service_type'],
                'services': booking['services'],
                'bookingDate': booking['booking_date'],
                'timeSlot': booking['time_slot'],
                'totalCost': float(booking['total_cost']) if booking['total_cost'] else 0,
                'status': booking['status'],
                'notes': booking['notes'],
                'createdAt': booking['created_at'],
                'invoiceSent': booking['invoice_sent'] if 'invoice_sent' in booking.keys() else 0,
                'invoiceSentAt': booking['invoice_sent_at'] if 'invoice_sent_at' in booking.keys() else None
            })
        
        return jsonify({'success': True, 'bookings': bookings_list}), 200
        
    except Exception as e:
        logger.error(f'Error getting user bookings: {e}')
        return jsonify({'success': False, 'message': 'Failed to retrieve bookings'}), 500

@app.route('/api/bookings', methods=['GET'])
@token_required
@admin_required
def get_all_bookings(current_user):
    """Get all bookings (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM bookings 
            ORDER BY booking_date DESC, created_at DESC
        ''')
        bookings = cursor.fetchall()
        conn.close()
        
        bookings_list = []
        for booking in bookings:
            bookings_list.append({
                'id': booking['id'],
                'customerName': booking['customer_name'],
                'customerPhone': booking['customer_phone'],
                'customerEmail': booking['customer_email'] if 'customer_email' in booking.keys() else '',
                'streetAddress': booking['street_address'],
                'neighborhood': booking['neighborhood'],
                'serviceType': booking['service_type'],
                'services': booking['services'],
                'bookingDate': booking['booking_date'],
                'timeSlot': booking['time_slot'],
                'totalCost': float(booking['total_cost']) if booking['total_cost'] else 0,
                'status': booking['status'],
                'notes': booking['notes'],
                'createdAt': booking['created_at'],
                'invoiceSent': booking['invoice_sent'] if 'invoice_sent' in booking.keys() else 0,
                'invoiceSentAt': booking['invoice_sent_at'] if 'invoice_sent_at' in booking.keys() else None
            })
        
        return jsonify({'success': True, 'bookings': bookings_list}), 200
        
    except Exception as e:
        logger.error(f'Error getting bookings: {e}')
        return jsonify({'success': False, 'error': 'Failed to retrieve bookings'}), 500

@app.route('/api/bookings', methods=['POST'])
def create_booking():
    """Create a new booking"""
    try:
        data = request.json
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Accept both camelCase (from website) and snake_case field names
        customer_name = data.get('customerName') or data.get('customer_name')
        customer_phone = data.get('customerPhone') or data.get('customer_phone')
        customer_email = data.get('customerEmail') or data.get('customer_email', '')
        street_address = data.get('streetAddress') or data.get('street_address')
        neighborhood = data.get('neighborhood')
        service_type = data.get('serviceType') or data.get('service_type')
        services = data.get('services', [])
        booking_date = data.get('date') or data.get('booking_date')
        time_slot = data.get('timeSlot') or data.get('time_slot')
        total_cost = data.get('totalCost') or data.get('total_cost', 0)
        notes = data.get('notes', '')
        
        cursor.execute('''
            INSERT INTO bookings 
            (customer_name, customer_phone, customer_email, street_address, neighborhood, 
             service_type, services, booking_date, time_slot, total_cost, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            customer_name,
            customer_phone,
            customer_email,
            street_address,
            neighborhood,
            service_type,
            str(services),
            booking_date,
            time_slot,
            float(total_cost) if total_cost else 0,
            'pending',
            notes
        ))
        
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"New booking created: #{booking_id}")
        
        return jsonify({
            'success': True,
            'message': 'Booking created successfully',
            'booking': {
                'id': booking_id
            }
        }), 201
        
    except Exception as e:
        logger.error(f'Error creating booking: {e}')
        return jsonify({'success': False, 'message': 'Failed to create booking'}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['GET'])
@token_required
def get_booking(current_user, booking_id):
    """Get a specific booking"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        conn.close()
        
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
        
        return jsonify({
            'id': booking['id'],
            'customer_name': booking['customer_name'],
            'customer_phone': booking['customer_phone'],
            'customer_email': booking['customer_email'] if 'customer_email' in booking.keys() else '',
            'street_address': booking['street_address'],
            'neighborhood': booking['neighborhood'],
            'service_type': booking['service_type'],
            'services': booking['services'],
            'booking_date': booking['booking_date'],
            'time_slot': booking['time_slot'],
            'total_cost': float(booking['total_cost']) if booking['total_cost'] else 0,
            'status': booking['status'],
            'notes': booking['notes'],
            'created_at': booking['created_at'],
            'invoice_sent': booking['invoice_sent'] if 'invoice_sent' in booking.keys() else 0,
            'invoice_sent_at': booking['invoice_sent_at'] if 'invoice_sent_at' in booking.keys() else None
        }), 200
        
    except Exception as e:
        logger.error(f'Error getting booking: {e}')
        return jsonify({'error': 'Failed to retrieve booking'}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['PUT'])
@token_required
@admin_required
def update_booking(current_user, booking_id):
    """Update a booking (admin only)"""
    try:
        data = request.json
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM bookings WHERE id = ?', (booking_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Booking not found'}), 404
        
        cursor.execute('''
            UPDATE bookings 
            SET customer_name = ?, customer_phone = ?, customer_email = ?,
                street_address = ?, neighborhood = ?, service_type = ?, 
                services = ?, booking_date = ?, time_slot = ?, 
                total_cost = ?, status = ?, notes = ?
            WHERE id = ?
        ''', (
            data.get('customer_name'),
            data.get('customer_phone'),
            data.get('customer_email', ''),
            data.get('street_address'),
            data.get('neighborhood'),
            data.get('service_type'),
            str(data.get('services', [])),
            data.get('booking_date'),
            data.get('time_slot'),
            float(data.get('total_cost', 0)),
            data.get('status'),
            data.get('notes', ''),
            booking_id
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Booking updated: #{booking_id}")
        
        return jsonify({
            'success': True,
            'message': 'Booking updated successfully'
        }), 200
        
    except Exception as e:
        logger.error(f'Error updating booking: {e}')
        return jsonify({'error': 'Failed to update booking'}), 500

@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_booking(current_user, booking_id):
    """Delete a booking (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM bookings WHERE id = ?', (booking_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Booking not found'}), 404
        
        cursor.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"Booking deleted: #{booking_id}")
        
        return jsonify({
            'success': True,
            'message': 'Booking deleted successfully'
        }), 200
        
    except Exception as e:
        logger.error(f'Error deleting booking: {e}')
        return jsonify({'error': 'Failed to delete booking'}), 500

@app.route('/api/bookings/<int:booking_id>/status', methods=['PATCH'])
@token_required
@admin_required
def update_booking_status(current_user, booking_id):
    """Update booking status (admin only)"""
    try:
        data = request.json
        new_status = data.get('status')
        
        if new_status not in ['pending', 'confirmed', 'completed', 'cancelled']:
            return jsonify({'error': 'Invalid status'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE bookings SET status = ? WHERE id = ?', (new_status, booking_id))
        conn.commit()
        conn.close()
        
        logger.info(f"Booking #{booking_id} status updated to: {new_status}")
        
        return jsonify({
            'success': True,
            'message': f'Booking status updated to {new_status}'
        }), 200
        
    except Exception as e:
        logger.error(f'Error updating booking status: {e}')
        return jsonify({'error': 'Failed to update status'}), 500

# ============================================================
# INVOICE ENDPOINTS
# ============================================================

@app.route('/api/bookings/<int:booking_id>/invoice', methods=['GET'])
@token_required
def get_invoice(current_user, booking_id):
    """Generate and return invoice PDF"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        conn.close()
        
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
        
        # Generate PDF
        pdf_buffer = generate_invoice_pdf(dict(booking))
        
        from flask import send_file
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ICS_Invoice_{booking_id}.pdf"
        )
        
    except Exception as e:
        logger.error(f'Error generating invoice: {e}')
        return jsonify({'error': 'Failed to generate invoice'}), 500

@app.route('/api/bookings/<int:booking_id>/send-invoice', methods=['POST'])
@token_required
@admin_required
def send_invoice(current_user, booking_id):
    """Send invoice email to customer"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,))
        booking = cursor.fetchone()
        
        if not booking:
            conn.close()
            return jsonify({'success': False, 'message': 'Booking not found'}), 404
        
        booking_dict = dict(booking)
        
        # Generate PDF
        pdf_buffer = generate_invoice_pdf(booking_dict)
        
        # Send email
        success, message = send_invoice_email(booking_dict, pdf_buffer)
        
        if success:
            # Update invoice_sent status
            cursor.execute('''
                UPDATE bookings 
                SET invoice_sent = 1, invoice_sent_at = ? 
                WHERE id = ?
            ''', (datetime.datetime.now().isoformat(), booking_id))
            conn.commit()
        
        conn.close()
        
        return jsonify({
            'success': success,
            'message': message
        }), 200 if success else 400
        
    except Exception as e:
        logger.error(f'Error sending invoice: {e}')
        return jsonify({'success': False, 'message': f'Failed to send invoice: {str(e)}'}), 500

# ============================================================
# PRICING ENDPOINTS
# ============================================================

@app.route('/api/pricing', methods=['GET'])
@token_required
@admin_required
def get_all_pricing(current_user):
    """Get all service pricing (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM service_pricing 
            ORDER BY category, display_order, service_name
        ''')
        services = cursor.fetchall()
        conn.close()
        
        services_list = []
        for service in services:
            services_list.append({
                'id': service['id'],
                'service_name': service['service_name'],
                'base_price': float(service['base_price']),
                'unit': service['unit'],
                'description': service['description'] or '',
                'is_active': bool(service['is_active']),
                'category': service['category'] or 'Other',
                'display_order': service['display_order'] or 0
            })
        
        return jsonify(services_list), 200
        
    except Exception as e:
        logger.error(f'Error getting pricing: {e}')
        return jsonify({'error': 'Failed to retrieve pricing'}), 500

@app.route('/api/pricing/<int:service_id>', methods=['PUT'])
@token_required
@admin_required
def update_pricing(current_user, service_id):
    """Update service pricing (admin only)"""
    try:
        data = request.json
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM service_pricing WHERE id = ?', (service_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404
        
        cursor.execute('''
            UPDATE service_pricing 
            SET service_name = ?, base_price = ?, unit = ?, description = ?, 
                is_active = ?, category = ?, display_order = ?
            WHERE id = ?
        ''', (
            data.get('service_name'),
            float(data.get('base_price', 0)),
            data.get('unit'),
            data.get('description', ''),
            1 if data.get('is_active', True) else 0,
            data.get('category', 'Other'),
            int(data.get('display_order', 0)),
            service_id
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Service updated successfully'
        }), 200
        
    except Exception as e:
        logger.error(f'Error updating service: {e}')
        return jsonify({'error': 'Failed to update service'}), 500

@app.route('/api/pricing', methods=['POST'])
@token_required
@admin_required
def add_pricing(current_user):
    """Add new service pricing (admin only)"""
    try:
        data = request.json
        
        service_name = data.get('service_name')
        base_price = data.get('base_price', 0)
        unit = data.get('unit', 'per service')
        description = data.get('description', '')
        is_active = data.get('is_active', True)
        category = data.get('category', 'Other')
        display_order = data.get('display_order', 0)
        
        if not service_name:
            return jsonify({'error': 'Service name is required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO service_pricing (service_name, base_price, unit, description, is_active, category, display_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (service_name, float(base_price), unit, description, 1 if is_active else 0, category, int(display_order)))
        
        service_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': 'Service added successfully',
            'service_id': service_id
        }), 201
        
    except Exception as e:
        logger.error(f'Error adding service: {e}')
        return jsonify({'error': 'Failed to add service'}), 500

@app.route('/api/pricing/<int:service_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_service(current_user, service_id):
    """Delete a service"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM service_pricing WHERE id = ?', (service_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404
        
        cursor.execute('DELETE FROM service_pricing WHERE id = ?', (service_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Service deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f'Error deleting service: {e}')
        return jsonify({'error': 'Failed to delete service'}), 500

@app.route('/api/pricing/reset', methods=['POST'])
@token_required
@admin_required
def reset_pricing(current_user):
    """Reset all pricing to default values that match website (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Delete all existing pricing
        cursor.execute('DELETE FROM service_pricing')
        
        # Insert the correct services that match website.html servicePriceMapping
        services = [
            # Basic Cleaning
            ('Base price for basic residential cleaning', 85.00, 'per service', 'Base price for basic residential cleaning service', 1, 'basic', 1),
            ('Additional bedroom (basic cleaning)', 18.00, 'per bedroom', 'Additional charge per bedroom for basic cleaning', 1, 'basic', 2),
            ('Additional bathroom (basic cleaning)', 20.00, 'per bathroom', 'Additional charge per bathroom for basic cleaning', 1, 'basic', 3),
            # Deep Cleaning
            ('Base price for deep residential cleaning', 130.00, 'per service', 'Base price for deep residential cleaning service', 1, 'deep', 4),
            ('Additional bedroom (deep cleaning)', 18.00, 'per bedroom', 'Additional charge per bedroom for deep cleaning', 1, 'deep', 5),
            ('Additional bathroom (deep cleaning)', 20.00, 'per bathroom', 'Additional charge per bathroom for deep cleaning', 1, 'deep', 6),
            # Add-on Services
            ('Sofa/Couch Cleaning', 40.00, 'per service', 'Deep cleaning for sofas and couches', 1, 'add-on', 7),
            ('Mattress Cleaning', 70.00, 'per service', 'Deep cleaning and sanitization for mattresses', 1, 'add-on', 8),
            ('Electrostatic Cleaning (per room)', 30.00, 'per room', 'Electrostatic disinfection cleaning per room', 1, 'add-on', 9),
            ('Pool Cleaning', 50.00, 'per service', 'Pool cleaning service', 1, 'add-on', 10),
            # Office Cleaning
            ('Base price for office cleaning', 50.00, 'per service', 'Base price for office cleaning service', 1, 'office', 11),
            ('Additional office', 18.00, 'per room', 'Additional charge per office room', 1, 'office', 12),
            ('Additional bathroom (office)', 20.00, 'per bathroom', 'Additional charge per bathroom for office cleaning', 1, 'office', 13),
            ('Office Sofa Cleaning', 40.00, 'per service', 'Deep cleaning for office sofas and couches', 1, 'office', 14),
            ('Office Electrostatic Cleaning', 30.00, 'per room', 'Electrostatic disinfection cleaning for offices', 1, 'office', 15),
        ]
        
        for service in services:
            cursor.execute('''
                INSERT INTO service_pricing (service_name, base_price, unit, description, is_active, category, display_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', service)
        
        conn.commit()
        conn.close()
        
        logger.info("Pricing reset to default values")
        return jsonify({'success': True, 'message': 'Pricing reset successfully', 'count': len(services)}), 200
        
    except Exception as e:
        logger.error(f'Error resetting pricing: {e}')
        return jsonify({'success': False, 'error': 'Failed to reset pricing'}), 500

@app.route('/api/pricing/public', methods=['GET'])
def get_public_pricing():
    """Get active service pricing for customers"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, service_name, base_price, unit, description, category, display_order
            FROM service_pricing 
            WHERE is_active = 1
            ORDER BY category, display_order, service_name
        ''')
        services = cursor.fetchall()
        conn.close()
        
        services_list = []
        for service in services:
            services_list.append({
                'id': service['id'],
                'service_name': service['service_name'],
                'base_price': float(service['base_price']),
                'unit': service['unit'],
                'description': service['description'] or '',
                'category': service['category'] or 'Other'
            })
        
        return jsonify(services_list), 200
        
    except Exception as e:
        logger.error(f'Error getting public pricing: {e}')
        return jsonify({'error': 'Failed to retrieve pricing'}), 500

# ============================================================
# USER MANAGEMENT ENDPOINTS
# ============================================================

@app.route('/api/users', methods=['GET'])
@token_required
@admin_required
def get_all_users(current_user):
    """Get all users (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, first_name, last_name, email, phone, role, created_at 
            FROM users 
            ORDER BY created_at DESC
        ''')
        users = cursor.fetchall()
        conn.close()
        
        users_list = []
        for user in users:
            users_list.append({
                'id': user['id'],
                'firstName': user['first_name'],
                'lastName': user['last_name'],
                'email': user['email'],
                'phone': user['phone'] or '',
                'role': user['role'],
                'created_at': user['created_at']
            })
        
        return jsonify(users_list), 200
        
    except Exception as e:
        logger.error(f'Error getting users: {e}')
        return jsonify({'error': 'Failed to retrieve users'}), 500

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@token_required
@admin_required
def update_user(current_user, user_id):
    """Update user details (admin only)"""
    try:
        data = request.json
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT id, role FROM users WHERE id = ?', (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            conn.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Prevent changing the last admin to non-admin
        if existing_user['role'] == 'admin' and data.get('role') != 'admin':
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'")
            admin_count = cursor.fetchone()['count']
            if admin_count <= 1:
                conn.close()
                return jsonify({'success': False, 'message': 'Cannot remove the last admin'}), 400
        
        # Check if password is being updated
        new_password = data.get('password')
        
        if new_password and len(new_password) >= 6:
            # Update user with new password
            hashed_password = hash_password(new_password)
            cursor.execute('''
                UPDATE users 
                SET first_name = ?, last_name = ?, email = ?, phone = ?, role = ?, password = ?
                WHERE id = ?
            ''', (
                data.get('first_name'),
                data.get('last_name'),
                data.get('email'),
                data.get('phone', ''),
                data.get('role', 'customer'),
                hashed_password,
                user_id
            ))
        else:
            # Update user without changing password
            cursor.execute('''
                UPDATE users 
                SET first_name = ?, last_name = ?, email = ?, phone = ?, role = ?
                WHERE id = ?
            ''', (
                data.get('first_name'),
                data.get('last_name'),
                data.get('email'),
                data.get('phone', ''),
                data.get('role', 'customer'),
                user_id
            ))
        
        conn.commit()
        conn.close()
        
        password_msg = ' Password updated.' if new_password and len(new_password) >= 6 else ''
        return jsonify({
            'success': True,
            'message': f'User updated successfully.{password_msg}'
        }), 200
        
    except Exception as e:
        logger.error(f'Error updating user: {e}')
        return jsonify({'success': False, 'message': 'Failed to update user'}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_user(current_user, user_id):
    """Delete a user (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT id, role, email FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Prevent deleting admins
        if user['role'] == 'admin':
            conn.close()
            return jsonify({'success': False, 'message': 'Cannot delete admin users'}), 400
        
        # Prevent self-deletion
        if user_id == current_user['user_id']:
            conn.close()
            return jsonify({'success': False, 'message': 'Cannot delete your own account'}), 400
        
        # Delete user
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'User deleted successfully'
        }), 200
        
    except Exception as e:
        logger.error(f'Error deleting user: {e}')
        return jsonify({'success': False, 'message': 'Failed to delete user'}), 500

# ============================================================
# ADMIN DASHBOARD ROUTES - Serve HTML Pages
# ============================================================

@app.route('/admin_login.html')
def serve_admin_login_page():
    """Serve admin login page"""
    return render_template('admin_login.html')

@app.route('/admin_bookings.html')
def serve_admin_bookings_page():
    """Serve admin bookings page"""
    return render_template('admin_bookings.html')

@app.route('/admin_calendar.html')
def serve_admin_calendar_page():
    """Serve admin calendar page"""
    return render_template('admin_calendar.html')

@app.route('/pricing_management.html')
def serve_pricing_management_page():
    """Serve pricing management page"""
    return render_template('pricing_management.html')

@app.route('/user_management.html')
def serve_user_management_page():
    """Serve user management page"""
    return render_template('user_management.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/admin_config.js')
def serve_admin_config():
    """Serve admin config file from current directory or static folder"""
    # Try current directory first, then static folder
    if os.path.exists('admin_config.js'):
        return send_from_directory('.', 'admin_config.js')
    return send_from_directory('static', 'admin_config.js')

@app.route('/<path:filename>')
def serve_file(filename):
    """Serve any HTML file from templates directory"""
    # Don't catch API routes
    if filename.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    if filename.endswith('.html'):
        try:
            return render_template(filename)
        except:
            return jsonify({'error': 'Page not found'}), 404
    # Try to serve JS files from static folder first
    if filename.endswith('.js'):
        try:
            return send_from_directory('static', filename)
        except:
            pass
    # Try to serve from current directory (for logo, etc.)
    try:
        return send_from_directory('.', filename)
    except:
        return jsonify({'error': 'File not found'}), 404

# ============================================================
# MAIN - Production Ready
# ============================================================

if __name__ == '__main__':
    # Get port from environment variable (Render sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("Intelligence Cleaning Solutions - API Server")
    print("=" * 60)
    print(f"Environment: {ENVIRONMENT}")
    print(f"Starting server on http://0.0.0.0:{port}")
    print(f"Database: {DATABASE}")
    print("")
    print("Email Configuration Status:")
    if EMAIL_CONFIG['enabled']:
        print(f"  ✅ Email ENABLED - Sender: {EMAIL_CONFIG['sender_email']}")
    else:
        print("  ❌ Email DISABLED - Set MAIL_USERNAME and MAIL_PASSWORD")
    print("")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    # In production, debug should be False
    debug_mode = not IS_PRODUCTION
    
    app.run(
        debug=debug_mode,
        host='0.0.0.0',
        port=port
    )
