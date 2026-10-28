#!/bin/sh
# 0.2.7 / 0.3.x screens (web/shots_v03.mjs) against the board's server code (tests/phone_serve.py):
# safe mode (board/lvsafe.py, web/safe.js); later scenarios are added as they land.
#   PW=... CHROME=... game/web/shots_v03.sh OUTDIR [scenario...]
set -e
cd "$(dirname "$0")/.."
OUT="$(cd "$(dirname "${1:-shots}")" && pwd)/$(basename "${1:-shots}")"
mkdir -p "$OUT"
shift || true
SC="${*:-safe}"
python3 tools/lve.py >/dev/null
python3 web/build.py >/dev/null
[ -f build/e2e-root/pack.bin ] || sh tools/board_build.sh >/dev/null
P=8091
for s in $SC; do
  F=""; [ "$s" = safe ] && F="--safe"; [ "$s" != safe ] && F="--live"
  python3 tests/phone_serve.py $F 9 $P >/dev/null 2>&1 & A=$!
  trap 'kill $A 2>/dev/null' EXIT
  sleep 2
  node web/shots_v03.mjs "$s" $P "$OUT"
  kill $A 2>/dev/null || true
  P=$((P+1))
done
