#!/usr/bin/env python3
"""
Script to check the database schema and data
"""
import sqlite3
import os

def check_database():
    db_path = 'instance/courier.db'

    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return False

    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check shipment table schema
        print("=== SHIPMENT TABLE SCHEMA ===")
        cursor.execute("PRAGMA table_info(shipment)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]}: {col[2]} (nullable: {col[3]})")

        # Check if there are any shipments
        print("\n=== SHIPMENT DATA ===")
        cursor.execute("SELECT COUNT(*) FROM shipment")
        count = cursor.fetchone()[0]
        print(f"Total shipments: {count}")

        if count > 0:
            # Check first few shipments
            cursor.execute("SELECT id, tracking_id, document_type FROM shipment LIMIT 5")
            shipments = cursor.fetchall()
            print("\nFirst 5 shipments:")
            for shipment in shipments:
                print(f"  ID: {shipment[0]}, Tracking: {shipment[1]}, Doc Type: {shipment[2]}")

            # Check for NULL document_type values
            cursor.execute("SELECT COUNT(*) FROM shipment WHERE document_type IS NULL")
            null_count = cursor.fetchone()[0]
            print(f"\nShipments with NULL document_type: {null_count}")

        conn.close()
        return True

    except Exception as e:
        print(f"ERROR: {str(e)}")
        if 'conn' in locals():
            conn.close()
        return False

if __name__ == "__main__":
    print("Checking database...")
    check_database()