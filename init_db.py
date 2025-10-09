#!/usr/bin/env python3
"""
Database initialization script
"""
from main import app, db, create_tables

try:
    with app.app_context():
        print("Creating database tables...")
        create_tables()
        print("✅ Database initialized successfully!")
        print("📊 You can now run the application with: python main.py")
except Exception as e:
    print(f"❌ Error initializing database: {e}")
    exit(1)