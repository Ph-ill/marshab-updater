# Engagement layer check. Runs under MicroPython (unix port or a board) and CPython alike.
# Replays the reference season, then for every crew member works out drops, jobs, the
# streak, gifts and the waiting list, and hashes it all. CPython writes the expected hash
# (--write); MicroPython must produce the same one. Also drives the clock across the
# ticks_ms wrap and the LED notifier with a fake pin, and reports the peak heap with the
# story engine and the engagement layer loaded together.
#
#   micropython -X heapsize=160k tests/mp_engage.py      (from game/, after tests/run.sh)
import sys
import gc

sys.path.insert(0, ".")
gc.collect()
base = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 0
peak = [0]


def mem():
    gc.collect()
    m = (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1
    if m > peak[0]:
        peak[0] = m
    return m


try:
    import hashlib
except ImportError:
    import uhashlib as hashlib

from lv.pack import load            # noqa: E402
from lv.chlog import ChoiceLog      # noqa: E402
from lv.state import State          # noqa: E402
from lv.engine import Engine        # noqa: E402
from lv import record as R          # noqa: E402
from lv import engage as E          # noqa: E402
from lv.clock import Clock          # noqa: E402
from lv.led import Notifier         # noqa: E402

FLEET_KEY = b"test-fleet-key-not-secret"
m_code = mem()
pack = load("build/pack.bin")
table = E.load_table("build/engage.bin")
with open("build/season_log.bin", "rb") as f:
    raw = f.read()
log = ChoiceLog(FLEET_KEY)
for i in range(0, len(raw), R.LEN):
    log.merge(raw[i:i + R.LEN])
    if i % (32 * R.LEN) == 0:
        gc.collect()   # see ENGAGEMENT.md: without this a 192 KB heap can fragment
raw = None
st = State(pack)
eng = Engine(pack, st, log)
en = E.Engage(table, pack.voyage_key, pack.season)
local = E.Local(pack.season)
h = hashlib.sha256()
m_story = mem()
for d in range(1, pack.season + 1):
    eng.tick()
    for c in range(7):
        if d % 3 == c % 3:
            local.open(c, d)       # some crew open some drops
        minute = (d * 97 + c * 41) % 1440 if d % 5 else None
        keys = E.waiting(en, local, pack, st, log, c, minute)
        if (d + c) % 2:
            local.visit(c, keys)
        h.update(bytes(str(keys), "utf-8"))
        mem()
for c in range(7):
    h.update(en.drops(c))
    for d in range(1, pack.season + 1):
        h.update(bytes(str(en.job(c, d)), "utf-8"))
    a = E.active_days(log, c, pack.season)
    h.update(bytes(str(E.streak(a, pack.season)), "utf-8"))
    h.update(bytes(str(E.gifts(log, c, pack.season, table.ask_days)), "utf-8"))
    v = E.view(en, local, pack, st, log, c, 600)
    h.update(bytes(str(sorted(v["streak"]["days"])), "utf-8"))
    mem()
dump = local.dump()
h.update(dump)
ok = E.Local.load(dump).dump() == dump
m_all = mem()

# Clock across the 2^30 ticks_ms wrap, and the LED with a fake pin.
T = [0x3FFFFFFF - 5000]


def ticks():
    return T[0] & 0x3FFFFFFF


def tdiff(a, b):
    d = (a - b) & 0x3FFFFFFF
    return d - 0x40000000 if d & 0x20000000 else d


clk = Clock(ticks, tdiff)
noon = 1792843200000                    # 2026-10-24 12:00 UTC
clk.learn(noon, 0)
T[0] += 10000                            # wraps
ok = ok and clk.epoch_ms() == noon + 10000 and clk.minute() == 720


class Pin:
    def __init__(self):
        self.v = 0
        self.n = 0

    def value(self, v):
        self.v = v
        self.n += 1


pins = []
led = Notifier(clk, True, lambda: pins.append(Pin()) or pins[-1])
led.set_waiting(True)
on = 0
for step in range(0, 600000, 10):        # ten minutes in 10 ms steps
    T[0] += 10
    led.poll()
    on += led.lit
ok = ok and pins and 120 <= pins[0].n <= 280 and 10000 < on * 10 < 20000
digest = h.digest()
hexd = "".join("%02x" % b for b in digest[:8])
print("impl", sys.implementation.name)
print("engage table", table.size, "B; local file", len(dump), "B; LED writes in 10 min", pins[0].n if pins else 0)
print("code RAM", m_code, "story RAM", m_story, "with engagement", m_all, "peak heap in use", peak[0])
if "--write" in sys.argv:
    with open("build/engage_expect.txt", "w") as f:
        f.write(hexd + "\n")
    print("engage digest", hexd, "(written)")
else:
    want = open("build/engage_expect.txt").read().strip()
    print("engage digest", hexd, "expected", want)
    ok = ok and want == hexd
print("RESULT", "PASS" if ok else "FAIL")
