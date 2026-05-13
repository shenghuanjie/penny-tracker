#!/bin/bash
# Launch Chrome with remote debugging enabled using your profile.
# Uses a separate debug data dir with symlink to your real profile
# (Chrome refuses --remote-debugging-port with the default data dir).

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR="/Users/shengh4/Library/Application Support/Google/Chrome"
DEBUG_DATA_DIR="/Users/shengh4/Library/Application Support/Google/Chrome-Debug"
PROFILE_DIR="Profile 1"
PORT=9222

# Check if Chrome is already listening on the debug port
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Chrome is already running with remote debugging on port $PORT."
    exit 0
fi

# Set up debug data dir with symlink to real profile
mkdir -p "$DEBUG_DATA_DIR"
if [ -f "$USER_DATA_DIR/Local State" ] && [ ! -f "$DEBUG_DATA_DIR/Local State" ]; then
    cp "$USER_DATA_DIR/Local State" "$DEBUG_DATA_DIR/Local State"
fi
if [ -d "$USER_DATA_DIR/$PROFILE_DIR" ] && [ ! -e "$DEBUG_DATA_DIR/$PROFILE_DIR" ]; then
    ln -s "$USER_DATA_DIR/$PROFILE_DIR" "$DEBUG_DATA_DIR/$PROFILE_DIR"
fi

echo "Launching Chrome with remote debugging on port $PORT..."
"$CHROME" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$DEBUG_DATA_DIR" \
    --profile-directory="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check &

echo "Chrome launched (PID: $!). Scripts can now connect to localhost:$PORT."
