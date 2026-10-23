# Runs under MicroPython (unix port or a real board) and CPython alike.
# Replays build/season_log.bin from build/pack.bin and compares the state digest
# after every flight day with build/season_expect.txt written by CPython.
# It merges the log twice, in authored order and reversed, to show order doesn't matter.
#
#   micropython -X heapsize=128k tests/mp_check.py    (from game/; 64-bit unix port)
#   micropython32 -X heapsize=96k tests/mp_check.py   (32-bit build, like the Pico's)
import sys
import gc

sys.path.insert(0, ".")
try:
    import time
    ticks = time.ticks_ms
    diff = time.ticks_diff
except AttributeError:
    import time
    ticks = lambda: int(time.time() * 1000)  # noqa: E731
    diff = lambda a, b: a - b  # noqa: E731

gc.collect()
base = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 0

from lv.pack import load            # noqa: E402
from lv.chlog import ChoiceLog      # noqa: E402
from lv.state import State          # noqa: E402
from lv.engine import Engine        # noqa: E402
from lv import record as R          # noqa: E402

FLEET_KEY = b"test-fleet-key-not-secret"


def mem():
    gc.collect()
    return (gc.mem_alloc() - base) if hasattr(gc, "mem_alloc") else -1


m_code = mem()
pack = load("build/pack.bin")
m_pack = mem() - m_code
with open("build/season_log.bin", "rb") as f:
    raw = f.read()
# Kept as the one bytes object it was read as: the log packs what it merges (lv/chlog.py),
# so a list of 13-byte objects here would only measure the test, not the board.
n_recs = len(raw) // R.LEN
expect = [ln.strip() for ln in open("build/season_expect.txt") if ln.strip()]

ok = True
results = []
log = st = eng = seq = None
for order in ("authored", "reversed"):
    log = st = eng = seq = None
    m0 = mem()
    log = ChoiceLog(FLEET_KEY)
    seq = range(n_recs) if order == "authored" else range(n_recs - 1, -1, -1)
    t0 = ticks()
    bad = 0
    for i in seq:
        if log.merge(raw[i * R.LEN:(i + 1) * R.LEN]) <= 0:
            bad += 1
    t_merge = diff(ticks(), t0)
    m_log = mem() - m0
    st = State(pack)
    eng = Engine(pack, st, log)
    t0 = ticks()
    worst = 0
    mismatch = 0
    for d in range(1, pack.season + 1):
        t1 = ticks()
        eng.tick()
        dt = diff(ticks(), t1)
        if dt > worst:
            worst = dt
        if st.hexdigest() != expect[d - 1]:
            mismatch += 1
    t_season = diff(ticks(), t0)
    m_all = mem() - m0
    snap = st.dump()
    rt = State.load(snap).dump() == snap
    ok = ok and mismatch == 0 and bad == 0 and rt
    results.append((order, len(seq), bad, mismatch, t_merge, t_season, worst, m_log, m_all, len(snap), rt))

print("impl", sys.implementation.name, sys.version)
print("pack bytes", pack.size, "pack RAM", m_pack, "code RAM", m_code,
      "peak heap in use", mem())
for r in results:
    print("order=%s records=%d rejected=%d day_mismatches=%d merge_ms=%d season_ms=%d worst_tick_ms=%d "
          "log_RAM=%d log+state+engine_RAM=%d snapshot_bytes=%d snapshot_roundtrip=%s" % r)
print("final digest", st.hexdigest(), "expected", expect[-1])
print("RESULT", "PASS" if ok else "FAIL")
