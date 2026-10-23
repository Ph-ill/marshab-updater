#!/bin/sh
# Build the Long Voyage game firmware: MicroPython v1.29.0 for the Pico W with the game
# frozen in (tools/fw/manifest.py). Frozen code and data run from flash, so the heap
# keeps the ~50 KB the .mpy copy (tools/board_build.sh) spends on code.
#
#   sh tools/build_firmware.sh                    RPI_PICO_W .uf2
#   BOARD=RPI_PICO2_W sh tools/build_firmware.sh  Pico 2 W (untested on hardware)
#   sh tools/build_firmware.sh unix32             a 32-bit unix MicroPython with the same
#                                                 frozen set (heap measurements, tests)
#
# Output: $OUT (default build/firmware/) gets lv-<version>-<BOARD>.uf2 and a .sha256.
# Needs: git, make, cmake, python3, gcc-arm-none-eabi + libnewlib-arm-none-eabi (Debian/
# Ubuntu package names); gcc-multilib for unix32. Sources are cloned once into $FW_WORK
# (default ~/.cache/lv-firmware) at the pinned commits below and reused.
set -e
cd "$(dirname "$0")/.."
GAME=$(pwd)

# Pinned: MicroPython v1.29.0 and the submodules it pins (pico-sdk 2.3.0, and so on).
MP_TAG=v1.29.0
MP_COMMIT=0fd6c573ea815774668bbb16b8e197c8822368b2
PICO_SDK_COMMIT=98a542c1a62fb549ffb5d66a3e5892b06276b670
BOARD="${BOARD:-RPI_PICO_W}"
FW_WORK="${FW_WORK:-$HOME/.cache/lv-firmware}"
OUT="${OUT:-$GAME/build/firmware}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
MP="$FW_WORK/micropython-$MP_TAG"

if [ ! -d "$MP/.git" ]; then
  mkdir -p "$FW_WORK"
  git clone -q --depth 1 --branch "$MP_TAG" https://github.com/micropython/micropython.git "$MP"
fi
have=$(git -C "$MP" rev-parse HEAD)
[ "$have" = "$MP_COMMIT" ] || { echo "$MP is at $have, expected $MP_COMMIT ($MP_TAG)"; exit 1; }

# The game's build products the frozen data comes from.
python3 tools/lvc.py > /dev/null
python3 tools/lve.py > /dev/null
python3 web/build.py > /dev/null
python3 tools/fw/gen_lvdata.py
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' board/lvship.py)
MANIFEST="$GAME/tools/fw/manifest.py"

[ -x "$MP/mpy-cross/build/mpy-cross" ] || make -s -C "$MP/mpy-cross" -j"$JOBS"

if [ "$1" = unix32 ]; then
  # Same frozen set on the unix port, for measuring the heap the way the tests do.
  # The unix variant's manifest stands in for the board's (it has asyncio).
  UM="$FW_WORK/unix32-manifest.py"
  sed "s|\$(BOARD_DIR)/manifest.py|$MP/ports/unix/variants/standard/manifest.py|; s|base_path=\"\.\./\.\.|base_path=\"$GAME|; s|base_path=\"\.\"|base_path=\"$GAME/tools/fw\"|" \
    "$MANIFEST" | grep -v '"boot.py"' > "$UM"
  make -s -C "$MP/ports/unix" submodules > /dev/null
  make -s -C "$MP/ports/unix" -j"$JOBS" BUILD=build-lv32 PROG=micropython-lv32 \
    CFLAGS_EXTRA=-m32 LDFLAGS_EXTRA=-m32 MICROPY_PY_FFI=0 MICROPY_PY_BTREE=0 MICROPY_SSL_AXTLS=0 MICROPY_PY_SSL=0 \
    FROZEN_MANIFEST="$UM"
  mkdir -p "$OUT"
  cp "$MP/ports/unix/build-lv32/micropython-lv32" "$OUT/micropython-lv32"
  echo "built $OUT/micropython-lv32 (unix, 32-bit, game frozen, lvship $VERSION)"
  exit 0
fi

command -v arm-none-eabi-gcc > /dev/null || { echo "arm-none-eabi-gcc not found (apt install gcc-arm-none-eabi libnewlib-arm-none-eabi)"; exit 1; }
make -s -C "$MP/ports/rp2" BOARD="$BOARD" submodules > /dev/null
sdk=$(git -C "$MP/lib/pico-sdk" rev-parse HEAD)
[ "$sdk" = "$PICO_SDK_COMMIT" ] || { echo "pico-sdk is at $sdk, expected $PICO_SDK_COMMIT"; exit 1; }
B="build-lv-$BOARD"
make -s -C "$MP/ports/rp2" BOARD="$BOARD" BUILD="$B" FROZEN_MANIFEST="$MANIFEST" -j"$JOBS" > "$FW_WORK/$B.log" 2>&1 || {
  tail -30 "$FW_WORK/$B.log"; exit 1; }
mkdir -p "$OUT"
UF2="$OUT/lv-$VERSION-$BOARD.uf2"
cp "$MP/ports/rp2/$B/firmware.uf2" "$UF2"
(cd "$OUT" && sha256sum "$(basename "$UF2")" > "$(basename "$UF2").sha256")
echo "built $UF2: $(wc -c < "$UF2") bytes, sha256 $(cut -d' ' -f1 "$UF2.sha256")"
echo "MicroPython $MP_TAG ($MP_COMMIT), pico-sdk $PICO_SDK_COMMIT, lvship $VERSION"
arm-none-eabi-nm "$MP/ports/rp2/$B/firmware.elf" | python3 -c "
import sys
a = {l.split()[2]: int(l.split()[0], 16) for l in sys.stdin if len(l.split()) == 3}
print('GC heap (__GcHeapStart..__GcHeapEnd): %d B' % (a['__GcHeapEnd'] - a['__GcHeapStart']))"
arm-none-eabi-size "$MP/ports/rp2/$B/firmware.elf" | tail -1 | awk '{print "flash text " $1 " B, static RAM (data+bss) " $2+$3 " B"}'
