#!/usr/bin/env python3
"""
Intelligence Cleaning Solutions - Database Initialization
Creates and initializes the SQLite database with required tables
"""

import sqlite3
import os
import sys

DATABASE_FILE = 'cleaning_service.db'

# SQL schema for creating tables
CREATE_TABLES_SQL = """
-- Users table for authentication
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    address TEXT,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'customer',
    newsletter BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bookings table
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    booking_date DATE NOT NULL,
    time_slot TEXT NOT NULL,
    street_address TEXT NOT NULL,
    neighborhood TEXT NOT NULL,
    service_type TEXT NOT NULL,
    services TEXT NOT NULL,
    total_cost INTEGER NOT NULL,
    notes TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(booking_date);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""

def create_database():
    """Create the database and tables"""
    try:
        # Check if database already exists
        db_exists = os.path.exists(DATABASE_FILE)
        
        if db_exists:
            print("WARNING: Database '{}' already exists.".format(DATABASE_FILE))
            response = input("Do you want to recreate it? (yes/no): ").lower()
            if response not in ['yes', 'y']:
                print("Database initialization cancelled.")
                return False
            
            # Backup existing database
            backup_file = "{}.backup".format(DATABASE_FILE)
            import shutil
            shutil.copy2(DATABASE_FILE, backup_file)
            print("SUCCESS: Existing database backed up to: {}".format(backup_file))
            
            # Remove old database
            os.remove(DATABASE_FILE)
        
        # Create new database connection
        print("Creating database: {}".format(DATABASE_FILE))
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Execute SQL to create tables
        print("Creating tables...")
        cursor.executescript(CREATE_TABLES_SQL)
        
        # Commit changes
        conn.commit()
        
        # Verify tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        print("\n" + "=" * 60)
        print("SUCCESS: DATABASE INITIALIZED SUCCESSFULLY")
        print("=" * 60)
        print("\nDatabase file: {}".format(DATABASE_FILE))
        print("Tables created: {}".format(len(tables)))
        for table in tables:
            print("  - {}".format(table[0]))
        print("\nNext steps:")
        print("1. Create an admin user: python create_admin.py")
        print("2. Start the API server: python api.py")
        print("3. Start the admin dashboard: python admin_dashboard.py")
        print("=" * 60)
        
        # Close connection
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print("\nERROR: Database error: {}".format(e))
        return False
    except Exception as e:
        print("\nERROR: Unexpected error: {}".format(e))
        return False

def verify_database():
    """Verify database structure"""
    if not os.path.exists(DATABASE_FILE):
        print("ERROR: Database file '{}' not found!".format(DATABASE_FILE))
        return False
    
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Check if required tables exist
        required_tables = ['users', 'bookings']
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = [table[0] for table in cursor.fetchall()]
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            print("ERROR: Missing tables: {}".format(', '.join(missing_tables)))
            conn.close()
            return False
        
        print("SUCCESS: Database structure verified")
        
        # Show table counts
        for table in required_tables:
            cursor.execute("SELECT COUNT(*) FROM {}".format(table))
            count = cursor.fetchone()[0]
            print("  {}: {} records".format(table, count))
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print("ERROR: Error verifying database: {}".format(e))
        return False

def main():
    """Main function"""
    print("=" * 60)
    print("Intelligence Cleaning Solutions - Database Setup")
    print("=" * 60)
    print()
    
    if len(sys.argv) > 1 and sys.argv[1] == 'verify':
        # Verify existing database
        verify_database()
    else:
        # Create new database
        success = create_database()
        if success:
            print("\nSUCCESS: Database is ready to use!")
        else:
            print("\nERROR: Database initialization failed!")
            sys.exit(1)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
