# BLE sync through the real lv/ble.py code, on a fake radio (tests/fakeble/bluetooth.py).
# Runs under MicroPython (unix port, 32- and 64-bit) and CPython alike, from game/:
#
#   micropython -X heapsize=192k tests/mp_sync.py          (scenarios, then the heap check)
#   python3 tests/mp_sync.py
#
# Scenarios (each a fresh fake world; ships start with the records their own crew wrote):
#   clean     3 ships, nothing goes wrong
#   lossy     MTU 23 (every message in several chunks), 5 % of packets dropped, 5 %
#             duplicated, 10 % reordered
#   cut       the first 4 links drop after 6 packets each (mid-transfer disconnects)
#   fleet     5 radios: A, B, C real ships, A and C out of each other's range (C's records
#             reach A through B), B switched off for a while; an out-of-date ship on
#             another protocol, and a ship that advertises but never accepts a connection
# Each must end with every real ship holding the whole season (the digest of
# build/season_log.bin) inside the time limit, and nothing stuck in a session. After
# "fleet", ship A replays the season from what it got over the air and every flight day
# must match build/season_expect.txt.
#
# The heap a board needs is measured separately, in a fresh interpreter: mp_sync_heap.py.
import sys
import gc

sys.path.insert(0, "tests/fakeble")
sys.path.insert(0, "board")
sys.path.insert(0, ".")
gc.collect()
base = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 0

import bluetooth                    # noqa: E402  (the fake)
from lv import record as R          # noqa: E402
from lv import sync as S            # noqa: E402
from lv.chlog import ChoiceLog      # noqa: E402
from lv.ble import BleSync          # noqa: E402
from lv.pack import load            # noqa: E402  (imported first: compiling engine.py
from lv.state import State          # noqa: E402   is the biggest single allocation)
from lv.engine import Engine        # noqa: E402

FK = b"test-fleet-key-not-secret"
MP = sys.implementation.name == "micropython"


def mem():
    gc.collect()
    return (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1


m_code = mem()
with open("build/season_log.bin", "rb") as f:
    RAW = f.read()
NREC = len(RAW) // R.LEN


def full_digest():
    log = ChoiceLog(FK)
    for i in range(NREC):
        log.merge(RAW[i * R.LEN:(i + 1) * R.LEN])
    return log.digest()


WANT = full_digest()
FAST = {"scan_every_ms": 6000, "scan_ms": 3000}


class Board:
    def __init__(self, world, ship, authors, cfg=None):
        self.log = ChoiceLog(FK)
        for i in range(NREC):
            r = RAW[i * R.LEN:(i + 1) * R.LEN]
            if R.ship(r) in authors:
                self.log.merge(r)
        self.node = S.Node(self.log, ship, FK, 42)
        self.radio = world.new()
        c = dict(FAST)
        if cfg:
            c.update(cfg)
        self.sync = BleSync(self.node, self.radio, c)

    def poll(self, now):
        if self.radio.on:
            self.sync.poll(now)


def run(world, boards, limit_ms, events=None):
    t = 0
    while t < limit_ms:
        world.step(10)
        t += 10
        if events and t in events:
            events[t]()
        for b in boards:
            b.poll(world.now)
        if t % 1000 == 0 and all([b.node.digest() == WANT and b.sync.state == "idle" for b in boards]):
            return t
    return None


def show(name, t, world, boards):
    n = [b.sync.n for b in boards]
    tot = lambda k: sum([x[k] for x in n])   # noqa: E731
    print("%-6s converged=%s at %s ms; sessions ok %d fail %d; records sent %d got %d new %d; "
          "retries %d dups %d; radio %s" % (
              name, t is not None, t, tot("ok"), tot("fail"), tot("sent"), tot("got"), tot("new"),
              tot("retries"), tot("dups"),
              " ".join(["%s=%d" % (k, world.stats[k]) for k in sorted(world.stats)
                        if world.stats[k] and k != "adv_seen"])))
    return t is not None and all([b.sync.state == "idle" for b in boards])


def split3(world, cfg=None):
    return [Board(world, 0, (0, 3, 6, 15), cfg), Board(world, 1, (1, 4, 7), cfg),
            Board(world, 2, (2, 5), cfg)]


ok = True
res = {}

# clean
w = bluetooth.World(11)
bs = split3(w)
t = run(w, bs, 120000)
res["clean"] = show("clean", t, w, bs)

# lossy, small MTU
w = bs = None
gc.collect()
w = bluetooth.World(12)
w.drop, w.dup, w.reorder = 50, 50, 100
bs = split3(w, {"mtu": 23})
t = run(w, bs, 300000)
res["lossy"] = show("lossy", t, w, bs) and bs[0].sync.n["retries"] + bs[1].sync.n["retries"] > 0
assert w.stats["dropped"] and w.stats["duplicated"] and w.stats["reordered"]

# mid-transfer disconnects
w = bs = None
gc.collect()
w = bluetooth.World(13)
w.cut_after, w.cut_links = 6, 4
bs = split3(w)
t = run(w, bs, 300000)
res["cut"] = show("cut", t, w, bs) and w.stats["cut"] == 4 and sum([b.sync.n["fail"] for b in bs]) >= 4

# fleet: relay, power off, out-of-date and deaf ships
w = bs = None
gc.collect()
w = bluetooth.World(14)
w.drop, w.dup, w.reorder = 20, 20, 50
A = Board(w, 0, (0, 3, 6, 15))
B = Board(w, 1, (1, 4, 7))
C = Board(w, 2, (2, 5))
w.separate(A.radio, C.radio)
old = w.new()                                    # out-of-date firmware: protocol 9
p = bytearray(S.Node(ChoiceLog(FK), 5, FK).advert())
p[4] = 9
old.gap_advertise(1000000, adv_data=S.adv_data(bytes(p)))
deaf = w.new()                                   # stack wedged: advertises, never accepts
deaf.deaf = True
deaf.gap_advertise(1000000, adv_data=S.adv_data(S.Node(ChoiceLog(FK), 6, FK).advert()))
ev = {20000: lambda: w.power(B.radio, False), 90000: lambda: w.power(B.radio, True)}
bs = [A, B, C]
t = run(w, bs, 600000, ev)
pa = A.sync.peers
res["fleet"] = (show("fleet", t, w, bs) and 2 not in pa and pa[5].why == "protocol 9" and pa[6].fails > 0
                and pa[6].ok == 0 and t > 90000)
print("fleet: A heard ships %s; ship 6 (old) %r; ship 7 (deaf) fails %d, next try in %d s" % (
    sorted([k + 1 for k in pa]), pa[5].why, pa[6].fails, (pa[6].next_try - w.now) // 1000))

# The story from what A got over the air.
log = A.log
w = bs = B = C = old = deaf = None
A.sync = A.radio = None
gc.collect()
pack = load("build/pack.bin")
expect = [ln.strip() for ln in open("build/season_expect.txt") if ln.strip()]
st = State(pack)
bad = 0
for d in range(1, pack.season + 1):
    Engine(pack, st, log).tick()
    bad += st.hexdigest() != expect[d - 1]
res["story"] = bad == 0
print("story: ship A replayed %d days from records received over BLE, %d mismatches" % (pack.season, bad))
A = log = st = pack = expect = None
gc.collect()

for k in res:
    ok = ok and res[k]
print("impl", sys.implementation.name, "results", " ".join(["%s=%s" % (k, "ok" if res[k] else "FAIL")
                                                             for k in ("clean", "lossy", "cut", "fleet",
                                                                       "story")]))
print("RESULT", "PASS" if ok else "FAIL")
if not ok:
    sys.exit(1)
