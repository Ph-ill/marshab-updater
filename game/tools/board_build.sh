#!/bin/sh
# Build the board's files for a Pico W / Pico 2 W and (optionally) copy them over.
#
#   sh tools/board_build.sh               build build/board/ and build/board-fw/ only
#   sh tools/board_build.sh PORT          build, then copy build/board/ to the board on PORT
#   LAYOUT=fw sh tools/board_build.sh PORT   copy build/board-fw/ instead (game firmware)
#                                         (PORT: /dev/ttyACM0, COM5, ... or "auto")
#
#   build/board/     stock MicroPython 1.29 (Variant A): the game core lv/*.mpy too
#   build/board-fw/  the game firmware (tools/build_firmware.sh, the core lv/ frozen in):
#                    only what stays updatable: main.py, the glue (lvship, lvcal, lvled, lvledcfg, lvdays, lvweb, lvphone, lvstat,
#                    lvwifi, selftest), the pack, engage.bin and the phone page www/*.gz.
#                    Never put lv/ on a game-firmware board: it hides the frozen core. A
#                    fixed core module goes in lvx/<name>.mpy instead (lv/__init__.py):
#                    FROZEN_CORE=tools/fw/cores/lv-core-<ver>-<core>.json (what the flashed
#                    .uf2 froze, written by tools/build_firmware.sh) puts every lv module
#                    that changed since that core into build/board-fw/lvx/, and only those.
#                    Default: the newest core in tools/fw/cores/.
#
# Needs python3, mpy-cross 1.29 (pip install mpy-cross==1.29.0, or MPY_CROSS=/path) and,
# to copy, mpremote (pip install mpremote). Every module is precompiled to .mpy: nothing
# is compiled on the board, which is what keeps the heap low (docs/BENCH_TEST.md).
# The board's own settings (/data/ship.json, /data/crew.json) are never touched.
set -e
cd "$(dirname "$0")/.."
MPY_CROSS="${MPY_CROSS:-mpy-cross}"
MPREMOTE="${MPREMOTE:-mpremote}"
OUT=build/board
FW=build/board-fw
GLUE="lvship lvcal lvled lvledcfg lvdays lvweb lvphone lvstat lvwifi selftest"

python3 tools/lvc.py > /dev/null
python3 tools/lve.py > /dev/null
python3 web/build.py > /dev/null
rm -rf "$OUT" "$FW"
mkdir -p "$OUT/lv" "$FW/www"
for f in lv/*.py; do
  "$MPY_CROSS" -o "$OUT/lv/$(basename "$f" .py).mpy" "$f"
done
for f in $GLUE; do
  "$MPY_CROSS" -o "$FW/$f.mpy" "board/$f.py"
done
cp board/main.py "$FW/main.py"       # the boot file stays .py (it is tiny)
# Core modules changed since the frozen core the boards run: ship only those, as overrides.
FROZEN_CORE="${FROZEN_CORE:-$(ls tools/fw/cores/lv-core-*.json 2>/dev/null | sort -V | tail -1)}"
LVX=""
if [ -n "$FROZEN_CORE" ]; then
  LVX=$(python3 tools/fw/changed_modules.py "$FROZEN_CORE")
  mkdir -p "$FW/lvx"
  for m in $LVX; do
    "$MPY_CROSS" -o "$FW/lvx/$m.mpy" "lv/$m.py"
  done
  rmdir "$FW/lvx" 2>/dev/null || true
  cp "$FROZEN_CORE" build/frozen-core.json
  echo "frozen core $(basename "$FROZEN_CORE"): overrides for [${LVX}]"
fi
cp build/pack.bin build/engage.bin "$FW/"
cp build/app.html.gz build/text.json.gz build/engage.json.gz "$FW/www/"
cp -r "$FW"/. "$OUT"/
rm -rf "$OUT/lvx"                    # stock MicroPython has the whole lv/ as files
fwtotal=$(find "$FW" -type f -exec cat {} + | wc -c)
total=$(find "$OUT" -type f -exec cat {} + | wc -c)
cp build/season_log.bin "$OUT/season_log.bin"   # optional preload for the bulk test (not copied)
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
echo "built $OUT (stock MicroPython): $(ls "$OUT"/lv | wc -l) lv modules + $GLUE, main.py, pack, engage.bin, www/ = $total bytes of flash"
echo "built $FW (game firmware): $GLUE, main.py, pack, engage.bin, www/ = $fwtotal bytes of flash"

[ -z "$1" ] && exit 0
if [ "$1" = auto ]; then C=""; else C="connect $1"; fi
SRC="$OUT"
[ "$LAYOUT" = fw ] && SRC="$FW"
# Stop whatever is running, clear old copies (a .py next to a .mpy would win; a /lv next to
# the game firmware hides its frozen core), copy, reset.
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
for p in ('/lv', '/lvx', '/www', '/lvship.py', '/selftest.py', '/lvwifi.py', '/lvweb.py', '/lvphone.py', '/lvstat.py', '/lvdays.py', '/lvcal.py', '/lvled.py', '/lvledcfg.py'):
    rm(p)
for d in ('/data', '/www'$( [ "$SRC" = "$OUT" ] && echo ", '/lv'")):
    try:
        os.mkdir(d)
    except OSError:
        pass
"
[ "$SRC" = "$OUT" ] && $MPREMOTE $C cp "$OUT"/lv/*.mpy :lv/
$MPREMOTE $C cp "$SRC"/www/*.gz :www/
$MPREMOTE $C cp "$SRC"/*.mpy "$SRC"/pack.bin "$SRC"/engage.bin "$SRC"/main.py :
$MPREMOTE $C exec "import os, gc; s = os.statvfs('/'); gc.collect(); print('board: flash free %d KB, heap free %d B' % (s[0] * s[3] // 1024, gc.mem_free()))"
echo "copied $SRC to ${1}. Reset the board (mpremote $C reset) to start main.py."
