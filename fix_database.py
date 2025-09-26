#!/usr/bin/env python3
"""
Script to fix the missing document_type column in the shipment table
"""
import sqlite3
import os

def fix_database():
    db_path = 'instance/courier.db'

    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return False

    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if the column already exists
        cursor.execute("PRAGMA table_info(shipment)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'document_type' in column_names:
            print("Column 'document_type' already exists in the shipment table.")
            return True

        # Add the missing column
        print("Adding 'document_type' column to shipment table...")
        cursor.execute("ALTER TABLE shipment ADD COLUMN document_type VARCHAR(20) DEFAULT 'non_docs'")

        # Verify the column was added
        cursor.execute("PRAGMA table_info(shipment)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'document_type' in column_names:
            print("SUCCESS: Successfully added 'document_type' column to shipment table!")
            conn.commit()
            conn.close()
            return True
        else:
            print("FAILED: Failed to add 'document_type' column.")
            conn.close()
            return False

    except Exception as e:
        print(f"ERROR: {str(e)}")
        if 'conn' in locals():
            conn.close()
        return False

if __name__ == "__main__":
    print("Fixing database schema...")
    success = fix_database()
    if success:
        print("Database fix completed successfully!")
    else:
        print("Database fix failed!")