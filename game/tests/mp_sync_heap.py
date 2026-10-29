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
# --live (with --phone --ota): ship-to-ship (board/lvlive.py) on both ships, as main.py's
# run() installs it; the peer queues a hail for this ship, and a sixth phone hails the peer
# through main.py's ota_route (board/lvliveapi.py, loaded per request) while the others play.
LIVE = "--live" in sys.argv
# a full day's hail.json to start from (FIXREVIEW2 B1: lvliveapi.HOUT sent, HIN received),
# as a busy ship's would be by evening; --no-seed: an empty one
SEED = LIVE and "--no-seed" not in sys.argv


def seed_hails(p):
    # written a line at a time (the test's own garbage, gone before anything is measured);
    # its day unset, so the ship takes it as today's whatever the phones' clock says
    e = 1792989200000
    with open(p, "w") as f:
        f.write('{"d": null, "n": 12, "o": [')
        for k in range(12):
            f.write('%s["%06x", %d, %d, %d, 2]' % (", " if k else "", k, 2 + k % 6, k % 8, e - 3600000 - k * 60000))
        f.write('], "i": [')
        for k in range(16):
            f.write('%s["%06x", %d, %d, %d, 1, 0, %d, %d]' % (
                ", " if k else "", 0x100 + k, 2 + k % 6, k % 8, e - k * 60000, 2 + k % 6, e - k * 60000 - 60000))
        f.write(']}')
# --everyone: the season where all eight crew play every day (build/season_log_all.bin,
# python3 sim/season.py --everyone: about 2.5 times the reference season's records): the
# busiest log a season is likely to have, everything else as above. The cap applies again
# (0.3.0): the board's own copy of a log that size (lv/chlog.py, the frozen lv-core 0.2.0's,
# ~30 B a record on the Pico: ~20 KB for 673 records) took 0.2.7 to ~84.5 KB with Hail at an
# update's upload pieces (lvota whole, the manifest parsed per piece); 0.3.0 puts a piece
# through the small lvotap (an index line, not the manifest), waits in lvotaq before it
# loads, and drops lvota through the signature check: ~78-79 KB, about 1 KB to spare.
EVERYONE = "--everyone" in sys.argv
LOG = "build/season_log_all.bin" if EVERYONE else "build/season_log.bin"
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
where = [""]
kpeak = {}
# 0.3.0 review R2 M2: with --live --ota, a hail comes in (a peer's trailer, taken as a session
# would) at the signature check, the update's tightest moment: it must be held (not taken,
# not acked, no lvlivein import), Hail stays on, and it's delivered later in the run.
hail_sig = []
HAIL_M = [None]


class HailSes:
    to = 1                           # (the peer: ship 2)

    def __init__(self):
        self.acks = []
# the moment of the peak: which per-use board modules were loaded, the web server's open
# requests and the radio (printed at the end, so a cap overrun says what it coincided with)
PER_USE = ("lvota", "lvotap", "lvotaq", "lvsig", "lvphone", "lvliveapi", "lvlivein", "lvlivex", "lvflick", "lvfunnel",
           "lvcode", "lvledtest", "lvbatt", "lvsafe")


def mem():
    gc.collect()
    return (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1


def sample():
    m = mem()
    k = "sig" if "lvsig" in sys.modules else "ota" if ("lvota" in sys.modules or "lvotap" in sys.modules) else "game"
    if m > kpeak.get(k, 0):
        kpeak[k] = m
    if k == "sig" and HAIL_M[0] is not None and not hail_sig and getattr(globals().get("ship"), "live", None):
        L = globals()["ship"].live
        h0, i0, se = L.n["held"], L.n["in"], HailSes()
        L.take(se, HAIL_M[0], 0)
        hail_sig.append((L.n["held"] - h0, L.n["in"] - i0, len(se.acks), "lvlivein" in sys.modules))
        m2 = mem()
        if m2 > kpeak[k]:
            kpeak[k] = m2
    if m > peak[0]:
        peak[0] = m
        try:
            where[0] = "%s; web busy %s; radio %s" % (
                "+".join(n for n in PER_USE if n in sys.modules) or "no per-use module",
                getattr(globals().get("web"), "busy", "-"),
                globals()["ship"].ble.state if "ship" in globals() else "-")
        except Exception as e:
            where[0] = "? %r" % (e,)
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
if LIVE:
    import lvlive                    # resident on a board (lvlivein, lvlivex, lvliveapi and lvflick load per use)
m_code = sample()

FK = b"test-fleet-key-not-secret"
with open(LOG, "rb") as f:
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
if LIVE:
    class PeerClock:                 # the peer has no phones: no time, so no hail light
        def minute(self):
            return None

        def date(self):
            return None

        def known(self):
            return False

    class PeerShip:
        ble, node, fk, clock, led, live, ledtest = peer, peer.node, FK, PeerClock(), None, None, None
        live_why = None

        def say(self, s):
            pass
    try:
        os.mkdir(DATA + "-peer")
    except OSError:
        pass
    for n in ("live.json", "livebox.json", "fault.json"):
        try:
            os.remove(DATA + "-peer/" + n)
        except OSError:
            pass
    peer_link = lvlive.install(PeerShip(), DATA + "-peer")
    import lvlivein                  # (per use, as lvliveapi loads it for a phone's hail)
    lvlivein.send(peer_link, 1, 0, bytes((1, 0, 1)))        # "Good morning" to ship 1 (this one) from crew 2
    if OTA:
        HAIL_M[0] = bytes((lvlive.MARK, 1)) + peer_link.out[0][1]
    lvship.drop("lvlivein")
    lvlivein = None
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


chg_watch = [None]


class TestPin:
    # --ota: POST /api/led/test (board/lvledtest.py) drives this instead of the LED
    n = 0

    def value(self, v):
        TestPin.n += 1


# main.py as the board holds it: every function and class it defines (review #2 M6: the
# resident code is all of it, about 9 KB on lv32, not only the parts a run calls), executed up
# to the line that starts a board (T0 = ...). Then, with the phone game, its home_screen()
# (the manifest and icon) always, its ota_hooks() with --ota, and its charger watch with
# --bat (the pin read every 100 ms, the bolt at once, next to lvship's loop), as the board
# runs them. Imported as a module from a copy cut at that line (build/heap_main.py), so it
# is compiled from the file as the board compiles main.py, never held as one string.
with open("board/main.py") as f, open("build/heap_main.py", "w") as o:
    for ln in f:
        if ln.startswith("T0 = time.ticks_ms()"):
            break
        o.write(ln)
sys.modules.pop("heap_main", None)
sys.path.insert(0, "build")
m0 = mem()
import heap_main                     # noqa: E402
m_main = mem() - m0
sys.path.pop(0)
MAIN_PY = heap_main.__dict__
if WEB:
    web = lvweb.Server(ship, root=ROOT, say=lambda s: None)
    lvweb.probe = sample
    g = MAIN_PY
    g["home_screen"](lvweb)
    if OTA:
        g["ota_hooks"](lvweb, web)
        ship.led_pin = TestPin         # Test light (board/lvledtest.py): the LED, counted
    if BAT:
        chg_watch[0] = g["charger_watch"]
    src = g = None
    gc.collect()
    handler = web.handle
    if LIVE:
        for n in ("live.json", "livebox.json", "fault.json", "hail.json"):
            try:
                os.remove(DATA + "/" + n)
            except OSError:
                pass
        if SEED:
            seed_hails(DATA + "/hail.json")
            print("live: hail.json seeded with a full day (12 sent, 16 received)")
        lvlive.install(ship, DATA)            # as main.py's run() does
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
    if chg_watch[0] and ship.bat:
        asyncio.create_task(chg_watch[0](ship))
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
      "board peak (peak - peer - fake radio) %d B%s; main.py's resident code %d B (in the peak)" % (
          peak[0], got, t, m_peer_end, board, " (cap 80,000 B applies to the 32-bit Pico)" if BITS == 64 else " of the 80,000 B cap",
          m_main))
