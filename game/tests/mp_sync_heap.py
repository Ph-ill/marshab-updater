# The heap one ship needs with BLE sync running, measured as on the board.
# Runs under MicroPython (unix port, 32- and 64-bit) and CPython (no numbers), from game/:
#
#   micropython -X heapsize=256k tests/mp_sync_heap.py [dir | frozen] [--phone]
#
# One ship as on the board: the lv modules and the board glue (lvship, lvweb), the pack,
# the whole season in the log, the story replayed to the last day, BLE sync (lv/ble.py on
# the fake radio from tests/fakeble) and the web server answering over a real socket.
# It syncs a peer that missed almost the whole season (221 records over the link). The
# live heap (after gc) is sampled through all of it, including at the web server's
# busiest points (lvweb.probe, lvphone.probe). The board's share must stay under
# 80 KB (80,000 B): the peak, less the fake radio module and the peer at its largest
# (see below). The LED stays off, unless:
#   --led    the LED notifier on (led_notify: board/lvled.py loaded, a fake pin from
#            tests/fakeboard): it breathes through the sync (no quiet hours, a test pattern
#            first), polled frame by frame as its asyncio task (lvled.Led.run) does. On stock MicroPython the
#            notifier stays dark (game firmware only); --led --force measures it anyway.
#   dir      a directory of .mpy files first on the path (tools/board_build.sh build/board:
#            stock MicroPython, Variant A): the code comes precompiled, as on the board.
#   frozen   the interpreter has the game core lv/ frozen in (tools/build_firmware.sh
#            unix32, the Pico firmware's manifest); the rest comes from build/board-fw,
#            the files the updater installs on a game-firmware board.
#   --bat    a UPS-Lite battery (board/lvbatt.py, a fake CW2015 gauge from tests/fakeboard:
#            72 %, charging): found at boot, read every simulated second while the
#            radio is idle (lvship reads once a minute), lvbatt dropped after each read.
#   --phone  phones play while it syncs: prints PORT <n> and serves the phone game until
#            build/heap-data/done exists. tests/phone_heap.py drives it from CPython (two
#            phones through tests/phone_flow.py, in another process so their buffers
#            aren't counted) and checks every answer.
import sys
import gc

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PHONE = "--phone" in sys.argv
LED = "--led" in sys.argv
BAT = "--bat" in sys.argv
# --ota (with --phone): main.py's over-the-air hooks on the server, and lvota from
# build/heap-ota-mod/ (tests/phone_heap.py writes it: board/lvota.py with a test key and its
# staging under build/heap-ota/), so a phone can upload a signed update while the others play.
OTA = "--ota" in sys.argv
if LED or BAT:
    sys.path.insert(0, "tests/fakeboard")
    import fakeboard
    fakeboard.install()
if BAT:
    import fake_machine
    fake_machine.BAT.update({"on": True, "soc": 72 * 256, "mv": 3950, "chg": True})
FROZEN = bool(ARGS) and ARGS[0] == "frozen"
if FROZEN:
    for p in ("", "."):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, "build/board-fw")
    sys.path.insert(0, "tests/fakeble")
    ROOT = "build/board-fw/"
else:
    if ARGS:
        sys.path.insert(0, ARGS[0])
    sys.path.insert(1 if ARGS else 0, "tests/fakeble")
    sys.path.append("board")
    sys.path.append(".")
    ROOT = ARGS[0].rstrip("/") + "/" if ARGS else "build/"
if OTA:
    sys.path.insert(0, "build/heap-ota-mod")
DATA = "build/heap-data"         # the board's /data: log.bin, days.bin (each day's story)
import os                         # noqa: E402
try:
    os.mkdir(DATA)
except OSError:
    pass
for n in ("log.bin", "local.bin", "days.bin", "done", "clock.json"):    # crew.json: tests/phone_heap.py writes it
    try:
        os.remove(DATA + "/" + n)
    except OSError:
        pass
gc.collect()
base = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 0
peak = [0]


