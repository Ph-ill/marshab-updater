#!/bin/sh
# Build the bench firmware files for a Pico W / Pico 2 W and (optionally) copy them over.
#
#   sh tools/board_build.sh               build into build/board/ only
#   sh tools/board_build.sh PORT          build, then copy to the board on PORT
#                                         (/dev/ttyACM0, COM5, ... or "auto")
#
# Needs python3, mpy-cross 1.29 (pip install mpy-cross==1.29.0, or MPY_CROSS=/path) and,
# to copy, mpremote (pip install mpremote). Every module is precompiled to .mpy: nothing
# is compiled on the board, which is what keeps the heap low (docs/BENCH_TEST.md).
# The board's own settings (/data/ship.json) are never touched.
set -e
cd "$(dirname "$0")/.."
MPY_CROSS="${MPY_CROSS:-mpy-cross}"
MPREMOTE="${MPREMOTE:-mpremote}"
OUT=build/board

python3 tools/lvc.py > /dev/null
rm -rf "$OUT"
mkdir -p "$OUT/lv"
for f in lv/*.py; do
  "$MPY_CROSS" -o "$OUT/lv/$(basename "$f" .py).mpy" "$f"
done
for f in lvship selftest lvwifi; do
  "$MPY_CROSS" -o "$OUT/$f.mpy" "board/$f.py"
done
cp board/main.py "$OUT/main.py"       # the boot file stays .py (it is tiny)
cp build/pack.bin "$OUT/pack.bin"
total=$(cat "$OUT"/*.mpy "$OUT"/main.py "$OUT"/pack.bin "$OUT"/lv/* | wc -c)
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
echo "built $OUT: $(ls "$OUT"/lv | wc -l) lv modules + lvship, selftest, lvwifi, main.py, pack.bin = $total bytes of flash"

[ -z "$1" ] && exit 0
if [ "$1" = auto ]; then C=""; else C="connect $1"; fi
# Stop whatever is running, clear old copies (a .py next to a .mpy would win), copy, reset.
$MPREMOTE $C exec "
import os
for d, names in (('/lv', None), ('/', ('lvship.py', 'selftest.py', 'lvwifi.py'))):
    try:
        for n in os.listdir(d):
            if (names is None and n.endswith('.py')) or (names and n in names):
                os.remove(d.rstrip('/') + '/' + n)
    except OSError:
        pass
for d in ('/lv', '/data'):
    try:
        os.mkdir(d)
    except OSError:
        pass
"
$MPREMOTE $C cp "$OUT"/lv/*.mpy :lv/
$MPREMOTE $C cp "$OUT"/lvship.mpy "$OUT"/selftest.mpy "$OUT"/lvwifi.mpy "$OUT"/pack.bin "$OUT"/main.py :
$MPREMOTE $C exec "import os, gc; s = os.statvfs('/'); gc.collect(); print('board: flash free %d KB, heap free %d B' % (s[0] * s[3] // 1024, gc.mem_free()))"
echo "copied to ${1}. Reset the board (mpremote $C reset) to start main.py."
