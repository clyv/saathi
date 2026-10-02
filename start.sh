#!/usr/bin/env bash
# Saathi launcher for Linux and macOS.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "First run: creating a Python environment and installing Saathi..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  echo "Now downloading the AI models (needs internet, one time only)..."
  .venv/bin/python scripts/setup.py || true
fi

URL="http://127.0.0.1:8765/"
.venv/bin/python server.py &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 3

# Open as an app window if Chrome/Chromium is available, else the default browser.
for b in google-chrome chromium chromium-browser microsoft-edge; do
  if command -v "$b" >/dev/null 2>&1; then "$b" --app="$URL" >/dev/null 2>&1 & OPENED=1; break; fi
done
if [ -z "$OPENED" ]; then
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; else open "$URL"; fi
fi
wait $SERVER
