#!/bin/bash

# Start the POT (Proof of Origin Token) HTTP server in the background
# This is required for yt-dlp to bypass YouTube's bot detection with the web client
echo "Starting POT provider server on port 4416..."
python -m bgutil_ytdlp_pot_provider --port 4416 &
POT_PID=$!

# Give the POT server a moment to start
sleep 2

# Verify POT server is running
if kill -0 $POT_PID 2>/dev/null; then
    echo "POT provider server started (PID: $POT_PID)"
else
    echo "WARNING: POT provider server failed to start"
fi

# Start the Discord bot
echo "Starting Discord bot..."
python app.py
