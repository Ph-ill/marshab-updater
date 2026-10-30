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

SAFE = "--safe" in sys.argv           # board/lvsafe.py's safe-mode server instead (web/safe.js)
if SAFE:
    sys.argv.remove("--safe")
DUEL = "--duel" in sys.argv
if DUEL:
    sys.argv.remove("--duel")
    sys.argv.append("--live")
LIVE = "--live" in sys.argv           # ship-to-ship (board/lvlive.py) on, with a few hails (web/live.js)
if LIVE:
    sys.argv.remove("--live")
    sys.path.insert(0, "tests/fakeble")
LIVEOFF = "--live-off" in sys.argv    # the same, paused after a fault
if LIVEOFF:
    sys.argv.remove("--live-off")
# --live-as=STATE (with --live): idle (no hails yet), night (quiet hours), cap (today's lights
# used up), off (turned off in Settings), fleet (lvlive.ON False: the fleet kill switch)
LIVEAS = ([a[10:] for a in sys.argv if a.startswith("--live-as=")] or [""])[0]
sys.argv[:] = [a for a in sys.argv if not a.startswith("--live-as=")]  # in place: MicroPython's sys is read-only
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
for n in ("local.bin", "days.bin", "clock.json", "funnel.bin", "live.json", "livebox.json", "hail.json", "fault.json", "duel.json"):
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

if SAFE:
    import lvsafe
    _src = open("board/main.py").read()
    _src = _src[_src.index("def home_screen"):_src.index("\nasync def ota_ok")]
    _g = {"lvship": lvship, "asyncio": asyncio}
    exec(_src, _g)
    srv, _sh = lvsafe.server(lvweb, {"ship_id": 3}, "2 crashes in a row (MemoryError)", "127.0.0.1:%d" % PORT,
                             lambda: print("RESTART"), DATA, ROOT)
    _g["home_screen"](lvweb)
    _g["net_hooks"](lvweb, srv)

    async def safe_main():
        await asyncio.start_server(srv.handle, "127.0.0.1", PORT)
        print("READY %d" % PORT)
        try:
            sys.stdout.flush()
        except AttributeError:
            pass
        while True:
            await asyncio.sleep(1)
    asyncio.run(safe_main())
    sys.exit(0)
cfg = lvship.load_config("/nonexistent")
cfg["day"] = DAY
cfg["ship_id"] = 3
if LAUNCH:
    cfg["launch_date"] = LAUNCH[0]
quiet = lambda s: None  # noqa: E731
ship = lvship.Ship(cfg, root=ROOT, data=DATA, say=quiet, radio=LIVE,
                   days=lvdays.Days(DATA + "/days.bin"))
if LIVE:
    # Ship 3 with crewmates' ships heard (1 and 2 nearby, 5 an hour ago, 7 on old software),
    # a hail from ship 1 three minutes ago, one to ship 5 seen, one to ship 7 waiting.
    import time
    import lvlive
    import lvlivein
    from lv.ble import Peer
    if LIVEOFF:
        with open(DATA + "/fault.json", "w") as f:
            f.write('{"n": 1, "why": "MemoryError()", "up": 4000, "live": 1}')   # (in Hail's code: R2 M3)
    now = int(time.time() * 1000)
    ship.clock.learn(now, -300)
    # The hail light switched on in Settings: the fixture's Ship light is the dark notifier,
    # which the hail light would otherwise follow (0.3.0 review R2 M7)
    lvlivein.save(DATA + "/live.json", {"light": True})
    if LIVEAS == "off":
        lvlivein.save(DATA + "/live.json", {"on": False, "why": "turned off", "light": True})
    if LIVEAS == "fleet":
        lvlive.ON = False
    L = lvlive.install(ship, DATA)
    if L is not None:
        L.now = 10000000
        for k, ago, cap in ((0, 20, 1), (1, 25, 1), (4, 3600, 1), (6, 900, 0), (3, 30000, 1)):
            p = ship.ble.peers[k] = Peer(k)
            p.addr, p.seen = (0, bytes(6)), L.now - ago * 1000
            p.info = {"cap": cap, "busy": False}
        L.nx[6] = [3, 0]
        L.n.update({"dial": 6, "dial_ok": 4, "dial_fail": 2, "in": 3, "acked": 3})
        L.lc = [ship.clock.date(), 12 if LIVEAS == "cap" else 2]
        L.nx[1] = [1, L.now + 5000]          # the hail to ship 2 is between its two fast dials
        lvlivein.keep(L)
        m = ship.clock.minute()
        if LIVEAS == "night":   # quiet hours from a minute ago until 07:00, whatever the time
            ship.led.q = ((m - 1) % 1440, 420) if not (m >= 1320 or m < 420) else (1320, 420)
        elif m >= 1320 or m < 420:   # every other state by day, whenever the shots are taken
            ship.led.q = ((m + 60) % 1440, (m + 120) % 1440)
        hl = {"d": ship.clock.date(), "o": [
            ["01000a", 4, 1, now - 3600000, 3], ["01000b", 6, 0, now - 1500000, 0],
            ["01000c", 0, 5, now - 720000, 2], ["01000d", 1, 3, now - 4000, 0]],
            "i": [["7f0003", 0, 0, now - 180000, 0, 0, 0]]}
        if LIVEAS == "idle":
            hl["o"], hl["i"] = [], []
        lvlivein.save(DATA + "/hail.json", hl)
        ship.ble.n.update({"ok": 41, "fail": 3, "out": 22, "in": 22, "refused": 1})
        ship.ble.last = "ble: synced with ship 1: sent 4, got 2 (2 new)"
