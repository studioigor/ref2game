#!/usr/bin/env bash
# serve.sh [port] — serve the project root over http for the live preview (WebGL can't load file:// images).
# Picks the first free port from 8930 up (or the given one) and prints the live URL. Run it in the background.
P="${1:-8930}"
while lsof -iTCP:"$P" -sTCP:LISTEN >/dev/null 2>&1; do P=$((P+1)); done
echo "LIVE: http://127.0.0.1:$P/live/index.html"
exec python3 -m http.server "$P" --bind 127.0.0.1
