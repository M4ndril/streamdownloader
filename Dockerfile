FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# ffmpeg is required for streamlink to mux streams
# git might be needed for some plugins or versioningit
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY twitch_recorder.py .
# Note: We do NOT copy the 'data' folder, as it should be a volume

# Expose Streamlit port
EXPOSE 8501

# Run the application
CMD ["streamlit", "run", "twitch_recorder.py", "--server.port=8501", "--server.address=0.0.0.0"]
