# The heap one ship needs with BLE sync running, measured as on the board.
# Runs under MicroPython (unix port, 32- and 64-bit) and CPython (no numbers), from game/:
#
#   micropython -X heapsize=160k tests/mp_sync_heap.py [dir with .mpy files]
#
# One ship as on the board: the lv modules and board/lvship.py, the pack, the whole season
# in the log, the story replayed to the last day, BLE sync (lv/ble.py on the fake radio
# from tests/fakeble) and the status server answering one request over a real socket.
# It syncs a peer that missed almost the whole season (221 records over the link). The
# live heap (after gc) is sampled through all of it. The board's share must stay under
# 80 KB (80,000 B): the peak, less the fake radio module and the peer at its largest
# (see below). The LED stays off.
# With a directory of .mpy files first on the path (tools/board_build.sh makes one),
# the code comes precompiled, as on the board. With "frozen" instead, the interpreter
# must have the game frozen in (tools/build_firmware.sh unix32, the same manifest as the
# Pico firmware): nothing of the game is loaded from files, the pack included.
import sys
import gc

FROZEN = len(sys.argv) > 1 and sys.argv[1] == "frozen"
if FROZEN:
    for p in ("", "."):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, "tests/fakeble")
else:
    if len(sys.argv) > 1:
        sys.path.insert(0, sys.argv[1])
    sys.path.insert(1 if len(sys.argv) > 1 else 0, "tests/fakeble")
    sys.path.append("board")
    sys.path.append(".")
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
ship = lvship.Ship(cfg, root="build/", data=None, ble=w.new(), say=lambda s: None)
for i in range(NREC):
    ship.node.merge([RAW[i * R.LEN:(i + 1) * R.LEN]])
ship.tick_to(42)
RAW = None
WANT = ship.node.digest()
m_ship = sample()

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

http_ok = [False]


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


async def heap_run():
    srv = None
    port = 18000 + (gc.mem_free() % 997 if hasattr(gc, "mem_free") else 0)
    for i in range(20):
        try:
            srv = await asyncio.start_server(ship.http, "127.0.0.1", port + i)
            port += i
            break
        except OSError:
            pass
    sample()
    if srv:
        await client(port)
    t = 0
    while t < 120000:
        w.step(10)
        t += 10
        ship.ble.poll(w.now)
        peer.poll(w.now)
        if t % 50 == 0:
            sample()
            await lvship.sleep_ms(0)
        if peer.node.digest() == WANT and ship.ble.state == "idle" and peer.state == "idle":
            break
    if srv:
        srv.close()
    return t


t = asyncio.run(heap_run())
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
ok = (synced and http_ok[0] and not ship.led.enabled and ship.led.writes == 0 and
      (base == 0 or BITS == 64 or (0 < board < 80000)))
if FROZEN:
    # a frozen module's __file__ has no directory part (from board/ it would be board/...)
    ok = ok and ship.pack_src == "frozen" and "/" not in getattr(lvship, "__file__", "")
print("impl %s %d-bit; code from %s, pack from %s" % (sys.implementation.name, BITS,
      getattr(lvship, "__file__", "frozen"), ship.pack_src))
print("heap: fake radio module %d, code (lvship + lv incl. sync, ble) %d, peer %d, ship with the whole season "
      "and the story at day 42 %d" % (m_fake, m_code - m_fake, m_peer - m_code, m_ship - m_peer))
print("heap: peak live %d B while syncing (peer got %d records in %d ms of radio time); peer and fake world at the end %d; "
      "board peak (peak - peer - fake radio) %d B%s" % (peak[0], got, t, m_peer_end, board, " (cap 80,000 B applies to the 32-bit Pico)" if BITS == 64 else " of the 80,000 B cap"))
print("http: status server %s, phone clock learned %s" % ("answered" if http_ok[0] else "NOT answered",
                                                           ship.clock.known()))
print("led: notifier %s, pin writes %d" % ("on" if ship.led.enabled else "off (default)", ship.led.writes))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
