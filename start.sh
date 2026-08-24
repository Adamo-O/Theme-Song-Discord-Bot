#!/bin/bash

# Start the POT (Proof of Origin Token) HTTP server in the background.
# yt-dlp needs a PO token to keep YouTube's bot detection from stripping the
# audio formats out of the player response. The bgutil pip package only ships
# the yt-dlp *plugin*; the server itself is the Node app built into
# /opt/bgutil-pot by the Dockerfile.
POT_SERVER=${POT_SERVER:-/opt/bgutil-pot/server/build/main.js}
POT_PORT=${POT_PORT:-4416}

if [ ! -f "$POT_SERVER" ]; then
    echo "ERROR: POT provider server not found at $POT_SERVER"
    echo "       yt-dlp will run without PO tokens; expect some videos to fail"
    echo "       with 'Requested format is not available'."
else
    echo "Starting POT provider server on port $POT_PORT..."
    node "$POT_SERVER" --port "$POT_PORT" &
    POT_PID=$!

    # Poll the health endpoint rather than just checking the process is alive -
    # a process that started but can't serve requests is the same as no server.
    for _ in $(seq 1 30); do
        if curl -sf -m 2 "http://127.0.0.1:$POT_PORT/ping" > /dev/null; then
            echo "POT provider server ready (PID: $POT_PID): $(curl -sf -m 2 http://127.0.0.1:$POT_PORT/ping)"
            break
        fi
        if ! kill -0 $POT_PID 2>/dev/null; then
            echo "ERROR: POT provider server exited before becoming ready"
            break
        fi
        sleep 1
    done

    if ! curl -sf -m 2 "http://127.0.0.1:$POT_PORT/ping" > /dev/null; then
        echo "WARNING: POT provider server did not respond on port $POT_PORT"
    fi
fi

# Start the Discord bot
echo "Starting Discord bot..."
python app.py
