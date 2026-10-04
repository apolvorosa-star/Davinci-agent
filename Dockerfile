# Dockerfile for Davinci-Agent
# -------------------------------------------------
# Use official slim Python image
FROM python:3.11-slim

# Install build dependencies (optional, depends on packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependencies first for cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port (adjust if you run a server)
EXPOSE 8000

# Default command (adapt if your app entrypoint is elsewhere)
CMD ["python", "-m", "src.main"]
