# Ship state: a handful of fixed-size bytearrays, so RAM use doesn't grow with play.
# The only growing parts are `out` (8 bytes per story entry) and `pend` (open votes).
# dump() is the canonical byte form: it is what snapshots store and what the
# determinism tests hash.
try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256

from lv import ops as O
from lv.prng import Rng, day_seed

N = 8  # ships = crew; every per-crew array, the bond matrix and dil_seen's bit-per-crew byte fit 8
OFF = 128  # signed values are stored +128


class State:
    def __init__(self, pack=None):
        self.day = 0
        self.loc = bytearray(N)         # ship each crew member is aboard
        self.cond = bytearray(N)        # ops.COND_*
        self.morale = bytearray(N)      # 0..100
        self.traits = bytearray(3 * N)  # crew*3 + axis, -100..100 stored +128
        self.bonds = bytearray(N * N)   # symmetric, -100..100 stored +128
        self.res = bytearray(3)         # food, fuel, spares
        self.medkit = bytearray(N)      # per ship
        self.flags = bytearray(16)      # 128 story flags
        self.vars = bytearray(32)       # 32 counters or day marks, 0..255
        self.last_seen = bytearray(N)   # last flight day each owner acted (0 = never)
        self.dil_given = bytearray(N)   # private dilemmas offered per player
        self.spot = bytearray(N)        # story appearances per crew (role A or B), for fair casting
        self.fired = bytearray(0)       # per card: last day it fired (0 = never)
        self.dil_seen = bytearray(0)    # per card: bit per crew that was offered this dilemma
        self.pend = []                  # open items: bytes(type, card, open, close, A, B, C, D)
        self.out = bytearray()          # today's story entries, 8 bytes each
        self.chain = bytes(8)           # running hash of every earlier day's story
        self.ending = O.NONE
        if pack is not None:
            self.setup(pack)

    def setup(self, pack):
        rng = Rng(day_seed(pack.voyage_key, 0, 1))
        self.fired = bytearray(pack.ncards)
        self.dil_seen = bytearray(pack.ncards)
        self.res[:] = pack.res0
        for s in range(N):
            self.loc[s] = s
            self.morale[s] = 60
            self.medkit[s] = pack.medkits
            q = pack.quirks[pack.crew_quirk[s]]
            for a in range(3):
                self.set_trait(s, a, q[a] + rng.below(21) - 10)
        for i in range(N * N):
            self.bonds[i] = OFF
        for i in range(N):
            for j in range(i + 1, N):
                self.add_bond(i, j, rng.below(11) - 5)

    # ---- accessors ------------------------------------------------------
    def trait(self, c, a):
        return self.traits[3 * c + a] - OFF

    def set_trait(self, c, a, v):
        self.traits[3 * c + a] = (100 if v > 100 else -100 if v < -100 else v) + OFF

    def add_trait(self, c, a, dv):
        self.set_trait(c, a, self.trait(c, a) + dv)

    def bond(self, i, j):
        return self.bonds[i * N + j] - OFF

    def add_bond(self, i, j, dv):
        if i == j:
            return
        v = self.bond(i, j) + dv
        v = (100 if v > 100 else -100 if v < -100 else v) + OFF
        self.bonds[i * N + j] = v
        self.bonds[j * N + i] = v

    def add_morale(self, c, dv):
        v = self.morale[c] + dv
        self.morale[c] = 100 if v > 100 else 0 if v < 0 else v

    def add_res(self, r, dv):
        v = self.res[r] + dv
        self.res[r] = 255 if v > 255 else 0 if v < 0 else v

    def add_spot(self, roles):
        for k in (0, 1):
            c = roles[k]
            if c < N and self.spot[c] < 255:
                self.spot[c] += 1

    def flag(self, f):
        return (self.flags[f >> 3] >> (f & 7)) & 1

    def set_flag(self, f, on):
        if on:
            self.flags[f >> 3] |= 1 << (f & 7)
        else:
            self.flags[f >> 3] &= ~(1 << (f & 7)) & 255

    def emit(self, code, card=O.NONE, a=O.NONE, b=O.NONE, c=O.NONE, d=O.NONE, e=O.NONE):
        self.out += bytes((self.day, code, card & 255, a & 255, b & 255, c & 255, d & 255, e & 255))

    # ---- canonical form ----------------------------------------------------
    def dump(self):
        parts = [b"LVS1", bytes((self.day, self.ending, len(self.pend), len(self.fired))),
                 self.loc, self.cond, self.morale, self.traits, self.bonds, self.res,
                 self.medkit, self.flags, self.vars, self.last_seen, self.dil_given, self.spot, self.fired, self.dil_seen]
        parts += self.pend
        n = len(self.out)
        parts.append(self.chain)
        parts.append(bytes((n & 255, n >> 8)))
        parts.append(self.out)
        return b"".join(parts)

    @classmethod
    def load(cls, data):
        s = cls()
        data = bytes(data)
        if data[:4] != b"LVS1":
            raise ValueError("bad snapshot")
        s.day, s.ending, npend, nfired = data[4:8]
        p = 8
        for name, ln in (("loc", N), ("cond", N), ("morale", N), ("traits", 3 * N),
                         ("bonds", N * N), ("res", 3), ("medkit", N), ("flags", 16),
                         ("vars", 32), ("last_seen", N), ("dil_given", N), ("spot", N), ("fired", nfired), ("dil_seen", nfired)):
            setattr(s, name, bytearray(data[p:p + ln]))
            p += ln
        s.pend = []
        for _ in range(npend):
            s.pend.append(bytes(data[p:p + 8]))
            p += 8
        s.chain = data[p:p + 8]
        p += 8
        n = data[p] | (data[p + 1] << 8)
        p += 2
        s.out = bytearray(data[p:p + n])
        return s

    def close_day(self):
        # Fold today's story into the chain so the snapshot never grows with the season.
        self.chain = sha256(self.chain + self.out).digest()[:8]

    def digest(self):
        return sha256(self.dump()).digest()

    def hexdigest(self, n=8):
        import binascii
        return binascii.hexlify(self.digest()[:n]).decode()
