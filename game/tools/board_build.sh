#!/bin/sh
# Build the board's files for a Pico W / Pico 2 W and (optionally) copy them over.
#
#   sh tools/board_build.sh               build build/board/ and build/board-fw/ only
#   sh tools/board_build.sh PORT          build, then copy build/board/ to the board on PORT
#   LAYOUT=fw sh tools/board_build.sh PORT   copy build/board-fw/ instead (game firmware)
#                                         (PORT: /dev/ttyACM0, COM5, ... or "auto")
#
#   build/board/     stock MicroPython 1.29 (Variant A): everything as files, the game
#                    core lv/*.mpy too: main.py, the board modules (tools/fw/gen_lvfrozen.py
#                    BOARD: lvship, lvreport, lvcal, lvled, lvledcfg, lvbatt, lvdays, lvweb,
#                    lvphone, lvstat, lvwifi, selftest), the pack, engage.bin, www/*.gz.
#   build/board-fw/  the game firmware (tools/build_firmware.sh): only what the flashed
#                    core doesn't already have frozen in, i.e. what a release on it ships:
#                    main.py, boot.py, engage.bin and the phone page www/*.gz always; a board module
#                    as <name>.mpy and the pack as pack.bin only if they changed since that
#                    core (lv-core 0.1.0 froze neither: then all of them); a changed core
#                    module as lvx/<name>.mpy (lv/__init__.py). Files are found before the
#                    frozen modules on the board, so each one replaces its frozen copy.
#                    Never put lv/ on a game-firmware board: it hides the frozen core.
#                    FROZEN_CORE=tools/fw/cores/lv-core-<ver>-<core>.json says which core
#                    (what the flashed .uf2 froze, written by tools/build_firmware.sh).
#                    Default: the newest core in tools/fw/cores/.
#
# Needs python3, mpy-cross 1.29 (pip install mpy-cross==1.29.0, or MPY_CROSS=/path) and,
# to copy, mpremote (pip install mpremote). Every module is precompiled to .mpy: nothing
# is compiled on the board, which is what keeps the heap low (docs/BENCH_TEST.md).
# The board's own settings (/data/ship.json, /data/crew.json) are never touched.
# The board modules are compiled with -O3 (MPY_OPT to change it): no line numbers in their
# bytecode, about 1 KB less heap with the game loaded; a traceback from them names the
# function but shows line 1 (build with MPY_OPT= to get line numbers back when debugging).
# The board code has no asserts, so -O3 changes nothing else. The core lv/ keeps its lines.
set -e
cd "$(dirname "$0")/.."
MPY_CROSS="${MPY_CROSS:-mpy-cross}"
MPREMOTE="${MPREMOTE:-mpremote}"
MPY_OPT="${MPY_OPT--O3}"
OUT=build/board
FW=build/board-fw
GLUE=$(python3 tools/fw/gen_lvfrozen.py --print-board)

