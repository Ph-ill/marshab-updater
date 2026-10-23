# Loads build/pack.bin (written by tools/lvc.py). Text never reaches the Pico's RAM:
# the pack holds only logic, and the phone renders text from text.json.
from lv import ops as O

try:
    from array import array
except ImportError:  # pragma: no cover
    from uarray import array

try:
    from collections import namedtuple
except ImportError:  # pragma: no cover
    from ucollections import namedtuple

# A card is just its index. Its 11-byte header stays in Pack.data and is read in place:
#   data[hdr[i] + H_TYPE] ... data[hdr[i] + H_LNEG]
# The only per-card RAM is three u16 offsets (header, effects, first option): 6 bytes,
# where a 16-field tuple per card cost ~170 B. The engine also gets the card lists it
# scans every day (events, beats, ...) as bytes built once here, so a tick allocates no
# per-card lists.
H_TYPE, H_WEIGHT, H_DMIN, H_DMAX, H_FLAGS, H_COOL, H_DUR, H_NROLES, H_LAXIS, H_LPOS, H_LNEG = range(11)
HDR = 11

# Card is kept for tools, the sim and the mock server (built on demand, never stored).
Card = namedtuple("Card", ("idx", "type", "weight", "dmin", "dmax", "flags", "cooldown",
                           "duration", "nroles", "laxis", "lpos", "lneg", "conds",
                           "effects", "nopt", "opt0"))
# conds, effects and opt0 are offsets into Pack.data, each pointing at an op-list:
# one count byte, then count x 4 bytes.


def _skip(buf, p):
    return p + 1 + 4 * buf[p]


class _Cards:
    # Read-only sequence of Card tuples, decoded on access (not used by the engine).
    def __init__(self, pack):
        self.p = pack

    def __len__(self):
        return self.p.ncards

    def __getitem__(self, i):
        if i < 0 or i >= self.p.ncards:
            raise IndexError(i)
        return self.p.card(i)

    def __iter__(self):
        for i in range(self.p.ncards):
            yield self.p.card(i)


class Pack:
    def __init__(self, data):
        if not isinstance(data, bytes):
            data = bytes(data)
        if data[:4] != b"LVP1":
            raise ValueError("not a Long Voyage pack")
        self.id = data[4:8]
        p = 8
        self.ncards, self.nflags, self.nvars, self.ncrew, self.season = data[p:p + 5]
        p += 5
        self.voyage_key = data[p:p + 8]
        p += 8
        self.res0 = bytes(data[p:p + 3])
        p += 3
        self.medkits = data[p]
        p += 1
        nq = data[p]
        p += 1
        self.quirks = []
        for _ in range(nq):
            t = []
            for i in range(3):
                v = data[p + i]
                t.append(v - 256 if v > 127 else v)
            self.quirks.append(t)
            p += 3
        self.crew_quirk = bytes(data[p:p + self.ncrew])
        p += self.ncrew
        n = self.ncards
        self.hdr = array("H", [0] * n)
        self.eff = array("H", [0] * n)
        self.opt0 = array("H", [0] * n)
        due, events, beats, hooks, decs, dils, ends = [], [], [], [], [], [], []
        for i in range(n):
            q = data[p] | (data[p + 1] << 8)
            p += 2
            self.hdr[i] = q
            t, f = data[q + H_TYPE], data[q + H_FLAGS]
            q = _skip(data, q + HDR)
            self.eff[i] = q
            self.opt0[i] = _skip(data, q) + 1
            if t == O.EVENT or t == O.BEAT:
                if f & O.F_DUE:
                    due.append(i)
                elif f & O.F_HOOK:
                    hooks.append(i)
                elif t == O.EVENT:
                    events.append(i)
                else:
                    beats.append(i)
            elif t == O.DECISION:
                decs.append(i)
            elif t == O.DILEMMA:
                dils.append(i)
            elif t == O.ENDING:
                ends.append(i)
        self.due, self.events, self.beats = bytes(due), bytes(events), bytes(beats)
        self.hooks, self.decisions = bytes(hooks), bytes(decs)
        self.dilemmas, self.endings = bytes(dils), bytes(ends)
        self.size = len(data)
        self.data = data
        self.cards = _Cards(self)

    def h(self, i, field):
        return self.data[self.hdr[i] + field]

    def conds(self, i):
        return self.hdr[i] + HDR

    def nopt(self, i):
        return self.data[self.opt0[i] - 1]

    def opt(self, i, k):
        # Offset of option k's effect list. Accepts a card index or a Card tuple.
        if not isinstance(i, int):
            i = i.idx
        q = self.opt0[i]
        for _ in range(k):
            q = _skip(self.data, q)
        return q

    def card(self, i):
        d, q = self.data, self.hdr[i]
        return Card(i, d[q], d[q + 1], d[q + 2], d[q + 3], d[q + 4], d[q + 5], d[q + 6],
                    d[q + 7], d[q + 8], d[q + 9], d[q + 10], q + HDR, self.eff[i],
                    d[self.opt0[i] - 1], self.opt0[i])

    def of_type(self, t):
        return [c for c in self.cards if c.type == t]


def load(path):
    with open(path, "rb") as f:
        return Pack(f.read())
