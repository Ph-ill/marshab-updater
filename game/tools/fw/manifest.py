# Frozen-module manifest for the Long Voyage game firmware (tools/build_firmware.sh).
# Paths are relative to this file.
#
# Frozen code runs from flash: only its objects live on the heap, not its bytecode.
#   lv-core 0.1.0  the deterministic game core lv/ (engine, state, pack reader, records and
#                  log, BLE sync, codes, engagement rules...) and lvfrozen.py.
#   lv-core 0.2.0  also the board modules (lvship ... selftest, tools/fw/gen_lvfrozen.py
#                  BOARD) and the story pack as a frozen bytes object (lvpackdata.py):
#                  about 29 KB less heap with two phones playing during a BLE sync.
# Still files the web updater installs: main.py, the phone page and text (www/*.gz) and
# engage.bin. Every frozen piece can still be replaced without reflashing: /lvx/<name>.mpy
# for lv.<name> (lv/__init__.py), /<board module>.mpy and /pack.bin for the rest (found
# before the frozen ones on sys.path). tools/board_build.sh ships only what changed since
# the flashed core, and the updater removes stale copies of everything else.

# The board's own manifest first: networking, aioble, asyncio, _boot.py (filesystem).
include("$(BOARD_DIR)/manifest.py")

package("lv", base_path="../..")
module("lvfrozen.py", base_path="../../build/fw")
module("lvpackdata.py", base_path="../../build/fw")
# The board modules, in tools/fw/gen_lvfrozen.py BOARD order (tests/test_fw_split.py checks
# the two agree). -O3 as tools/board_build.sh compiles their file versions.
module("lvship.py", base_path="../../board", opt=3)
module("lvreport.py", base_path="../../board", opt=3)
module("lvcal.py", base_path="../../board", opt=3)
module("lvled.py", base_path="../../board", opt=3)
module("lvledcfg.py", base_path="../../board", opt=3)
module("lvbatt.py", base_path="../../board", opt=3)
module("lvdays.py", base_path="../../board", opt=3)
module("lvweb.py", base_path="../../board", opt=3)
module("lvphone.py", base_path="../../board", opt=3)
module("lvstat.py", base_path="../../board", opt=3)
module("lvwifi.py", base_path="../../board", opt=3)
module("selftest.py", base_path="../../board", opt=3)
# Over-the-air updates (since the core after 0.2.0; on 0.2.0 releases ship them as .mpy files).
module("lvota.py", base_path="../../board", opt=3)
module("lvsig.py", base_path="../../board", opt=3)
module("lvboot.py", base_path="../../board", opt=3)
# The home-screen funnel (after 0.2.2; on older cores releases ship it as lvfunnel.mpy).
module("lvfunnel.py", base_path="../../board", opt=3)
# Change your code (after 0.2.4; on older cores releases ship it as lvcode.mpy).
module("lvcode.py", base_path="../../board", opt=3)
# Test light (after 0.2.5; on older cores releases ship it as lvledtest.mpy).
module("lvledtest.py", base_path="../../board", opt=3)
# Safe mode and the fault notes (after 0.2.6; on older cores releases ship it as lvsafe.mpy).
module("lvsafe.py", base_path="../../board", opt=3)
# Ship-to-ship (after 0.2.7; on older cores releases ship them as .mpy).
module("lvlive.py", base_path="../../board", opt=3)
module("lvlivein.py", base_path="../../board", opt=3)
module("lvlivex.py", base_path="../../board", opt=3)
module("lvflick.py", base_path="../../board", opt=3)
module("lvliveapi.py", base_path="../../board", opt=3)
# The update's upload, split out of lvota (0.3.0; on older cores releases ship it as lvotap.mpy).
module("lvotap.py", base_path="../../board", opt=3)
module("lvotaq.py", base_path="../../board", opt=3)
# The update path's check before a trial is kept (0.3.0; on older cores it ships as lvotak.mpy).
module("lvotak.py", base_path="../../board", opt=3)
# Review-1 heap helpers; still ordinary .mpy files on the existing 0.2.0 core.
module("lvcheck.py", base_path="../../board", opt=3)
module("lvstateapi.py", base_path="../../board", opt=3)
module("lvphoneapi.py", base_path="../../board", opt=3)
module("lvsetup.py", base_path="../../board", opt=3)
module("lvphoneinit.py", base_path="../../board", opt=3)
module("lvlight.py", base_path="../../board", opt=3)
# Asteroid duel (0.3.1): an ordinary per-use .mpy override on existing cores.
module("lvduel.py", base_path="../../board", opt=3)
module("lvduelview.py", base_path="../../board", opt=3)
module("lvduelaction.py", base_path="../../board", opt=3)
module("lvduelrx.py", base_path="../../board", opt=3)
module("lvduellayout.py", base_path="../../board", opt=3)
module("lvlivecfg.py", base_path="../../board", opt=3)
module("lvduelmaint.py", base_path="../../board", opt=3)
module("lvliveops.py", base_path="../../board", opt=3)
module("lvduelother.py", base_path="../../board", opt=3)
module("lvduelstore.py", base_path="../../board", opt=3)