python3 tools/lvc.py > /dev/null
python3 tools/lve.py > /dev/null
python3 web/build.py > /dev/null
rm -rf "$OUT" "$FW"
mkdir -p "$OUT/lv" "$OUT/www" "$FW/www"
for f in lv/*.py; do
  "$MPY_CROSS" -o "$OUT/lv/$(basename "$f" .py).mpy" "$f"
done
for f in $GLUE; do
  "$MPY_CROSS" $MPY_OPT -o "$OUT/$f.mpy" "board/$f.py"
done
cp board/main.py "$OUT/main.py"      # the boot files stay .py (they are tiny)
cp board/boot.py "$OUT/boot.py"
cp build/pack.bin build/engage.bin "$OUT/"
cp build/app.html.gz build/text.json.gz build/engage.json.gz build/app.webmanifest.gz build/icon.png.gz "$OUT/www/"
# The game firmware's set: what the frozen core the boards run doesn't have as it is now.
FROZEN_CORE="${FROZEN_CORE:-$(ls tools/fw/cores/lv-core-*.json 2>/dev/null | sort -V | tail -1)}"
cp "$OUT/main.py" "$OUT/boot.py" "$OUT/engage.bin" "$FW/"
cp "$OUT"/www/*.gz "$FW/www/"
mkdir -p "$OUT/www/ls" "$FW/www/ls"     # the iOS launch screens (web/launch.py)
cp web/launch/*.png "$OUT/www/ls/"
cp web/launch/*.png "$FW/www/ls/"
LVX=""
if [ -n "$FROZEN_CORE" ]; then
  LVX=$(python3 tools/fw/changed_modules.py "$FROZEN_CORE")
  TOP=$(python3 tools/fw/changed_modules.py --files "$FROZEN_CORE")
  mkdir -p "$FW/lvx"
  for m in $LVX; do
    "$MPY_CROSS" -o "$FW/lvx/$m.mpy" "lv/$m.py"
  done
  rmdir "$FW/lvx" 2>/dev/null || true
  for f in $TOP; do
    cp "$OUT/$f" "$FW/$f"
  done
  cp "$FROZEN_CORE" build/frozen-core.json
  echo "frozen core $(basename "$FROZEN_CORE"): overrides for [${LVX}], files for [${TOP}]"
else
  for f in $GLUE; do cp "$OUT/$f.mpy" "$FW/"; done
  cp "$OUT/pack.bin" "$FW/"
fi
fwtotal=$(find "$FW" -type f -exec cat {} + | wc -c)
total=$(find "$OUT" -type f -exec cat {} + | wc -c)
# optional preload for the bulk test (not copied): only when the season sim has made one,
# so a clean export (no build/season_log.bin yet) still builds (0.3.0 review R3 m6)
if [ -f build/season_log.bin ]; then
  cp build/season_log.bin "$OUT/season_log.bin"
  python3 -c "
import sys; sys.path.insert(0, '.')
from lv.chlog import ChoiceLog
from lv import record as R
raw = open('build/season_log.bin', 'rb').read()
log = ChoiceLog(b'test-fleet-key-not-secret')
for i in range(0, len(raw), R.LEN):
    log.merge(raw[i:i + R.LEN])
print('bulk test preload: build/board/season_log.bin, %d records, digest %s' % (len(log), log.digest().hex()))
"
else
  echo "bulk test preload: skipped (no build/season_log.bin: run sim/season.py first)"
fi
echo "built $OUT (stock MicroPython): $(ls "$OUT"/lv | wc -l) lv modules + $GLUE, main.py, pack, engage.bin, www/ = $total bytes of flash"
echo "built $FW (game firmware): $(cd "$FW" && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ')= $fwtotal bytes of flash"

[ -z "$1" ] && exit 0
if [ "$1" = auto ]; then C=""; else C="connect $1"; fi
SRC="$OUT"
[ "$LAYOUT" = fw ] && SRC="$FW"
# Stop whatever is running, clear old copies (a .py next to a .mpy would win; a /lv next to
# the game firmware hides its frozen core; a board module or pack.bin the game firmware has
# frozen in would replace the frozen one; an over-the-air update in progress, /ota, would
# be swapped in or rolled back over these at the next boot), copy, reset. /data is never touched.
$MPREMOTE $C exec "
import os
def rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rm(p + '/' + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass
for p in ['/lv', '/lvx', '/www', '/pack.bin', '/ota'] + ['/%s.%s' % (m, e) for m in '$GLUE'.split() for e in ('py', 'mpy')]:
    rm(p)
for d in ('/data', '/www'$( [ "$SRC" = "$OUT" ] && echo ", '/lv'")):
    try:
        os.mkdir(d)
    except OSError:
        pass
"
[ "$SRC" = "$OUT" ] && $MPREMOTE $C cp "$OUT"/lv/*.mpy :lv/
$MPREMOTE $C cp "$SRC"/www/*.gz :www/
$MPREMOTE $C cp $(ls "$SRC"/*.mpy "$SRC"/pack.bin 2>/dev/null) "$SRC"/engage.bin "$SRC"/boot.py "$SRC"/main.py :
if [ -d "$SRC/lvx" ]; then
  $MPREMOTE $C mkdir :lvx || true
  $MPREMOTE $C cp "$SRC"/lvx/*.mpy :lvx/
fi
$MPREMOTE $C exec "import os, gc; s = os.statvfs('/'); gc.collect(); print('board: flash free %d KB, heap free %d B' % (s[0] * s[3] // 1024, gc.mem_free()))"
echo "copied $SRC to ${1}. Reset the board (mpremote $C reset) to start main.py."
