#!/bin/sh
# The home-screen funnel (web/shots_funnel.mjs) against the board's own server code
# (tests/phone_serve.py), light and dark, story text replaced; also a click-through test.
#   PW=... CHROME=... game/web/shots_funnel.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
PORT=8059
python3 tests/phone_serve.py 9 $PORT > "$OUT/.server.log" 2>&1 & A=$!
trap 'kill $A 2>/dev/null; rm -f "$OUT/.server.log"' EXIT
for i in $(seq 1 100); do grep -q READY "$OUT/.server.log" 2>/dev/null && break; sleep 0.2; done
PORT=$PORT node web/shots_funnel.mjs "$OUT"
