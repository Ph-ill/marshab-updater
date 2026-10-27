#!/bin/sh
# The home-screen card and screen (web/shots_a2hs.mjs), light, story text replaced; also a click-through test.
#   PW=... CHROME=... game/web/shots_a2hs.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
python3 sim/mockserver.py --port 8058 codes=1234,1234,1234,1234,1234,1234 >/dev/null 2>&1 & A=$!
trap 'kill $A 2>/dev/null' EXIT
sleep 2
node web/shots_a2hs.mjs "$OUT"
