#!/bin/sh
# Engagement screenshots (390x844): build the page, start a mock Pico on 8048, shoot, stop it.
#   PW=... CHROME=... game/web/shots_engage.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
python3 sim/mockserver.py --port 8048 >/dev/null 2>&1 & PID=$!
trap 'kill $PID 2>/dev/null' EXIT
sleep 2
PORT=8048 node web/shots_engage.mjs "$OUT"
