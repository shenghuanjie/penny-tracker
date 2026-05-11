#!/bin/bash
# Launch Chrome with remote debugging enabled using your profile.
# Usage: ./launch_chrome.sh
#   or:  source launch_chrome.sh  (to keep it in the same terminal)

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR="/Users/shengh4/Library/Application Support/Google/Chrome"
PROFILE_DIR="Profile 1"
PORT=9222

# Check if Chrome is already listening on the debug port
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Chrome is already running with remote debugging on port $PORT."
    exit 0
fi

echo "Launching Chrome with remote debugging on port $PORT..."
"$CHROME" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$USER_DATA_DIR" \
    --profile-directory="$PROFILE_DIR" &

echo "Chrome launched (PID: $!). Scripts can now connect to localhost:$PORT."
