#!/usr/bin/env python3
"""
Admin Dashboard Server with Robust Error Handling
Serves admin HTML files on port 5001 with proper MIME types
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import sys
import socket

class RobustHTTPServer(HTTPServer):
    """HTTP Server that properly handles connection errors"""
    
    def handle_error(self, request, client_address):
        """Override to suppress connection errors silently"""
        # Get the exception info
        import sys
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        # Suppress common connection errors
        if exc_type in (ConnectionAbortedError, ConnectionResetError, 
                       BrokenPipeError, ConnectionError):
            # These are normal - browser closed connection
            pass
        else:
            # For other errors, just log them briefly without full traceback
            print(f"Request error: {exc_type.__name__}", file=sys.stderr)

class AdminDashboardHandler(SimpleHTTPRequestHandler):
    """Custom handler for admin dashboard files"""
    
    def handle(self):
        """Override to catch errors during request handling"""
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, 
                BrokenPipeError, ConnectionError, socket.error):
            # Connection errors are normal, suppress them
            pass
        except Exception:
            # Other exceptions should still be handled by the server
            raise
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS"""
        try:
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers()
        except (ConnectionAbortedError, BrokenPipeError, 
                ConnectionResetError, ConnectionError, socket.error):
            pass
    
    def log_message(self, format, *args):
        """Custom log format - only log successful requests"""
        if '200' in str(args) or '304' in str(args):
            sys.stdout.write("%s - [%s] %s\n" % (
                self.address_string(),
                self.log_date_time_string(),
                format % args
            ))

def run_server(port=5001):
    """Run the admin dashboard server"""
    
    print("=" * 60)
    print("Intelligence Cleaning Solutions - Admin Dashboard Server")
    print("=" * 60)
    print(f"Starting server on http://127.0.0.1:{port}")
    print(f"Press Ctrl+C to stop")
    print("=" * 60)
    print()
    print("Admin Pages Available:")
    print(f"  • Login:           http://127.0.0.1:{port}/admin_login.html")
    print(f"  • Bookings:        http://127.0.0.1:{port}/admin_bookings.html")
    print(f"  • Pricing:         http://127.0.0.1:{port}/pricing_management.html")
    print(f"  • User Management: http://127.0.0.1:{port}/user_management.html")
    print()
    print("=" * 60)
    print()
    
    try:
        server_address = ('', port)
        # Use our custom server class
        httpd = RobustHTTPServer(server_address, AdminDashboardHandler)
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        httpd.shutdown()
    except OSError as e:
        if e.errno == 48 or e.errno == 10048:  # Address already in use
            print(f"\n❌ ERROR: Port {port} is already in use!")
            print("Please close any other server running on this port and try again.")
            sys.exit(1)
        else:
            raise

if __name__ == '__main__':
    port = 5001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port number. Using default port 5001.")
    
    run_server(port)
