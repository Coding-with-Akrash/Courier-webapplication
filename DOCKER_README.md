# Docker Deployment Guide for PICS Courier Application

This application has been dockerized and is ready for container deployment.

## Files Created

- `Dockerfile` - Main container configuration
- `.dockerignore` - Files to exclude from Docker build
- `docker-compose.yml` - Easy deployment configuration

## Deployment Instructions

### Option 1: Using Docker Compose (Recommended)

1. **Build and run the container:**
   ```bash
   docker-compose up --build
   ```

2. **Run in background:**
   ```bash
   docker-compose up -d --build
   ```

3. **Stop the application:**
   ```bash
   docker-compose down
   ```

### Option 2: Using Docker Commands

1. **Build the Docker image:**
   ```bash
   docker build -t courier-app .
   ```

2. **Run the container:**
   ```bash
   docker run -p 5000:5000 -v $(pwd)/instance:/app/instance -v $(pwd)/uploads:/app/uploads courier-app
   ```

## Features

- **Multi-stage build** for optimized image size
- **Persistent data** with Docker volumes for database and uploads
- **Health checks** to ensure container is running properly
- **Production-ready** configuration

## Environment Variables

The following environment variables can be customized:

- `FLASK_ENV` - Set to 'production' for production deployment
- `SECRET_KEY` - Change the Flask secret key for security

## Volumes

- `instance/` - Contains the SQLite database
- `uploads/` - Contains uploaded files (pricing CSV, etc.)

## Ports

- **5000** - Flask application port

## Production Deployment

For production deployment, consider:

1. Using a production WSGI server like Gunicorn
2. Setting up a reverse proxy (nginx)
3. Using environment variables for sensitive data
4. Setting up proper logging
5. Using a production database instead of SQLite

## Troubleshooting

1. **Container won't start:**
   - Check if port 5000 is already in use
   - Verify all dependencies are installed

2. **Database issues:**
   - Ensure the instance directory has proper permissions
   - Check database file exists in the container

3. **File upload issues:**
   - Verify uploads directory permissions
   - Check volume mounting

## Health Check

The container includes a health check that verifies the application is responding on port 5000.