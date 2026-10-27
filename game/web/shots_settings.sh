#!/bin/sh
# Settings (web/settings.js): the gear, every section, Change your code, Reset this ship; light, story text
# replaced; also a click-through test against the mock (sim/mockserver.py /api/reset, /api/code).
#   PW=... CHROME=... game/web/shots_settings.sh OUTDIR
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
python3 tools/lve.py >/dev/null
python3 web/build.py
python3 sim/mockserver.py --port 8059 codes=1234,1234,1234,1234,1234,1234 ota=0.2.0 bat=72,3950,1 >/dev/null 2>&1 & A=$!
python3 sim/mockserver.py --port 8060 codes=1234,1234,1234,1234,1234,1234 >/dev/null 2>&1 & B=$!
trap 'kill $A $B 2>/dev/null' EXIT
sleep 2
node web/shots_settings.mjs "$OUT"
