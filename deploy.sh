#!/bin/bash

# PICS Courier Application Deployment Script

echo "🚀 Deploying PICS Courier Application..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker-compose down

# Build and start the application
echo "🔨 Building and starting the application..."
docker-compose up --build -d

# Wait for the application to start
echo "⏳ Waiting for application to start..."
sleep 10

# Check if the application is running
if curl -f http://localhost:5000/ &> /dev/null; then
    echo "✅ Application deployed successfully!"
    echo "🌐 Application is available at: http://localhost:5000"
    echo "📊 Container status:"
    docker-compose ps
else
    echo "❌ Application failed to start. Checking logs..."
    docker-compose logs
fi