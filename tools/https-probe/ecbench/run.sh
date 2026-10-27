#!/bin/sh
# Counts the Cortex-M0+ (Thumb-1) instructions mbedTLS 3.6.6 (the copy pinned by MicroPython
# v1.29.0, same ECP options as the rp2 port: MBEDTLS_ECP_NIST_OPTIM, default window/comb)
# needs for the three P-256 operations a TLS 1.2 ECDHE-ECDSA server does per full handshake:
# ephemeral keygen, ECDSA sign of the ServerKeyExchange, ECDH shared secret.
# Needs arm-none-eabi-gcc + libnewlib, qemu-user (qemu-arm). Takes ~2 minutes.
#   MP=~/.cache/lv-firmware/micropython-v1.29.0 sh ecbench/run.sh
set -e
cd "$(dirname "$0")"
MP="${MP:-$HOME/.cache/lv-firmware/micropython-v1.29.0}"
M=$MP/lib/mbedtls; L=$M/library
SRC="$L/bignum.c $L/bignum_core.c $L/ecp.c $L/ecp_curves.c $L/ecdsa.c $L/ecdh.c $L/asn1write.c $L/asn1parse.c $L/platform_util.c $L/md.c $L/sha256.c $L/hmac_drbg.c $L/constant_time.c"
arm-none-eabi-gcc -mcpu=cortex-m0plus -mthumb -O2 -DMBEDTLS_CONFIG_FILE='"cfg.h"' -I. -I$M/include -I$L \
  --specs=rdimon.specs -Wl,-Ttext-segment=0x100000 bench.c $SRC -o /tmp/lv-ecbench.elf
for w in 0 1 2 3; do
  n=$(qemu-arm -cpu cortex-m0 -one-insn-per-tb -d exec,nochain -D /dev/stdout /tmp/lv-ecbench.elf $w 2>/dev/null | grep -c "^Trace")
  echo "stage $w: $n instructions"
done
echo "stage 0 = setup (2 key pairs); 1 = +ECDHE keygen; 2 = +ECDSA sign; 3 = +ECDH shared"
