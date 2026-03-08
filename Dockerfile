FROM python:3.12-slim

# Install system dependencies (including build deps for PyNaCl)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libffi-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp POT provider plugin
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# Copy application code
COPY . .

# Run the bot
CMD ["python", "app.py"]
