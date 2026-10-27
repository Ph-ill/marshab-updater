#!/bin/sh
# Game core checks: compile the pack, unit tests, a simulated season with the
# determinism test, the JS renderer against the Python one, and (if a MicroPython
# unix port is available) the same season replayed under MicroPython; the ship-to-ship
# BLE sync on a fake radio, and the board's heap with the sync running (precompiled
# with mpy-cross when it is available, as on a board). The phone game's board server
# (board/lvweb.py + lvphone.py) is driven through the app's whole flow on CPython and
# MicroPython; with LV_FROZEN_MP (the game firmware as a unix port: tools/build_firmware.sh
# unix32) the frozen split is checked too, and the 80 KB heap gate with BLE sync and two
# phones playing at once. The LED notifier's schedule (tests/test_led.py) and the bench
# script (tools/bench.py, tests/test_bench.py: fake boards on the unix ports). The battery
# reader (board/lvbatt.py, tests/test_batt.py: a fake fuel gauge) on all of them, and its
# share of the heap (phone_heap.py ... --led --bat). Over-the-air updates (board/lvota.py,
# lvboot.py, lvsig.py; tests/test_ota.py) on all of them, and an upload's share of the heap
# (phone_heap.py ... --ota); signing and the release check (tests/test_ota_release.py);
# the phone page's update notice and screens (web/ota.js) clicked through against the mock
# (web/shots_ota.sh, needs playwright-core: PW=...).
#   MICROPYTHON=/path/to/micropython MPY_CROSS=/path/to/mpy-cross \
#   LV_FROZEN_MP=/path/to/micropython-lv32 [PW=/path/to/playwright-core] game/tests/run.sh
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
python3 tests/test_you_voice.py
node tests/render_check.mjs
python3 web/build.py
python3 tests/mock_check.py
python3 tests/test_phone.py
python3 tests/test_cal.py
python3 tests/test_led.py
python3 tests/test_batt.py
python3 tests/test_ota.py
python3 tests/test_ota_release.py
python3 tests/test_ships8.py
python3 tests/phone_check.py 9
python3 tests/phone_check.py 42
LV_FROZEN_MP="$LV_FROZEN_MP" MPY_CROSS="$MPY_CROSS" python3 tests/test_fw_split.py
MP="${MICROPYTHON:-$(command -v micropython || true)}"
if [ -n "$MP" ]; then
  "$MP" -X heapsize=160k tests/mp_check.py
  "$MP" tests/mp_codes.py
  "$MP" tests/test_led.py
  "$MP" tests/test_batt.py
  if [ -n "$LV_FROZEN_MP" ]; then "$LV_FROZEN_MP" tests/test_batt.py; fi
  "$MP" tests/test_ota.py
  if [ -n "$LV_FROZEN_MP" ]; then "$LV_FROZEN_MP" tests/test_ota.py; fi
  # every ship id boots with a launch date (ship 2, 2026-10-25)
  "$MP" -X heapsize=512k tests/test_ships8.py
  if [ -n "$LV_FROZEN_MP" ]; then "$LV_FROZEN_MP" -X heapsize=512k tests/test_ships8.py; fi
  "$MP" -X heapsize=160k tests/mp_engage.py
  "$MP" -X heapsize=192k tests/mp_merge.py
  # 3 boards in one process (a 64-bit port needs about 320k for this one).
  "$MP" -X heapsize=384k tests/mp_sync.py
  # The phone server's flow under MicroPython (the test's own buffers need the big heap;
  # the board's share is measured by phone_heap.py below).
  "$MP" -X heapsize=2m tests/phone_check.py 5
  "$MP" -X heapsize=2m tests/phone_check.py 42
  MPY_CROSS="${MPY_CROSS:-$(command -v mpy-cross || true)}"
  if [ -n "$MPY_CROSS" ]; then
    MPY_CROSS="$MPY_CROSS" sh tools/board_build.sh
    # Stock MicroPython (every module a file): sync + the bench status server (the phone
    # game is off there: it needs the game firmware).
    "$MP" -X heapsize=256k tests/mp_sync_heap.py build/board
    # ...with led_notify on: stays dark there (game firmware only: no heap for it).
    "$MP" -X heapsize=256k tests/mp_sync_heap.py build/board --led
    # The game firmware's frozen set, if a unix build of it is given (tools/build_firmware.sh unix32):
    # sync alone, then sync + two phones playing over real sockets.
    if [ -n "$LV_FROZEN_MP" ]; then
      "$LV_FROZEN_MP" -X heapsize=256k tests/mp_sync_heap.py frozen
      python3 tests/phone_heap.py "$LV_FROZEN_MP" frozen
      # ...and with the LED notifier on and blinking (board/lvled.py in the heap too).
      python3 tests/phone_heap.py "$LV_FROZEN_MP" frozen --led
      # ...and a UPS-Lite battery read while idle (board/lvbatt.py loaded and dropped each time).
      python3 tests/phone_heap.py "$LV_FROZEN_MP" frozen --led --bat
      # ...and a third phone uploading a signed update meanwhile (board/lvota.py, lvsig.py).
      MPY_CROSS="$MPY_CROSS" python3 tests/phone_heap.py "$LV_FROZEN_MP" frozen --led --bat --ota
    fi
    # tools/bench.py against fake boards: stock MicroPython (must refuse, naming the .uf2)
    # and, with LV_FROZEN_MP, the game firmware (install, settings, selftest, report).
    MICROPYTHON="$MP" LV_FROZEN_MP="$LV_FROZEN_MP" python3 tests/test_bench.py
  else
    echo "mpy-cross not found: heap measured from source (set MPY_CROSS=...)"
    "$MP" -X heapsize=256k tests/mp_sync_heap.py
  fi
else
  echo "micropython not found: skipped tests/mp_check.py (set MICROPYTHON=...)"
fi
# The real phone page in headless Chrome against the board's server code, on CPython and
# (if given) MicroPython: the game firmware's unix build when there is one.
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || true)}"
if [ -n "$CHROME" ] && command -v node > /dev/null; then
  CHROME="$CHROME" node --experimental-websocket tests/app_e2e.mjs 9
  BPY="${LV_FROZEN_MP:-$MP}"
  if [ -n "$BPY" ]; then
    CHROME="$CHROME" BOARD_PY="$BPY -X heapsize=1m" node --experimental-websocket tests/app_e2e.mjs 9
  fi
  if [ -n "$PW" ]; then
    O="$(mktemp -d)"; PW="$PW" CHROME="$CHROME" sh web/shots_ota.sh "$O/ota"; rm -rf "$O"
  else
    echo "playwright-core not given: skipped web/shots_ota.sh (set PW=...)"
  fi
else
  echo "chrome or node not found: skipped tests/app_e2e.mjs (set CHROME=...)"
fi
