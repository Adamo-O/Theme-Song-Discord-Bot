FROM python:3.12-slim

# Install system dependencies (build deps for PyNaCl, plus the runtime libs the
# POT provider server's prebuilt `canvas` native module links against)
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
    git \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libjpeg62-turbo \
    libgif7 \
    librsvg2-2 \
    libpixman-1-0 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (yt-dlp's EJS n-challenge solver requires Node >= 22.0.0;
# Debian's apt nodejs is 18.x, which silently fails to solve the challenge and
# leaves only image formats available). NodeSource ships a supported build.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Plugin and server must be the same version
ARG POT_PROVIDER_VERSION=1.3.2

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the yt-dlp POT provider plugin (client side). pip drops it into
# site-packages/yt_dlp_plugins, which yt-dlp picks up automatically.
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider==${POT_PROVIDER_VERSION}

# Build the POT provider HTTP server (server side), as a fallback for when no
# external provider is configured. The pip package above is ONLY the plugin - it
# contains no runnable module, so the server has to be built from the repo.
# Production sets POT_PROVIDER_URL to a separate service and start.sh leaves this
# one alone; it is only launched when POT_PROVIDER_URL is unset or local. Keep
# POT_PROVIDER_VERSION in step with whatever that external service runs, or the
# plugin logs a version-mismatch warning on every extraction.
RUN git clone --single-branch --depth 1 --branch ${POT_PROVIDER_VERSION} \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-pot && \
    cd /opt/bgutil-pot/server && \
    npm ci && npx tsc && npm prune --omit=dev && \
    npm cache clean --force && \
    rm -rf /opt/bgutil-pot/.git && \
    test -f /opt/bgutil-pot/server/build/main.js

# Copy application code
COPY . .

# Run the POT server and bot together
CMD ["bash", "start.sh"]
