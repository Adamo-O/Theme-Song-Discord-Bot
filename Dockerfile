FROM python:3.12-slim

# Install system dependencies (including build deps for PyNaCl)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libffi-dev \
    python3-dev \
    gcc \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp POT provider plugin
# Use pip for Python path registration + manual install for yt-dlp plugin directory
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider && \
    mkdir -p /root/.yt-dlp/plugins && \
    curl -sL https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/latest/download/bgutil-ytdlp-pot-provider.zip \
    -o /tmp/pot-plugin.zip && \
    unzip /tmp/pot-plugin.zip -d /root/.yt-dlp/plugins/ && \
    rm /tmp/pot-plugin.zip && \
    echo "Installed POT plugin to:" && ls -la /root/.yt-dlp/plugins/

# Copy application code
COPY . .

# Run the bot
CMD ["python", "app.py"]
