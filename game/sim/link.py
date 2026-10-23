# In-memory transport for lv/sync.py: two Sessions wired together, with faults on demand.
# The tests use it to drive the sync protocol without a radio (tests/test_sync.py).
from lv.sync import RUN


class LoopLink:
    """In-memory transport: two Sessions wired together, for the simulator and tests.
    fault(chunk, to) returns a list of (delay in steps, chunk) to deliver: [] drops it,
    two entries duplicate it, different delays reorder. cut=N: the link dies after N
    chunks (a mid-transfer disconnect)."""

    def __init__(self, a, b, fault=None):
        self.s = (a, b)
        self.fault = fault
        self.wire = [[], []]      # [due step, chunk] in flight towards a, towards b
        self.chunks = 0

    def run(self, now=0, step=10, limit=4000, cut=None):
        a, b = self.s
        for t in range(limit):
            now += step
            for side in (0, 1):
                to = 1 - side

                def send(c, to=to, t=t):
                    self.chunks += 1
                    if cut is not None and self.chunks > cut:
                        return True     # the link is gone; chunks vanish
                    for d, x in (self.fault(c, to) if self.fault else [(0, c)]):
                        self.wire[to].append((t + d, x))
                    return True
                self.s[side].pump(send, now)
            for side in (0, 1):
                w = self.wire[side]
                self.wire[side] = [e for e in w if e[0] > t]
                for e in w:
                    if e[0] <= t:
                        self.s[side].feed(e[1], now)
            if a.state != RUN and b.state != RUN and not a.q and not b.q:
                break
        return now
