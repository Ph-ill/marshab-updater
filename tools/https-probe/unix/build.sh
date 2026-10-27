#!/bin/sh
# Builds the 32-bit unix MicroPython v1.29.0 with the rp2 port's mbedTLS options and
# bare-metal allocation (mbedTLS buffers on the GC heap, as on the Pico), plus an allocation
# counter (probe_alloc.c: SIGUSR1 prints "ALLOC cur= peak=" and resets the peak).
#   MP=~/.cache/lv-firmware/micropython-v1.29.0 sh unix/build.sh [in4k]
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
MP="${MP:-$HOME/.cache/lv-firmware/micropython-v1.29.0}"
CFG=$D/mbedtls_config_rp2like.h; SUF=
[ "$1" = in4k ] && { CFG=$D/mbedtls_config_rp2like_in4k.h; SUF=-in4k; }
gcc -m32 -O2 -c "$D/unix/probe_alloc.c" -o /tmp/lv_probe_alloc.o
make -s -C "$MP/ports/unix" submodules >/dev/null
make -s -C "$MP/ports/unix" -j"$(nproc)" BUILD=build-tlsprobe32$SUF PROG=micropython-tls32$SUF \
  CFLAGS_EXTRA="-m32 -DMICROPY_TRACKED_ALLOC=1" \
  LDFLAGS_EXTRA="-m32 /tmp/lv_probe_alloc.o -Wl,--wrap=m_tracked_calloc,--wrap=m_tracked_free" \
  MICROPY_PY_FFI=0 MICROPY_PY_BTREE=0 MICROPY_SSL_AXTLS=0 MICROPY_PY_SSL=1 MICROPY_SSL_MBEDTLS=1 \
  MBEDTLS_CONFIG_FILE="\\\"$CFG\\\""
cp "$MP/ports/unix/build-tlsprobe32$SUF/micropython-tls32$SUF" "$D/unix/"
echo "built $D/unix/micropython-tls32$SUF"