def mem():
    gc.collect()
    return (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1


def sample():
    m = mem()
    if m > peak[0]:
        peak[0] = m
    return m


import bluetooth                    # noqa: E402  (the fake)
m_fake = sample()
import lvship                        # noqa: E402
# The web server the board runs: the phone game's (lvweb) on the game firmware or with
# --phone; the bench status server (lvstat) on stock MicroPython.
WEB = FROZEN or PHONE
if WEB:
    import lvweb                     # noqa: E402
    import lvdays                    # noqa: E402
else:
    import lvstat                    # noqa: E402
if PHONE:
    import lvphone                   # loaded on the first phone request on a board: counted as code here
from lv import record as R          # noqa: E402
from lv import sync as S            # noqa: E402
from lv.chlog import ChoiceLog      # noqa: E402
from lv.ble import BleSync          # noqa: E402
m_code = sample()

FK = b"test-fleet-key-not-secret"
with open("build/season_log.bin", "rb") as f:
    RAW = f.read()
NREC = len(RAW) // R.LEN
FAST = {"scan_every_ms": 6000, "scan_ms": 3000}

w = bluetooth.World(15)
plog = ChoiceLog(FK)
for i in range(NREC):
    r = RAW[i * R.LEN:(i + 1) * R.LEN]
    if R.ship(r) == 1:
        plog.merge(r)
peer = BleSync(S.Node(plog, 1, FK, 42), w.new(), FAST)
m_peer = sample()
cfg = lvship.load_config("/nonexistent")
cfg["day"] = 42
cfg["ble"] = FAST
if PHONE:
    # The phone game as it runs for real: the day from the calendar (board/lvcal.py), FD 42
    # once the first request brings the phones' clock (launched long enough ago).
    cfg["launch_date"] = "2026-09-01"
if LED:
    cfg["led_notify"] = "--force" in sys.argv and "force" or True   # stock MicroPython: --force
    cfg["led_quiet"] = ""
    cfg["led_unknown_time"] = True
# The board keeps each day's story for the phones only when it serves the phone game.
ship = lvship.Ship(cfg, root=ROOT, data=DATA, ble=w.new(), say=lambda s: None,
                   days=lvdays.Days(DATA + "/days.bin") if WEB else None)
for i in range(NREC):
    ship.node.merge([RAW[i * R.LEN:(i + 1) * R.LEN]])
ship.tick_to(42)
RAW = None
if LED and ship.led.enabled:
    ship._led("test")
    ship._led("gift")
WANT = ship.node.digest()
m_ship = sample()

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

http_ok = [False]
if PHONE:
    lvphone.probe = sample


async def client(port):
    r, wr = await asyncio.open_connection("127.0.0.1", port)
    wr.write(b"GET /api/sync HTTP/1.0\r\nX-Phone-Time: 1792843200000\r\nX-Phone-TZ: -300\r\n\r\n")
    await wr.drain()
    body = b""
    while True:
        b = await r.read(256)
        if not b:
            break
        body += b
    wr.close()
    http_ok[0] = body.startswith(b"HTTP/1.0 200") and b'"digest"' in body


if WEB:
    web = lvweb.Server(ship, root=ROOT, say=lambda s: None)
    lvweb.probe = sample
    # main.py's home_screen() (the manifest and icon) always, and its ota_hooks() with
    # --ota, as they are (main.py itself starts a board, so only those parts).
    # Read line by line, so the measured heap holds only those functions, not main.py's text.
    src, on = [], False
    with open("board/main.py") as f:
        for ln in f:
            if ln.startswith("def home_screen"):
                on = True
            elif ln.startswith("async def ota_ok") or (ln.startswith("def ota_hooks") and not OTA):
                break
            if on:
                src.append(ln)
    g = {"lvship": lvship, "asyncio": asyncio}
    exec("".join(src), g)
    g["home_screen"](lvweb)
    if OTA:
        g["ota_hooks"](lvweb, web)
    src = g = None
    gc.collect()
    handler = web.handle
else:
    handler = lvstat.server(ship)
during = [0]
air = [None]
bat = [None, 0]


def done_flag():
    try:
        os.stat(DATA + "/done")
        return True
    except OSError:
        return False


async def heap_run():
    srv = None
    port = 18000 + (gc.mem_free() % 997 if hasattr(gc, "mem_free") else 0)
    for i in range(20):
        try:
            srv = await asyncio.start_server(handler, "127.0.0.1", port + i)
            port += i
            break
        except OSError:
            pass
    sample()
    if srv:
        await client(port)
    if PHONE:
        print("PORT %d" % port)
        while web.served < 2:            # sync starts with the first phone's visit
            await lvship.sleep_ms(5)
    t = 0
    phones_done = not PHONE
    while t < (600000 if PHONE else 120000):
        w.step(10)
        t += 10
        ship.ble.poll(w.now)
        peer.poll(w.now)
        if LED:
            ship.led.poll(ship.ble.busy())
        if BAT and t % 1000 == 0 and not ship.ble.busy() and not (WEB and web.busy > 0):
            ship.bat_poll()                  # as lvship's loop does, only while nothing is busy
            bat[1] += 1
        if t % 50 == 0:
            sample()
            await lvship.sleep_ms(1 if PHONE else 0)
            if not phones_done:
                phones_done = done_flag()
                if not phones_done:
                    during[0] = web.served
        # Done when the peer has everything (with phones: their taps too, once they've left).
        if phones_done and peer.node.digest() == ship.node.digest() and ship.ble.state == "idle" \
                and peer.state == "idle":
            break
    if PHONE:
        # A few more scans, so the ship hears the peer's advert after the sync (in sync now).
        for i in range(6000):
            w.step(10)
            ship.ble.poll(w.now)
            peer.poll(w.now)
            if i % 5 == 0:
                sample()
        # (not sampled: the phones' own /api/state calls during the sync are, above)
        air[0] = web.phone.state_body(0, 39, ship.clock.minute())["air"]
        bat[0] = web.phone.state_body(0, 39, ship.clock.minute())["bat"]
        gc.collect()
    if LED:
        # the patterns in real time (the sync above runs on the fake radio's clock): the
        # test breaths, then the gift's double pulse, polled frame by frame as the light's
        # own task (lvled.Led.run) does
        n = 0
        while n < 9000:
            d = min(100, max(1, ship.led.poll(False)))
            await lvship.sleep_ms(d)
            n += d
            sample()
    if srv:
        srv.close()
    return t


t = asyncio.run(heap_run())
if PHONE:
    WANT = ship.node.digest()       # the phones' taps went over too
synced = peer.node.digest() == WANT and peer.state == "idle" and ship.ble.state == "idle"
got = peer.node.new
# The peer's share of the peak: everything measured before the ship existed (m_peer -
# m_code: the fake world, the peer's radio, BleSync and first 53 records) plus what
# its log grew by. The growth is measured on copies built on their own afterwards: the
# peer's log as it started and as it ended.


def copy_size(ship_of):
    m0 = mem()
    clog = ChoiceLog(FK)
    for r in ship.log.values():
        if ship_of(R.ship(r)):
            clog.merge(r)
    m = mem() - m0
    clog = None
    return m


grow = copy_size(lambda s: True) - copy_size(lambda s: s == 1)
m_peer_end = m_peer - m_code + grow
board = peak[0] - m_peer_end - m_fake  # what a board holds: no second ship, no fake radio
BITS = 64 if sys.maxsize > 2 ** 32 else 32
# The cap is the Pico's: a 32-bit build. The 64-bit port's figure is printed for comparison.
led_ok = (ship.led.enabled and ship.led.writes >= 6 if lvship.game_fw() or "--force" in sys.argv else
          not ship.led.enabled and ship.led.writes == 0) if LED else (not ship.led.enabled and ship.led.writes == 0)
ok = (synced and http_ok[0] and led_ok and
      (base == 0 or BITS == 64 or (0 < board < 80000)))
import lv                                   # noqa: E402
if FROZEN:
    # the core is the frozen one (not hidden by a lv/ directory). Since lv-core 0.2.0 the glue
    # and the pack are frozen too, unless build/board-fw ships a newer copy (a hotfix file
    # is found first): each must come from exactly where the layout says.
    core, _ = lv.firmware()
    glue_file = str(getattr(lvship, "__file__", "")).startswith("build/board-fw")
    try:
        os.stat(ROOT + "lvship.mpy")
        want_glue_file = True
    except OSError:
        want_glue_file = False
    try:
        os.stat(ROOT + "pack.bin")
        want_pack = "file"
    except OSError:
        want_pack = "frozen"
    ok = (ok and core is not None and not core["shadowed"] and glue_file == want_glue_file
          and ship.pack_src == want_pack)
print("impl %s %d-bit; glue from %s, pack %s; %s" % (sys.implementation.name, BITS,
      lvship.__file__ if (not FROZEN or glue_file) else "the firmware (frozen)", ship.pack_src, lv.describe()))
print("heap: fake radio module %d, code (lvship + lv incl. sync, ble) %d, peer %d, ship with the whole season "
      "and the story at day 42 %d" % (m_fake, m_code - m_fake, m_peer - m_code, m_ship - m_peer))
print("heap: peak live %d B while syncing (peer got %d records in %d ms of radio time); peer and fake world at the end %d; "
      "board peak (peak - peer - fake radio) %d B%s" % (peak[0], got, t, m_peer_end, board, " (cap 80,000 B applies to the 32-bit Pico)" if BITS == 64 else " of the 80,000 B cap"))
print("http: status server %s, phone clock learned %s" % ("answered" if http_ok[0] else "NOT answered",
                                                           ship.clock.known()))
if PHONE:
    # Bluetooth contact for the phones (lvphone.air): ship 2 heard seconds ago and in sync,
    # nobody else heard; ship 1 is this one.
    A = air[0]
    air_ok = A is not None and len(A) == 1 and A[0][0] == 1 and 0 <= A[0][1] <= 30 and A[0][2] is True
    ok = ok and air_ok
    print("air: %s (ship 2 heard seconds ago, in sync): %s" % (A, "ok" if air_ok else "FAIL"))
    ok = ok and ship.cal is not None and ship.day == 42
    print("calendar: launch %s, flight day %d from the %s" % (ship.cal.date if ship.cal else None, ship.day,
                                                          ship.cal.src if ship.cal else "manual day"))
    print("phone: %d requests served (%d while the BLE radio ran), %d refused busy; heap peak includes "
          "/api/state, the page streamed from flash and the taps" % (web.served, during[0], web.refused))
if BAT:
    # the gauge found at boot and read while idle; lvbatt never stays loaded
    B = bat[0] if PHONE else (ship.bat[:3] if ship.bat else None)
    bat_ok = (B is not None and B[0] == 72 and 3940 <= B[1] <= 3960 and B[2] is True and bat[1] > 0
              and "lvbatt" not in sys.modules)
    ok = ok and bat_ok
    print("battery: %s after %d readings while idle, lvbatt %s: %s" % (
        B, bat[1], "loaded" if "lvbatt" in sys.modules else "dropped", "ok" if bat_ok else "FAIL"))
print("led: notifier %s, pin writes %d" % ("on" if ship.led.enabled else "off (default)", ship.led.writes))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
