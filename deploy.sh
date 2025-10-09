#!/bin/bash

# PICS Courier Application Deployment Script
echo "🚀 Starting deployment process..."

# Check if we're in the right directory
if [ ! -f "main.py" ] || [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    exit 1
fi

# Generate a secure secret key
if [ -z "$SECRET_KEY" ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "🔑 Generated secure SECRET_KEY: $SECRET_KEY"
fi

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🔧 Running database migrations..."
python fix_database.py

echo "✅ Testing application..."
python -c "from main import app; print('✅ Application loads successfully')"

echo "🌐 Application is ready for deployment!"
echo ""
echo "📋 Next steps:"
echo "1. Railway: railway login && railway up"
echo "2. Render: Connect your GitHub repository"
echo "3. Heroku: git push heroku main"
echo ""
echo "🔐 Make sure to set these environment variables:"
echo "   SECRET_KEY=$SECRET_KEY"
echo "   FLASK_ENV=production"
echo ""
echo "🎉 Deployment script completed!"