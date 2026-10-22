#!/bin/sh
# Full offline check: syntax, unit, integration (simulated board), release validator.
# Add --online to also download the MicroPython .uf2 files and check their sha256.
set -e
cd "$(dirname "$0")/.."
for f in src/*.js; do node --check "$f"; done
node tests/unit.test.mjs
node tests/integration.test.mjs
python3 tools/validate_firmware.py "$@"
