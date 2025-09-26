# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory in container
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libmariadb-dev \
        libmariadb-dev-compat \
        pkg-config \
        && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Create instance directory for SQLite database
RUN mkdir -p instance

# Create uploads directory
RUN mkdir -p uploads

# Make sure uploads directory is writable
RUN chmod 755 uploads

# Initialize the database and create tables
RUN python -c "from main import app, db, create_tables; with app.app_context(): create_tables(); print('Database initialized successfully!')"

# Expose port 5000
EXPOSE 5000

# Set the command to run the application
CMD ["python", "main.py"]