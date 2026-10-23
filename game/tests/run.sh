#!/bin/sh
# Game core checks: compile the pack, unit tests, a simulated season with the
# determinism test, the JS renderer against the Python one, and (if a MicroPython
# unix port is available) the same season replayed under MicroPython; the ship-to-ship
# BLE sync on a fake radio, and the board's heap with the sync running (precompiled
# with mpy-cross when it is available, as on a board).
#   MICROPYTHON=/path/to/micropython MPY_CROSS=/path/to/mpy-cross game/tests/run.sh
set -e
cd "$(dirname "$0")/.."
python3 tools/lvc.py
python3 tools/lve.py
python3 tests/test_core.py
python3 tests/test_content.py
python3 tests/mp_codes.py
python3 sim/season.py > /dev/null
python3 - <<'PY'
import json, sys
d = json.load(open("sim/out/stats.json"))["determinism"]
bad = [k for k, v in d.items() if not v["all_ships_match"]]
print("determinism:", "FAIL " + ", ".join(bad) if bad else "all 8 ships match in " + ", ".join(d))
sys.exit(1 if bad else 0)
PY
python3 tests/test_engage.py
python3 tests/mp_engage.py --write > /dev/null
python3 tests/test_sync.py
python3 tests/mp_sync.py
node tests/render_check.mjs
python3 web/build.py
python3 tests/mock_check.py
MP="${MICROPYTHON:-$(command -v micropython || true)}"
if [ -n "$MP" ]; then
  "$MP" -X heapsize=160k tests/mp_check.py
  "$MP" tests/mp_codes.py
  "$MP" -X heapsize=160k tests/mp_engage.py
  "$MP" -X heapsize=192k tests/mp_merge.py
  # 3 boards in one process (a 64-bit port needs about 320k for this one).
  "$MP" -X heapsize=384k tests/mp_sync.py
  MPY_CROSS="${MPY_CROSS:-$(command -v mpy-cross || true)}"
  if [ -n "$MPY_CROSS" ]; then
    MPY_CROSS="$MPY_CROSS" sh tools/board_build.sh
    "$MP" -X heapsize=256k tests/mp_sync_heap.py build/board
    # The game firmware's frozen set, if a unix build of it is given (tools/build_firmware.sh unix32).
    if [ -n "$LV_FROZEN_MP" ]; then
      "$LV_FROZEN_MP" -X heapsize=256k tests/mp_sync_heap.py frozen
    fi
  else
    echo "mpy-cross not found: heap measured from source (set MPY_CROSS=...)"
    "$MP" -X heapsize=256k tests/mp_sync_heap.py
  fi
else
  echo "micropython not found: skipped tests/mp_check.py (set MICROPYTHON=...)"
fi
