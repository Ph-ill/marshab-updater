# The heap one ship needs with BLE sync running, measured as on the board.
# Runs under MicroPython (unix port, 32- and 64-bit) and CPython (no numbers), from game/:
#
#   micropython -X heapsize=256k tests/mp_sync_heap.py [dir | frozen] [--phone]
#
# One ship as on the board: the lv modules and the board glue (lvship, lvweb), the pack,
# the whole season in the log, the story replayed to the last day, BLE sync (lv/ble.py on
# the fake radio from tests/fakeble) and the web server answering over a real socket.
# It syncs a peer that missed almost the whole season (221 records over the link). The
# The in-operation heap is sampled without collection, including at the web server's
# busiest points (lvweb.probe, lvphone.probe). The board's share must stay under
# CAP (110,000 B since 2026-10-30; 100,000 B from 2026-10-29, 80,000 B before): the peak,
# less the fake radio module and the peer at its largest
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
DUEL = "--duel" in sys.argv
LIVE = "--live" in sys.argv or DUEL
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


def seed_duels(lk, peer_lk):
    # Three legal, near-71-shot games, not three copies of an early invitation.
    # The last fleet cell (35) stays unshot, so every history is still active.
    import lvduel as D
    from binascii import hexlify
    from lvlivein import send
    layout = D.encode([[0, 0], [12, 0], [35, 0]])
    games = []
    for to in (1, 2, 3):
        ident, salt = bytes((0x48, to)), bytes((to,)) * 6
        g = D.fresh(lk, to, ident, 0, "active")
        g["l"], g["salt"] = hexlify(layout).decode(), hexlify(salt).decode()
        g["c"] = hexlify(D.commit(ident, layout, salt)).decode()
        n = 68 if to == 1 else 70
        h = ""
        for shot in range(1, n + 1):
            cell = (shot - 1) // 2
            r = D.result(layout, list(range(cell)), cell)
            h += chr(65 + cell) + chr(97 + r)
        g["n"], g["h"] = n, h
        # Durable recovery intents, all eleven bytes padded just like emit().
        body = ident + bytes((n, cell, r, 1)) + bytes(5)
        g["q"] = [[9, hexlify(body).decode()]]
        g["last"] = [5, hexlify(ident + bytes((n, cell)) + bytes(7)).decode()]
        games.append(g)
    # Seed the durable file without flushing: the first measured inbound call,
    # not fixture construction, must recover these obligations under pressure.
    # Seven finished-game stubs (lvduel.retire), each of the largest shape a stub
    # can take (review 0.3.1-9 #2): state, owed flag, a deferred reply (lvduel.defer)
    # and three queued moves (ANSWER, REVEAL, END), none reservable while the out-box
    # below is full. (A resignation's stub also keeps "why", but then allowed() keeps
    # only REVEAL and END: one 11-byte move more outweighs that small int.)
    rejections = []
    for to in range(1, 8):
        ident = bytes((0x52, to))
        g = {"to": to, "id": hexlify(ident).decode(), "s": "done", "o": 1,
             "rj": [hexlify(bytes((0x53, to))).decode(), 5],
             "q": [[6, hexlify(ident + bytes((71, 35, 3)) + bytes(6)).decode()],
                   [7, hexlify(ident + layout + bytes((to,)) * 6).decode()],
                   [8, hexlify(ident + bytes((2,)) + bytes(8)).decode()]]}
        rejections.append(g)
    D.save(lk.sh.data + D.F, {"g": games, "r": dict((str(to), [123, 123]) for to in range(1, 8)),
                             "e": rejections})
    remote = dict(games[0])
    remote["to"], remote["q"] = 0, []
    remote["last"] = [6, hexlify(bytes((0x48, 1, 68, 33, 0)) + bytes(6)).decode()]
    D.store(peer_lk, {"g": [remote], "r": {}})
    # Real Seen receipts occupy the shared finite outbox until the radio ACKs
    # them. This keeps q live during the first streamed /api/live + inbound shot;
    # nothing is cleared/discarded to make the phones' next move succeed.
    for k in range(24):
        send(lk, 2, 1, bytes((0x48, 0, k)))


