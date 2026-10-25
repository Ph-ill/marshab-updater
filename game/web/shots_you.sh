#!/bin/sh
# Second-person UI screenshots (web/shots_you.mjs), light, story text replaced.
#   PW=... CHROME=... game/web/shots_you.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
python3 sim/mockserver.py --port 8054 codes=1234,1234,1234,1234,1234,1234, >/dev/null 2>&1 & A=$!
python3 sim/mockserver.py --port 8055 >/dev/null 2>&1 & B=$!
trap 'kill $A $B 2>/dev/null' EXIT
sleep 2
node web/shots_you.mjs "$OUT"
