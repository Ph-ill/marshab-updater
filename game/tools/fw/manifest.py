# Frozen-module manifest for the Long Voyage game firmware (tools/build_firmware.sh).
# Paths are relative to this file.
#
# Frozen ("option 2"): only what rarely changes, the deterministic game core lv/ (engine,
# state, pack reader, records and log, BLE sync, codes, engagement rules...), plus
# lvfrozen.py, the manifest of what was frozen (tools/fw/gen_lvfrozen.py).
# Not frozen, updatable as files by the web updater: the story pack and text, the phone
# page (www/app.html.gz), engage data, and the board glue (main.py, lvship, lvweb,
# lvphone, lvwifi, selftest). A file /lvx/<name>.mpy replaces the frozen lv.<name>
# (lv/__init__.py), so a core fix can ship without reflashing too.

# The board's own manifest first: networking, aioble, asyncio, _boot.py (filesystem).
include("$(BOARD_DIR)/manifest.py")

package("lv", base_path="../..")
module("lvfrozen.py", base_path="../../build/fw")
