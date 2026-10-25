#!/bin/sh
# The first-run screenshots (web/shots_onboard.mjs), light and dark: one fresh mock each.
#   game/web/shots_onboard.sh OUTDIR       (needs PW and CHROME, as in shots.mjs)
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 web/build.py
PIDS=""
for p in 8052 8053; do
  python3 sim/mockserver.py --port $p codes=1234,1234,1234,1234,1234,1234, >/dev/null 2>&1 & PIDS="$PIDS $!"
done
trap 'kill $PIDS 2>/dev/null' EXIT
sleep 2
node web/shots_onboard.mjs "$OUT"
