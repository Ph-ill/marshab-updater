#!/bin/sh
# Game core checks: compile the pack, unit tests, a simulated season with the
# determinism test, the JS renderer against the Python one, and (if a MicroPython
# unix port is available) the same season replayed under MicroPython.
#   MICROPYTHON=/path/to/micropython game/tests/run.sh
set -e
cd "$(dirname "$0")/.."
python3 tools/lvc.py
python3 tests/test_core.py
python3 sim/season.py > /dev/null
python3 - <<'PY'
import json, sys
d = json.load(open("sim/out/stats.json"))["determinism"]
bad = [k for k, v in d.items() if not v["all_7_match"]]
print("determinism:", "FAIL " + ", ".join(bad) if bad else "all 7 ships match in " + ", ".join(d))
sys.exit(1 if bad else 0)
PY
node tests/render_check.mjs
python3 web/build.py
MP="${MICROPYTHON:-$(command -v micropython || true)}"
if [ -n "$MP" ]; then
  "$MP" -X heapsize=160k tests/mp_check.py
else
  echo "micropython not found: skipped tests/mp_check.py (set MICROPYTHON=...)"
fi
