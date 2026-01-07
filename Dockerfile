FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# ffmpeg is required for streamlink to mux streams
# git might be needed for some plugins or versioningit
# supervisor is needed to run multiple processes
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# Copy application code
COPY server.py .
COPY run_app.py .
COPY monitor_service.py .
COPY settings_manager.py .
COPY uploader_service.py .
COPY static static
COPY templates templates

# Create directory for data
RUN mkdir -p static

# Expose FastAPI port
EXPOSE 8501

# Run the unified application runner
CMD ["python", "run_app.py"]