if LAUNCH:
    ship.clock.learn(int(LAUNCH[1]), int(LAUNCH[2]))
    ship.day_check()
    if ship.day != DAY:
        print("calendar says flight day %d, expected %d" % (ship.day, DAY))
        sys.exit(1)
srv = lvweb.Server(ship, root=ROOT, ip="127.0.0.1:%d" % PORT, say=quiet)


class _Led:
    # Test light (board/lvledtest.py): the board's LED, here a pin that counts its writes
    n = 0

    def value(self, v):
        _Led.n += 1


ship.led_pin = _Led
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


async def duel_peer():
    # A deterministic opponent for phone screenshots; board-side rules and signed
    # envelopes are real. Radio loss/retry is exercised in test_duel.py instead.
    import bluetooth
    import lvduel
    from lv import sync as sync
    from lv.chlog import ChoiceLog
    from lv.ble import BleSync
    class PeerShip:
        def say(self, text):
            pass
    peer = PeerShip()
    peer.data = DATA + "/duel-peer"
    try:
        os.mkdir(peer.data)
    except OSError:
        pass
    for n in ("livebox.json", "duel.json"):
        try:
            os.remove(peer.data + "/" + n)
        except OSError:
            pass
    peer.fk, peer.clock, peer.led, peer.web, peer.ledtest = ship.fk, ship.clock, None, None, None
    peer.node = sync.Node(ChoiceLog(ship.fk), 0, ship.fk, 3)
    world = bluetooth.World(31)
    peer.ble = BleSync(peer.node, world.new())
    lvlive.install(peer, peer.data)
    peer.live.cfg["dl"] = False
    class Session:
        def __init__(self, frm):
            self.to, self.acks = frm, []
    def deliver(a, b):
        it = [o[1] for o in a.live.out if o[0] == b.node.ship][:6]
        if not it:
            return
        s = Session(a.node.ship)
        b.live.take(s, bytes((lvlive.MARK, len(it))) + b"".join(it), 0)
        if s.acks:
            a.live.take(Session(b.node.ship), bytes((lvlive.MARK, len(s.acks))) + b"".join(s.acks), 0)
    while True:
        deliver(ship, peer)
        games = lvduel.view(peer.live)
        if games:
            g = games[0]
            if g["s"] == "invited":
                lvduel.action(peer.live, {"action": "accept", "to": ship.node.ship, "layout": [[0, 0], [12, 0], [35, 0]]})
            elif g["turn"] and not g["pending"]:
                # Miss until all empty cells are used. The phone can finish first.
                own = lvduel.view(ship.live)
                occupied = [c for row in (own[0]["layout"] or []) for c in row] if own else []
                fired = [z[1] for z in g["shots"]]
                choices = [c for c in range(36) if c not in fired and c not in occupied]
                if choices:
                    lvduel.action(peer.live, {"action": "fire", "to": ship.node.ship, "cell": choices[0]})
        deliver(peer, ship)
        await asyncio.sleep(.05)


async def main():
    await asyncio.start_server(srv.handle, "127.0.0.1", PORT)
    if DUEL:
        asyncio.create_task(duel_peer())
    print("CREW %d" % crew)
    print("READY %d" % PORT)
    try:
        sys.stdout.flush()       # a pipe on CPython
    except AttributeError:
        pass
    while True:
        await asyncio.sleep(1)


asyncio.run(main())
