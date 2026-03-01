# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for Playwright, Node.js, and Git
RUN apt-get update && apt-get install -y 
    curl 
    gnupg 
    git 
    libnss3 
    libnspr4 
    libatk1.0-0 
    libatk-bridge2.0-0 
    libcups2 
    libdrm2 
    libxkbcommon0 
    libxcomposite1 
    libxdamage1 
    libxext6 
    libxfixes3 
    libxrandr2 
    libgbm1 
    libasound2 
    libpango-1.0-0 
    libcairo2 
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - 
    && apt-get install -y nodejs 
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium)
RUN playwright install chromium --with-deps

# Copy the project files
COPY . .

# Install app dependencies (the React project)
# Note: We assume the 'app' directory exists and is a Vite project
RUN if [ -d "app" ]; then cd app && npm install; fi

# Expose the dashboard port
EXPOSE 8080

# Run the application
# We use a shell to ensure environment variables are loaded if needed
CMD ["python", "main.py"]
