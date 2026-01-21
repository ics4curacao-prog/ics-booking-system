#!/usr/bin/env python3
"""
Admin Dashboard Flask Application
Serves admin HTML files for production deployment with gunicorn
Includes API endpoints for contact form and public pricing
"""

from flask import Flask, render_template, send_from_directory, redirect, request, jsonify
from flask_cors import CORS
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# ============================================================
# EMAIL CONFIGURATION - Use environment variables
# ============================================================
EMAIL_CONFIG = {
    'smtp_server': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.environ.get('MAIL_PORT', 587)),
    'sender_email': os.environ.get('MAIL_USERNAME', ''),
    'sender_password': os.environ.get('MAIL_PASSWORD', ''),
    'sender_name': os.environ.get('MAIL_SENDER_NAME', 'Intelligence Cleaning Services'),
    'enabled': True
}

# Validate email configuration
if not EMAIL_CONFIG['sender_email'] or not EMAIL_CONFIG['sender_password']:
    logger.warning("Email credentials not configured. Set MAIL_USERNAME and MAIL_PASSWORD environment variables.")
    EMAIL_CONFIG['enabled'] = False
else:
    logger.info(f"Email configured with sender: {EMAIL_CONFIG['sender_email']}")

# ============================================================
# ROUTES - Serve Admin Pages
# ============================================================

@app.route('/')
def index():
    """Redirect to login page"""
    return redirect('/admin_login.html')

@app.route('/admin_login.html')
def admin_login():
    """Serve admin login page"""
    return render_template('admin_login.html')

@app.route('/admin_bookings.html')
def admin_bookings():
    """Serve admin bookings page"""
    return render_template('admin_bookings.html')

@app.route('/admin_calendar.html')
def admin_calendar():
    """Serve admin calendar page"""
    return render_template('admin_calendar.html')

@app.route('/pricing_management.html')
def pricing_management():
    """Serve pricing management page"""
    return render_template('pricing_management.html')

@app.route('/user_management.html')
def user_management():
    """Serve user management page"""
    return render_template('user_management.html')

# ============================================================
# STATIC FILES
# ============================================================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/<path:filename>')
def serve_file(filename):
    """Serve any file from templates directory"""
    # Don't catch API routes
    if filename.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    if filename.endswith('.html'):
        return render_template(filename)
    return send_from_directory('.', filename)

# ============================================================
# API ENDPOINTS
# ============================================================

@app.route('/api/contact', methods=['POST', 'OPTIONS'])
def contact_form():
    """Handle contact form submissions - sends email to info@ics.cw"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
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
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({
                'success': False,
                'message': 'Please enter a valid email address'
            }), 400
        
        # Check if email is configured
        if not EMAIL_CONFIG['enabled']:
            logger.warning("Contact form submitted but email is not configured")
            return jsonify({
                'success': False,
                'message': 'Email service is not configured. Please contact us directly at info@ics.cw'
            }), 500
        
        # Send email to info@ics.cw
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"New Contact Form Message from {first_name} {last_name}"
            msg['From'] = f"{EMAIL_CONFIG['sender_name']} <{EMAIL_CONFIG['sender_email']}>"
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
            
            # Send email
            with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
                server.starttls()
                server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
                server.send_message(msg)
            
            logger.info(f"Contact form email sent successfully from {email}")
            return jsonify({
                'success': True,
                'message': 'Thank you for your message! We will get back to you soon.'
            }), 200
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Contact form: SMTP authentication failed: {e}")
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


@app.route('/api/pricing/public', methods=['GET'])
def get_public_pricing():
    """Get public pricing - returns default pricing for display"""
    # Default pricing data for the website
    default_pricing = [
        {'id': 1, 'service_name': 'Basic Cleaning', 'base_price': 75.00, 'unit': 'per visit', 'description': 'Standard cleaning service', 'category': 'Residential'},
        {'id': 2, 'service_name': 'Deep Cleaning', 'base_price': 150.00, 'unit': 'per visit', 'description': 'Thorough deep cleaning', 'category': 'Residential'},
        {'id': 3, 'service_name': 'Mattress Cleaning', 'base_price': 50.00, 'unit': 'per mattress', 'description': 'Professional mattress cleaning', 'category': 'Specialty'},
        {'id': 4, 'service_name': 'Sofa Cleaning', 'base_price': 75.00, 'unit': 'per sofa', 'description': 'Upholstery cleaning', 'category': 'Specialty'},
        {'id': 5, 'service_name': 'Pool Cleaning', 'base_price': 100.00, 'unit': 'per visit', 'description': 'Pool maintenance and cleaning', 'category': 'Outdoor'},
        {'id': 6, 'service_name': 'Office Cleaning', 'base_price': 125.00, 'unit': 'per visit', 'description': 'Commercial office cleaning', 'category': 'Commercial'},
    ]
    return jsonify(default_pricing), 200


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy', 
        'service': 'ICS Admin Dashboard',
        'email_enabled': EMAIL_CONFIG['enabled'],
        'email_sender': EMAIL_CONFIG['sender_email'] if EMAIL_CONFIG['enabled'] else 'not configured'
    })

# ============================================================
# RUN SERVER
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print("=" * 60)
    print("Intelligence Cleaning Solutions - Admin Dashboard")
    print("=" * 60)
    print(f"Starting server on http://127.0.0.1:{port}")
    print("")
    print("Email Configuration Status:")
    if EMAIL_CONFIG['enabled']:
        print(f"  ✅ Email ENABLED - Sender: {EMAIL_CONFIG['sender_email']}")
    else:
        print("  ❌ Email DISABLED - Set MAIL_USERNAME and MAIL_PASSWORD")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=debug)
