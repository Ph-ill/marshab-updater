# The heap safe mode needs while a phone installs an update through it (0.3.0), measured as
# on the board. Runs under the game firmware's unix build (LV_FROZEN_MP), from game/;
# tests/phone_heap.py ... --safe starts it and plays the phones from CPython:
#
#   micropython-lv32 -X heapsize=512k tests/mp_safe_heap.py frozen
#
# Safe mode (board/lvsafe.py start/server) is what a ship that keeps crashing runs: the
# hotspot, the phone page, sign-in, Settings > Ship software and /api/ota*, no Bluetooth,
# no story, no season log in RAM. It is also where an update that couldn't get through the
# game's heap (a MemoryError while the game was loaded, twice) is tried again, so it has to
# take a whole upload well inside the 80,000 B cap. Resident here, as on a board: all of
# main.py (it is __main__ there: every function it defines, cut at the line that starts a
# board, as tests/mp_sync_heap.py does), lvsafe and lvweb; lvotaq, lvotap, lvota and lvsig
# load and drop per request as they do on a board. lvota comes from build/heap-ota-mod
# (a test key; staging under build/heap-ota). Prints PORT <n>, serves until
# build/heap-data/done exists, then the board peak (its share of the heap) and RESULT.
import sys
import gc
import os

for p in ("", "."):
    while p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, "build/board-fw")
sys.path.insert(0, "build/heap-ota-mod")
DATA = "build/heap-data"
ROOT = "build/board-fw/"
for n in ("done", "fault.json"):
    try:
        os.remove(DATA + "/" + n)
    except OSError:
        pass
with open(DATA + "/fault.json", "w") as f:                 # 2 crashes in a row: safe mode
    f.write('{"n": 2, "why": "MemoryError: memory allocation failed, allocating 1024 bytes", "up": 5000}')
gc.collect()
base = gc.mem_alloc()
peak = [0]
where = [""]
PER_USE = ("lvota", "lvotap", "lvotaq", "lvsig", "lvcheck", "lvsetup",
           "lvphoneapi", "lvphoneinit", "lvstateapi", "lvlight")


def sample():
    gc.collect()
    m = gc.mem_alloc() - base
    if m > peak[0]:
        peak[0] = m
        where[0] = "+".join(n for n in PER_USE if n in sys.modules) or "no per-use module"
    return m


import lvship                       # noqa: E402  (main.py imports it at the top)
import lvweb                        # noqa: E402
import lvsafe                       # noqa: E402
with open("board/main.py") as f, open("build/heap_main_safe.py", "w") as o:
    for ln in f:
        if ln.startswith("T0 = time.ticks_ms()"):
            break
        o.write(ln)
sys.path.insert(0, "build")
import heap_main_safe               # noqa: E402
sys.path.pop(0)
M = heap_main_safe.__dict__
lvweb.probe = sample
cfg = lvship.load_config("/nonexistent")
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio


async def run():
    web, sh = lvsafe.server(lvweb, cfg, "2 crashes in a row (MemoryError)", "127.0.0.1", None,
                            data=DATA, root=ROOT)
    M["home_screen"](lvweb)
    M["net_hooks"](lvweb, web)
    srv = None
    port = 19000 + gc.mem_free() % 997
    for i in range(20):
        try:
            srv = await asyncio.start_server(web.handle, "127.0.0.1", port + i)
            port += i
            break
        except OSError:
            pass
    print("PORT %d" % port)
    while True:
        sample()
        try:
            os.stat(DATA + "/done")
            break
        except OSError:
            pass
        await lvship.sleep_ms(20)
    srv.close()
    return web


web = asyncio.run(run())
board = peak[0]
ok = 0 < board < 80000 and web.served > 0 and not any(n in sys.modules for n in PER_USE)
print("impl %s; safe mode serving %d requests (%d refused busy)" % (sys.implementation.name, web.served, web.refused))
print("heap: safe-mode board peak %d B of the 80,000 B cap (%d B to spare), at %s; per-use modules %s after" % (
    board, 80000 - board, where[0], "dropped" if not any(n in sys.modules for n in PER_USE) else "STILL LOADED"))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