# --everyone: the season where all eight crew play every day (build/season_log_all.bin,
# python3 sim/season.py --everyone: about 2.5 times the reference season's records): the
# busiest log a season is likely to have, everything else as above. The cap applies again
# (0.3.0): the board's own copy of a log that size (lv/chlog.py, the frozen lv-core 0.2.0's,
# ~30 B a record on the Pico: ~20 KB for 673 records) took 0.2.7 to ~84.5 KB with Hail at an
# update's upload pieces (lvota whole, the manifest parsed per piece); 0.3.0 puts a piece
# through the small lvotap (an index line, not the manifest), waits in lvotaq before it
# loads, and drops lvota through the signature check. Review-1 additionally bounds
# expensive responses before allocation and loads phone/boot helpers only when used;
# the acceptance target is <=78,000 B over three full and three normal combined runs.
# The board heap cap (32-bit): 110,000 B, Phill 2026-10-30 (100,000 B from 2026-10-29; 80,000 B before). A Pico W has about
# 193 KB free for the game; the cap leaves room for Wi-Fi buffers and fragmentation over days.
CAP = 110000
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
DUEL_M = [None]
duel_taken = [False]
duel_held = [False]
duel_injecting = [False]
duel_worst = [None]
duel_terminal = [None]
duel_phase = ["long"]
duel_peer_stage = [0]


class HailSes:
    to = 1                           # (the peer: ship 2)

    def __init__(self):
        self.acks = []
# the moment of the peak: which per-use board modules were loaded, the web server's open
# requests and the radio (printed at the end, so a cap overrun says what it coincided with)
PER_USE = ("lvota", "lvotap", "lvotaq", "lvsig", "lvphone", "lvliveapi", "lvlivein", "lvlivex", "lvflick", "lvfunnel",
           "lvcode", "lvledtest", "lvbatt", "lvsafe", "lvcheck", "lvstateapi",
           "lvphoneapi", "lvphoneinit", "lvsetup", "lvlight", "lvduel", "lvduelrx", "lvduelaction", "lvduelview", "lvduellayout", "lvlivecfg", "lvduelmaint", "lvliveops", "lvduelother", "lvduelstore")


