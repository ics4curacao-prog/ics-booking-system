#!/usr/bin/env python3
"""
Admin Dashboard Flask Application
Serves admin HTML files for production deployment with gunicorn
"""

from flask import Flask, render_template, send_from_directory, redirect, url_for
from flask_cors import CORS
import os

# Create Flask app
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

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
    if filename.endswith('.html'):
        return render_template(filename)
    return send_from_directory('.', filename)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'healthy', 'service': 'ICS Admin Dashboard'}

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
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=debug)
