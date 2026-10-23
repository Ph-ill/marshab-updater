#!/bin/sh
# Build the page, start one mock Pico per viewport (each needs a fresh, unclaimed ship) plus
# one with seat 0 pre-claimed, take every screenshot, stop the mocks.
#   game/web/shots.sh OUTDIR           # 390x844 and 360x800
#   SIZES=cna game/web/shots.sh OUTDIR # the captive-sheet viewports, OUTDIR/cna-WxH/
# Needs PW (playwright-core dir) and CHROME, as in shots.mjs.
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 web/build.py
PIDS=""
python3 sim/mockserver.py --port 8042 codes=1234,1234,1234,1234,1234,1234, >/dev/null 2>&1 & PIDS="$PIDS $!"
for p in 8043 8044 8045 8046 8047; do
  python3 sim/mockserver.py --port $p codes=1234,1234,1234,1234,1234,1234, >/dev/null 2>&1 & PIDS="$PIDS $!"
done
trap 'kill $PIDS 2>/dev/null' EXIT
sleep 2
node web/shots.mjs "$OUT"