def mem():
    gc.collect()
    return (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1


def sample():
    # No collection at operation probes: include temporary working allocations.
    m = (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1
    k = "sig" if "lvsig" in sys.modules else "ota" if ("lvota" in sys.modules or "lvotap" in sys.modules) else "game"
    if m > kpeak.get(k, 0):
        kpeak[k] = m
    if DUEL:
        phase = "duel-" + duel_phase[0]
        if m > kpeak.get(phase, 0):
            kpeak[phase] = m
    # Settings also imports lvsig for its self-check, outside OTA admission.
    # Only the upload verifier installs our web probe on that module.
    if (k == "sig" and getattr(sys.modules["lvsig"], "probe", None) is stream_sample
            and HAIL_M[0] is not None and not hail_sig and getattr(globals().get("ship"), "live", None)):
        L = globals()["ship"].live
        h0, i0, se = L.n["held"], L.n["in"], HailSes()
        L.take(se, HAIL_M[0], 0)
        hail_sig.append((L.n["held"] - h0, L.n["in"] - i0, len(se.acks), "lvlivein" in sys.modules))
        m2 = (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1
        if m2 > kpeak[k]:
            kpeak[k] = m2
    if m > peak[0]:
        peak[0] = m
        try:
            where[0] = "%s; web busy %s; radio %s" % (
                "+".join(n for n in PER_USE if n in sys.modules) or "no per-use module",
                getattr(globals().get("web"), "busy", "-"),
                globals()["ship"].ble.state if "ship" in globals() else "-")
            where[0] += "; stage " + str(getattr(globals().get("lvship"), "heap_stage", "-"))
            where[0] += "; injection " + str(duel_injecting[0])
        except Exception as e:
            where[0] = "? %r" % (e,)
    return m


def critical_duel(j):
    if duel_worst[0] is None:
        games, rejects = j["g"], j.get("e", [])
        session = ship.ble.sess
        assert isinstance(session, lvlive.Session) and session.to == 1 and w.links
        assert duel_held[0] and not web.radio_hold and "lvliveapi" not in sys.modules
        # The forced real-radio move commits after the live stream releases it;
        # rule evaluation must finish before persistence holds its buffers.
        assert "lvduelrx" not in sys.modules
        assert "lvduel" not in sys.modules
        assert "lvduelmaint" not in sys.modules
        assert "lvliveops" not in sys.modules
        assert "lvduelother" not in sys.modules
        assert len(ship.live.out) == 24 and all(o[1][0] == 2 for o in ship.live.out)
        assert len(games) == 3 and all(g["s"] == "active" and g["n"] >= 68 and
               len(g["h"]) == 2 * g["n"] and g.get("q") for g in games)
        assert len(rejects) == 7 and len(j["r"]) == 7 and all(
            g.get("o") and g.get("rj") and [z[0] for z in g.get("q", ())] == [6, 7, 8] for g in rejects)
        duel_worst[0] = (tuple(g["n"] for g in games),
                         sum(len(g.get("q", ())) for g in games + rejects), 24)
        sample()
        peer_link.sh.web.radio_hold = False


def stream_sample():
    # Release the peer only inside the live response's streaming callback.
    # Its HELLO carries the shot through fake GATT and the actual Session._msg.
    if DUEL and not duel_held[0] and not duel_injecting[0] and "lvliveapi" in sys.modules:
        duel_injecting[0] = True
        try:
            before = ship.live.n["in"]
            held_before = ship.live.n["held"]
            ship.ble.next_scan = w.now + 120000
            for i in range(12000):
                w.step(10)
                peer.poll(w.now)
                ship.ble.poll(w.now)
                if ship.live.n["held"] > held_before:
                    duel_held[0] = True
                    break
            assert duel_held[0] and ship.live.n["in"] == before
            assert len(ship.live.out) == 24 and all(o[1][0] == 2 for o in ship.live.out)
            assert web.radio_hold and "lvduelrx" not in sys.modules
        finally:
            ship.ble.next_scan = w.now
            duel_injecting[0] = False
    return sample()


import bluetooth                    # noqa: E402  (the fake)
m_fake = mem()
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
m_code = mem()

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
        data = DATA + "-peer"

        def say(self, s):
            pass
    try:
        os.mkdir(DATA + "-peer")
    except OSError:
        pass
    for n in ("live.json", "livebox.json", "fault.json", "duel.json"):
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
m_peer = mem()
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
m_ship = mem()

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
    web = lvweb.Server(ship, root=ROOT, say=lambda s: print(s) if s.startswith("http:") else None)
    lvweb.probe = stream_sample
    g = MAIN_PY
    g["home_screen"](lvweb)
    if OTA or DUEL:
        g["ota_hooks"](lvweb, web)
        ship.led_pin = TestPin         # Test light (board/lvledtest.py): the LED, counted
    if BAT:
        chg_watch[0] = g["charger_watch"]
    src = g = None
    gc.collect()
    handler = web.handle
    if LIVE:
        for n in ("live.json", "livebox.json", "fault.json", "hail.json", "duel.json"):
            try:
                os.remove(DATA + "/" + n)
            except OSError:
                pass
        if SEED:
            seed_hails(DATA + "/hail.json")
            print("live: hail.json seeded with a full day (12 sent, 16 received)")
        lvlive.install(ship, DATA)            # as main.py's run() does
        if DUEL:
            import lvduel
            seed_duels(ship.live, peer_link)
            # The peer is busy receiving until the deferred shot commits. Its
            # unacknowledged receipts keep all 24 real outbox entries resident
            # across the first held session and its retry, not only the stream.
            peer_link.sh.web = HailSes()
            peer_link.sh.web.radio_hold = True
            peer_link.sh.web.busy = 0
            # The peer's 69th shot is held until the first streamed live response.
            assert lvduel.action(peer_link, {"action": "fire", "to": 0, "cell": 34})[0] == 200
            shot = next(o for o in peer_link.out if o[1][0] == 5)
            DUEL_M[0] = bytes((lvlive.MARK, 1)) + shot[1]
            # Do not deliver before a phone's streamed /api/live. The first
            # probe takes it and samples lvduel while all of its state is live.
            ship.duel_probe = critical_duel
            lvship.heap_probe = sample
            shot = lvduel = None
            # seed_duels was defined before the gc baseline: retain its code so
            # dropping test-only bytecode cannot artificially lower board peak.
            lvship.drop("lvduel")
            lvship.drop("lvlivein")
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


def duel_progress():
    # Test peer automation only; every local transition still uses phone HTTP.
    if duel_peer_stage[0] >= 2:
        try:
            with open(DATA + "/duel-phase") as f:
                phase = f.read()
            if phase != duel_phase[0]:
                duel_phase[0] = phase
                with open(DATA + "/duel-phase-ack", "w") as f:
                    f.write(phase)
        except OSError:
            pass
        return
    # The independent test peer cannot advance while its prior frames await
    # ACKs. Do not repeatedly parse its private transcript in that interval:
    # this is peer automation, not work the board under measurement performs.
    if peer_link.out:
        return
    import lvduel as D
    try:
        remote = D.box(peer_link)["g"][0]
        if duel_peer_stage[0] == 0 and remote["n"] == 70 and remote["s"] == "active" and not peer_link.out:
            duel_phase[0] = "terminal"
            assert D.action(peer_link, {"action": "fire", "to": 0, "cell": 35})[0] == 200
            duel_peer_stage[0] = 1
        if duel_peer_stage[0] == 1 and remote["s"] == "done":
            local = D.box(ship.live)["g"][0]
            if local["s"] == "done":
                assert local["n"] == remote["n"] == 71
                assert len(local["h"]) == len(remote["h"]) == 142
                assert local.get("verified") and remote.get("verified")
                assert local.get("counted") and remote.get("counted")
                duel_terminal[0] = (local["n"], remote["n"], local["verified"], remote["verified"])
                try:
                    os.stat(DATA + "/duel-rematch")
                except OSError:
                    return
                duel_phase[0] = "new-invite"
                assert D.action(peer_link, {"action": "new", "to": 0})[0] == 200
                assert D.action(peer_link, {"action": "invite", "to": 0, "layout": [[0, 0], [12, 0], [35, 0]]})[0] == 200
                duel_peer_stage[0] = 2

    finally:
        D = None
        lvship.drop("lvduel")
        lvship.drop("lvlivein")


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
    if PHONE and LIVE:
        # Deterministic shared-pin precondition: a real Hail playback owns it
        # before the Test-light client connects (independent of quiet hours).
        import lvflick
        assert lvflick.start(ship)
        lvflick = None
        lvship.drop("lvflick")
    if PHONE:
        print("PORT %d" % port)
        ready_started = lvship.ticks_ms()
        while web.served < 2 or (DUEL and not duel_held[0]):
            if lvship.ticks_diff(lvship.ticks_ms(), ready_started) > 30000 or done_flag():
                raise RuntimeError("duel: first measured live stream never accepted its move")
            # Duel admission is exercised before the radio can free receipt
            # slots: full outbox + three durable intent lists must coexist with
            # the streamed response, not vanish during unrelated phone logins.
            await lvship.sleep_ms(5)
    t = 0
    duel_progress_due = 1000
    bat_due = 1000
    phones_done = not PHONE
    started = lvship.ticks_ms()
    diagnostic_due = started + 15000
    # Light ownership/OTA admission can outlast ten accelerated radio minutes.
    # Keep polling and sampling until every client finishes; never truncate the workload.
    while t < (600000 if PHONE else 120000) or (PHONE and not phones_done):
        if PHONE and lvship.ticks_diff(lvship.ticks_ms(), started) > 180000:
            raise RuntimeError("phone workload did not finish within 180 s")
        if DUEL and lvship.ticks_diff(lvship.ticks_ms(), diagnostic_due) >= 0:
            print("duel: radio time %d, states %s/%s, queues %d/%d, HTTP %d, phase %s" %
                  (t, ship.ble.state, peer.state, len(ship.live.out), len(peer_link.out), web.served, duel_phase[0]))
            print("duel: admission %s/%s, receive %s/%s, dial %s/%s" %
                  (web.busy, web.radio_hold, ship.live.n["held"], peer_link.n["held"],
                   ship.live.n["dial"], peer_link.n["dial"]))
            diagnostic_due = lvship.ticks_ms() + 15000
        w.step(10)
        t += 10

        ship.ble.poll(w.now)
        peer.poll(w.now)
        if DUEL and duel_worst[0] is not None:
            duel_taken[0] = True
        if DUEL and t >= duel_progress_due and not web.busy and ship.ble.state == peer.state == "idle":
            duel_progress()
            duel_progress_due = t + 1000
        if LED:
            ship.led.poll(ship.ble.busy())
        if BAT and t >= bat_due and not ship.ble.busy() and not (WEB and web.busy > 0):
            ship.bat_poll()                  # as lvship's loop does, only while nothing is busy
            bat[1] += 1
            bat_due = t + 1000
        if t % 50 == 0:
            sample()
            await lvship.sleep_ms(1 if PHONE else 0)
            if not phones_done:
                phones_done = done_flag()
                if not phones_done:
                    during[0] = web.served
        # Done when the peer has everything (with phones: their taps too, once they've left).
        if phones_done and peer.node.digest() == ship.node.digest() and ship.ble.state == "idle" \
                and peer.state == "idle" and (not LIVE or (not peer_link.out and
                    (not ship.live.out or (DUEL and not any(o[0] == 1 for o in ship.live.out))))):
            break
    if PHONE:
        # Hail can leave the peer in a session/cooldown longer than one scan.
        # Settle until a fresh, matching advert is actually observed, not merely
        # until a fixed amount of fake radio time has passed. Keep the age assertion.
        for i in range(30000):
            w.step(10)
            ship.ble.poll(w.now)
            peer.poll(w.now)
            if i % 5 == 0:
                sample()
                q = ship.ble.peers.get(1)
                if i >= 6000 and q is not None and q.diff_since is None and 0 <= ship.ble._swept - q.seen <= 10000:
                    break
            if i % 50 == 0:
                await lvship.sleep_ms(1)
        # (not sampled: the phones' own /api/state calls during the sync are, above)
        air[0] = web.phone.state_body(0, 39, ship.clock.minute())["air"]
        bat[0] = web.phone.state_body(0, 39, ship.clock.minute())["bat"]
        gc.collect()
    if LED:
        # A faster phone/radio workload can finish while the initial Hail still
        # owns the pin (up to its 30 s wait plus 10 s playback). Observe that
        # real task releasing ownership before testing the notifier's pattern.
        # Keep sampling throughout; neither the heap nor pin-write gate changes.
        release_started = lvship.ticks_ms()
        while getattr(ship, "ledtest", None) is not None:
            if lvship.ticks_diff(lvship.ticks_ms(), release_started) > 45000:
                raise RuntimeError("light playback did not release the notifier")
            ship.led.poll(False)
            await lvship.sleep_ms(50)
            sample()
        if ship.led.enabled:
            ship._led("test")
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
# The notifier wrote its own pattern (6+ writes) in every mode, OTA+LIVE too: a hail's
# flicker or Test light owns the pin only for its own seconds, not the run (0.3.0 review 2
# n1: review 1 had let OTA+LIVE pass on Test light's writes alone).
led_ok = (ship.led.enabled and ship.led.writes >= 6 if lvship.game_fw() or "--force" in sys.argv else
          not ship.led.enabled and ship.led.writes == 0) if LED else (not ship.led.enabled and ship.led.writes == 0)
ok = (synced and http_ok[0] and led_ok and
      (base == 0 or BITS == 64 or (0 < board < CAP)))
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
          peak[0], got, t, m_peer_end, board, " (cap %d B applies to the 32-bit Pico)" % CAP if BITS == 64 else " of the %d B cap" % CAP,
          m_main))
print("heap: the peak came with %s" % where[0])
print("heap: board peak by moment: %s" % ", ".join("%s %d B" % (k, kpeak[k] - m_peer_end - m_fake) for k in sorted(kpeak)))
if EVERYONE and BITS == 32:
    print("heap: the everyone-plays season: %d B to spare under the %d B cap" % (CAP - board, CAP))
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
    # Two patterns: each has 6 blink edges, 6 breath edges and the final off (26 writes).
    # With the radio quiet the breaths are PWM steps (hundreds of writes): 200 required, as
    # before review 1 (0.3.0 review 2 n1). With Hail's radio and phones busy (--live) the
    # task gets fewer turns and a breath can collapse to its solid middles, so 26 there;
    # tests/test_ledtest.py checks the PWM breaths themselves (>=100 writes each).
    lt_min = 26 if LIVE else 200
    lt_ok = TestPin.n >= lt_min and "lvledtest" not in sys.modules
    ok = ok and lt_ok
    print("test light: pin writes %d (at least %d), lvledtest %s: %s" % (
        TestPin.n, lt_min, "loaded" if "lvledtest" in sys.modules else "dropped", "ok" if lt_ok else "FAIL"))
if LIVE:
    # Hail both ways over the same syncs: the phone's to the peer acked back to this ship, the
    # peer's to this one taken (and acked); nothing refused as bad, lvliveapi dropped.
    L = ship.live
    PL = peer_link
    # The two absent opponents retain exactly their bounded durable SYNCs.
    # They are part of the measured workload, never silently discarded to pass.
    # The six absent crewmates' stubs keep their ANSWER, REVEAL and END queued.
    absent_ok = (DUEL and len(L.out) == 20 and
                 sum(o[1][0] == 9 and o[0] in (2, 3) for o in L.out) == 2 and
                 all(sorted(o[1][0] for o in L.out if o[0] == to and o[1][5] == 0x52) == [6, 7, 8]
                     for to in range(2, 8)))
    lv_ok = (L is not None and PL is not None and L.n["in"] >= 1 and PL.n["in"] >= 1 and (not L.out or absent_ok)
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
if DUEL:
    import json
    with open(DATA + "/duel.json") as f:
        dg = json.load(f)["g"]
    duel_ok = (duel_taken[0] and duel_worst[0] is not None and duel_terminal[0] == (71, 71, 1, 1) and len(dg) == 3 and
               all(g["n"] == 70 and len(g["h"]) == 140 and g["s"] == "active" and
                   g["p"] is None and not g.get("q") for g in dg if g["to"] in (2, 3)) and
               next(g for g in dg if g["to"] == 1)["s"] == "draft" and
               "lvduel" not in sys.modules and absent_ok)
    ok = ok and duel_ok
    print("duel: measured concurrent transcripts/obligations/outbox %s; final shots %s; "
          "move deferred by /api/live then committed %s, rules dropped %s: %s" % (
              duel_worst[0], [g["n"] for g in dg], duel_taken[0],
              "lvduel" not in sys.modules, "ok" if duel_ok else "FAIL"))
    print("duel: terminal mutual transcript verification %s; phone accept/resign/new: %s" % (duel_terminal[0], "ok" if duel_ok else "FAIL"))
print("led: notifier %s, pin writes %d" % ("on" if ship.led.enabled else "off (default)", ship.led.writes))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
