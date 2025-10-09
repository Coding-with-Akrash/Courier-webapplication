#!/usr/bin/env python3
"""
Test database connection
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'test-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/courier.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class TestClient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

try:
    with app.app_context():
        # Create tables
        db.create_all()
        print("Database connection successful!")
        print("Tables created successfully!")

        # Test query
        client = TestClient(name="Test User", email="test@example.com")
        db.session.add(client)
        db.session.commit()
        print("Test data inserted successfully!")

        # Verify data
        clients = TestClient.query.all()
        print(f"Found {len(clients)} clients in database")

except Exception as e:
    print(f"Database error: {e}")
    import traceback
    traceback.print_exc()