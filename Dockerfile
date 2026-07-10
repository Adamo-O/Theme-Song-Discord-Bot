FROM python:3.12-slim

# Install system dependencies (including build deps for PyNaCl)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libopus-dev \
    libffi-dev \
    libsodium-dev \
    python3-dev \
    gcc \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (yt-dlp's EJS n-challenge solver requires Node >= 22.0.0;
# Debian's apt nodejs is 18.x, which silently fails to solve the challenge and
# leaves only image formats available). NodeSource ships a supported build.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
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

# Run the POT server and bot together
CMD ["bash", "start.sh"]