print("heap: the peak came with %s" % where[0])
print("heap: board peak by moment: %s" % ", ".join("%s %d B" % (k, kpeak[k] - m_peer_end - m_fake) for k in sorted(kpeak)))
if EVERYONE and BITS == 32:
    print("heap: the everyone-plays season: %d B to spare under the 80,000 B cap" % (80000 - board))
print("http: status server %s, phone clock learned %s" % ("answered" if http_ok[0] else "NOT answered",
                                                           ship.clock.known()))
if PHONE:
    # Bluetooth contact for the phones (lvphone.air): ship 2 heard seconds ago and in sync,
    # nobody else heard; ship 1 is this one.
    A = air[0]
    # "seconds ago" is lv/ble's _swept (moved on at most every 10 s, by a status look) less the
    # last advert heard; with Hail on, the peer spends some of the after-sync minute in a
    # session (not advertising) and the 0.3.0 upload's waits move the phones' last looks, so
    # anything within that minute (60 s of scans) counts: 36 s was seen once, 0-26 s usually.
    air_ok = A is not None and len(A) == 1 and A[0][0] == 1 and 0 <= A[0][1] <= 60 and A[0][2] is True
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
if OTA and WEB:
    # Test light played its 10 s pattern twice (blinks and software-PWM breaths), then went
    lt_ok = TestPin.n >= 200 and "lvledtest" not in sys.modules
    ok = ok and lt_ok
    print("test light: pin writes %d, lvledtest %s: %s" % (
        TestPin.n, "loaded" if "lvledtest" in sys.modules else "dropped", "ok" if lt_ok else "FAIL"))
if LIVE:
    # Hail both ways over the same syncs: the phone's to the peer acked back to this ship, the
    # peer's to this one taken (and acked); nothing refused as bad, lvliveapi dropped.
    L = ship.live
    PL = peer_link
    lv_ok = (L is not None and PL is not None and L.n["in"] >= 1 and PL.n["in"] >= 1 and not L.out
             and not PL.out and L.n["bad"] == 0 and PL.n["bad"] == 0 and "lvliveapi" not in sys.modules
             and "lvlivein" not in sys.modules)
    ok = ok and lv_ok
    if OTA and WEB:
        hs = hail_sig[0] if hail_sig else None
        hs_ok = hs is not None and hs[0] == 1 and hs[1] == 0 and hs[2] == 0 and not hs[3] and L is not None
        ok = ok and hs_ok
        print("live: a hail at the signature check: %s (held, taken, acks, lvlivein loaded); Hail %s: %s" % (
            hs, "on" if L is not None else "off", "ok" if hs_ok else "FAIL"))
    try:
        import json
        with open(DATA + "/hail.json") as f:
            hj = json.load(f)
        print("live: hail.json at the end: %d sent (%d today), %d received" % (len(hj["o"]), hj.get("n", -1), len(hj["i"])))
        hj = None
    except (OSError, ValueError, KeyError):
        pass
    print("live: ship %s, peer %s, waiting %d/%d, lvliveapi and lvlivein %s: %s" % (
        L and L.n, PL and PL.n, len(L.out) if L else -1, len(PL.out) if PL else -1,
        "loaded" if "lvliveapi" in sys.modules or "lvlivein" in sys.modules else "dropped",
        "ok" if lv_ok else "FAIL"))
print("led: notifier %s, pin writes %d" % ("on" if ship.led.enabled else "off (default)", ship.led.writes))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
