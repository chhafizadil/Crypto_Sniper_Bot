# Dockerfile for Crypto Signal Bot on GCP Cloud Run
# Purpose: Builds a Docker image to run the bot on Cloud Run
# Uses Python 3.12 slim image for lightweight container
# Exposes port 8080 for Cloud Run compatibility

FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Copy all project files to the container
COPY . .

# Install dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 8080 (Cloud Run default)
EXPOSE 8000

# Command to run the bot
CMD ["python", "main.py"]
