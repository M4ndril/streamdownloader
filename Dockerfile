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
COPY twitch_recorder.py .
COPY monitor_service.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY .streamlit .streamlit

# Expose Streamlit port
EXPOSE 8501

# Run supervisor (which runs streamlit and the monitor service)
CMD ["/usr/bin/supervisord"]
