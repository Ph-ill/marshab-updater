#!/bin/sh
# Playwright review at 375/320 px, light/dark, using real board handlers.
set -eu
cd "$(dirname "$0")/.."
OUT="${1:?screenshot output directory required}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
python3 tools/lvc.py >/dev/null
python3 tools/lve.py >/dev/null
python3 web/build.py >/dev/null
P="${DUEL_TEST_PORT:-8091}"
python3 -u tests/phone_serve.py --duel 9 "$P" >"$OUT/board.log" 2>&1 & A=$!
trap 'kill "$A" 2>/dev/null || true' EXIT
# The browser waits for readiness; a failed board process is not a passing screenshot run.
python3 -c 'import sys,time,urllib.request
for _ in range(100):
 try:
  urllib.request.urlopen("http://localhost:"+sys.argv[1]+"/");break
 except OSError: time.sleep(.1)
else: raise SystemExit("fake board did not start")' "$P"
node web/shots_duel.mjs "$P" "$OUT"
