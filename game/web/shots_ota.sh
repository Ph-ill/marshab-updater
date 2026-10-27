#!/bin/sh
# Over-the-air update screens (web/shots_ota.mjs), light, story text replaced; also a click-through test.
#   PW=... CHROME=... game/web/shots_ota.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
python3 sim/mockserver.py --port 8056 codes=1234,1234,1234,1234,1234,1234 ota=0.2.0 >/dev/null 2>&1 & A=$!
python3 sim/mockserver.py --port 8057 codes=1234,1234,1234,1234,1234,1234 ota=0.2.0,back >/dev/null 2>&1 & B=$!
trap 'kill $A $B 2>/dev/null' EXIT
sleep 2
node web/shots_ota.mjs "$OUT"
