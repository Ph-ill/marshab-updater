# Loads build/pack.bin (written by tools/lvc.py). Text never reaches the Pico's RAM:
# the pack holds only logic, and the phone renders text from text.json.
from lv import ops as O


try:
    from collections import namedtuple
except ImportError:  # pragma: no cover
    from ucollections import namedtuple

# A card is an immutable tuple: MicroPython ignores __slots__, so a class instance would
# carry a member dict (~4x the RAM). A namedtuple is one flat block per card.
Card = namedtuple("Card", ("idx", "type", "weight", "dmin", "dmax", "flags", "cooldown",
                           "duration", "nroles", "laxis", "lpos", "lneg", "conds",
                           "effects", "nopt", "opt0"))
# conds, effects and opt0 are offsets into Pack.data, each pointing at an op-list:
# one count byte, then count x 4 bytes. Nothing is copied, so a card costs one tuple.


def _skip(buf, p):
    return p + 1 + 4 * buf[p]


class Pack:
    def __init__(self, data):
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
        offs = []
        for i in range(self.ncards):
            offs.append(data[p] | (data[p + 1] << 8))
            p += 2
        self.cards = []
        for i in range(self.ncards):
            q = offs[i]
            hdr = data[q:q + 11]
            q += 11
            conds = q
            q = _skip(data, q)
            effects = q
            q = _skip(data, q)
            nopt = data[q]
            q += 1
            c = Card(i, hdr[0], hdr[1], hdr[2], hdr[3], hdr[4], hdr[5], hdr[6], hdr[7],
                     hdr[8], hdr[9], hdr[10], conds, effects, nopt, q)
            self.cards.append(c)
        self.size = len(data)
        self.data = data

    def opt(self, card, i):
        # Offset of option i's effect list.
        q = card.opt0
        for _ in range(i):
            q = _skip(self.data, q)
        return q

    def of_type(self, t):
        return [c for c in self.cards if c.type == t]


def load(path):
    with open(path, "rb") as f:
        return Pack(f.read())
