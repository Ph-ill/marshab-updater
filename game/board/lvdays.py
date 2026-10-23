# Each day's story (State.out, 8-byte entries) kept for the phones' story log, and which
# past days a late record rewrote ("log updated" on the page). lvship.Ship feeds it as it
# tells each day (Ship(..., days=Days(...))); lvphone streams it. Only the board serving
# the phone game keeps it (main.py), so a bench board on stock MicroPython doesn't pay.
from lv import ops as O


def visible(out):
    """The story entries the page shows (routine chores are folded into one line)."""
    keep = bytearray()
    for i in range(0, len(out), 8):
        e = out[i:i + 8]
        if not (e[1] == O.O_ACT and e[6] == 1 and e[4] != 0):
            keep += e
    return bytes(keep)


class Days:
    """Every day's story entries (st.out), for the phones' story log. With a data folder
    they live in a file (data/days.bin, appended as days are told, rewritten on boot), so
    the season's ~5 KB of story isn't on the heap; only (offset, length) per day is.
    ref(d) is a handle that stays readable while the story changes (a phone half-way
    through reading it): old versions stay in the file until nobody is reading."""

    def __init__(self, path=None):
        self.path = path
        self.idx = {}              # day -> bytes (no file) or (offset, length)
        self.updated = {}          # day -> the flight day it was rewritten by a late record
        self.size = 0
        self.readers = 0
        if path:
            try:
                open(path, "wb").close()
            except OSError:
                self.path = None

    def get(self, d):
        r = self.idx.get(d)
        return None if r is None else self.load(r)

    def ref(self, d):
        return self.idx.get(d, b"")

    def load(self, r):
        if not isinstance(r, tuple):
            return r
        with open(self.path, "rb") as f:
            f.seek(r[0])
            return f.read(r[1])

    def length(self, d):
        r = self.idx.get(d, b"")
        return r[1] if isinstance(r, tuple) else len(r)

    def put(self, d, b, today):
        """Day d's story is b, told (or retold) on flight day `today`. A day is flagged
        "updated" only if a phone would read something different: rewritten after that day
        ended, and a line the page shows changed (as sim/mockserver.py)."""
        if today > d and d in self.idx:
            old = self.get(d)
            if old != b and visible(old) != visible(b):
                self.updated[d] = today
        if not self.path:
            self.idx[d] = b
            return
        live = 0
        for r in self.idx.values():
            live += r[1]
        if self.readers == 0 and self.size > 4096 and self.size > 3 * live:
            self._compact()
        with open(self.path, "ab") as f:
            f.write(b)
        self.idx[d] = (self.size, len(b))
        self.size += len(b)

    def _compact(self):
        keep = [(d, self.load(self.idx[d])) for d in sorted(self.idx)]
        self.idx = {}
        self.size = 0
        with open(self.path, "wb") as f:
            for d, b in keep:
                f.write(b)
                self.idx[d] = (self.size, len(b))
                self.size += len(b)
