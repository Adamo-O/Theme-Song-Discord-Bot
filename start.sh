#!/bin/bash

# POT (Proof of Origin Token) provider. yt-dlp needs a PO token to keep YouTube's bot
# detection from stripping the audio formats out of the player response.
#
# In production POT_PROVIDER_URL points at a separate Railway service, so there is
# nothing to start here. The server built into /opt/bgutil-pot by the Dockerfile is a
# fallback for when no external provider is configured - it is only launched when
# POT_PROVIDER_URL is unset or points at this container, otherwise it would just be an
# idle Node process nobody connects to.
#
# Note the bgutil pip package ships the yt-dlp *plugin* only; it has no runnable module,
# which is why the server is a separate build.
POT_SERVER=${POT_SERVER:-/opt/bgutil-pot/server/build/main.js}
POT_PORT=${POT_PORT:-4416}

# Host out of POT_PROVIDER_URL: strip the scheme, then the path, keeping any port
pot_target=${POT_PROVIDER_URL#*://}
pot_target=${pot_target%%/*}
case "$pot_target" in
    ''|localhost*|127.0.0.1*|'[::1]'*) pot_is_local=1 ;;
    *) pot_is_local=0 ;;
esac

if [ "$pot_is_local" -eq 0 ]; then
    echo "POT provider configured at $pot_target - not starting a local one"
elif [ ! -f "$POT_SERVER" ]; then
    echo "ERROR: no external POT provider configured and no local server at $POT_SERVER"
    echo "       yt-dlp will run without PO tokens; expect some videos to fail"
    echo "       with 'Requested format is not available'."
else
    echo "No external POT provider configured, starting local server on port $POT_PORT..."
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

# The bot pings POT_PROVIDER_URL itself at startup and logs whether it is reachable,
# which covers the external provider case as well.
echo "Starting Discord bot..."
python app.py
