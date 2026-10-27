# The board's phone server (board/lvweb.py + lvphone.py) on a real TCP port, for a browser
# to play against (tests/app_e2e.mjs). Runs on CPython or the MicroPython unix port, from game/:
#
#   python3 tests/phone_serve.py [day] [port] [launch_date epoch_ms tz_min]
#   micropython -X heapsize=1m tests/phone_serve.py [day] [port] [...]
#
# The board's files as tools/board_build.sh lays them out (www/*.gz, pack.bin, engage.bin)
# under build/e2e-root/, a ship at flight day `day` (default 9) with the reference season's
# records from before it, every crew code 1234. Prints "CREW <n>" (someone with a private
# dilemma open today, if anyone) and "READY <port>", then serves until killed.
# With a launch date (board/lvcal.py) the day comes from the calendar instead: the ship is
# told the phone time epoch_ms / tz_min before it starts, as a first phone request would,
# and moves to the next day when a phone's clock crosses 06:00 (tests/app_e2e.mjs).
# main.py's own routes are on it too (home_screen, ota_hooks): the manifest and icon, the
# update hooks, Reset this ship (its restart only prints RESET here) and /api/hello, the
# home-screen funnel (board/lvfunnel.py; funnel.bin is removed at start, so every run begins
# with a ship that has seen no phone).
import sys
import os
sys.path.append("board")
sys.path.append(".")
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import json

import lvship
import lvweb
import lvdays
from lv import codes as K
from lv import record as R

DAY = int(sys.argv[1]) if len(sys.argv) > 1 else 9
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8099
LAUNCH = sys.argv[3:6] if len(sys.argv) > 5 else None
ROOT = "build/e2e-root/"
DATA = "build/e2e-data"


def mkdir(p):
    try:
        os.mkdir(p)
    except OSError:
        pass


def copy(src, dst):
    with open(src, "rb") as f:
        b = f.read()
    with open(dst, "wb") as f:
        f.write(b)


mkdir(ROOT)
mkdir(ROOT + "www")
mkdir(DATA)
for n in ("app.html.gz", "text.json.gz", "engage.json.gz", "app.webmanifest.gz", "icon.png.gz"):
    copy("build/" + n, ROOT + "www/" + n)
mkdir(ROOT + "www/ls")                  # the iOS launch screens (tools/board_build.sh)
for n in os.listdir("web/launch"):
    copy("web/launch/" + n, ROOT + "www/ls/" + n)
copy("build/pack.bin", ROOT + "pack.bin")
copy("build/engage.bin", ROOT + "engage.bin")
for n in ("local.bin", "days.bin", "clock.json", "funnel.bin"):
    try:
        os.remove(DATA + "/" + n)
    except OSError:
        pass
with open(DATA + "/crew.json", "w") as f:
    f.write(json.dumps(K.make_config(["1234"] * 8, b"bench-salt-16-by")))
with open("build/season_log.bin", "rb") as f:
    raw = f.read()
with open(DATA + "/log.bin", "wb") as f:
    for i in range(0, len(raw), R.LEN):
        if R.day(raw[i:i + R.LEN]) < DAY:
            f.write(raw[i:i + R.LEN])
raw = None

cfg = lvship.load_config("/nonexistent")
cfg["day"] = DAY
cfg["ship_id"] = 3
if LAUNCH:
    cfg["launch_date"] = LAUNCH[0]
quiet = lambda s: None  # noqa: E731
ship = lvship.Ship(cfg, root=ROOT, data=DATA, say=quiet, radio=False,
                   days=lvdays.Days(DATA + "/days.bin"))
if LAUNCH:
    ship.clock.learn(int(LAUNCH[1]), int(LAUNCH[2]))
    ship.day_check()
    if ship.day != DAY:
        print("calendar says flight day %d, expected %d" % (ship.day, DAY))
        sys.exit(1)
srv = lvweb.Server(ship, root=ROOT, ip="127.0.0.1:%d" % PORT, say=quiet)
# main.py's over-the-air hooks as they are (/api/ota* to board/lvota.py; the page asks the
# ship what it runs). Nothing here uploads, so nothing is written.
_src = open("board/main.py").read()
_src = _src[_src.index("def home_screen"):_src.index("\nasync def ota_ok")]
_g = {"lvship": lvship, "asyncio": asyncio}
exec(_src, _g)
_g["reboot"] = lambda: print("RESET")     # "Reset this ship": the files go, no restart here
_g["home_screen"](lvweb)    # and the home-screen manifest and icon
_g["ota_hooks"](lvweb, srv)
_src = _g = None
crew = 2
for it in ship.st.pend:
    if it[0] == 4 and it[4] < 7 and it[4] != 5:
        crew = it[4]
        break


async def main():
    await asyncio.start_server(srv.handle, "127.0.0.1", PORT)
    print("CREW %d" % crew)
    print("READY %d" % PORT)
    try:
        sys.stdout.flush()       # a pipe on CPython
    except AttributeError:
        pass
    while True:
        await asyncio.sleep(1)


asyncio.run(main())
