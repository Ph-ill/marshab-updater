# Crew codes, sign-in lockout and "remember this phone for today".
#
# Phill sets every crew member's 4-digit code once, in the updater's ship setup, and the
# same codes go onto all seven ships (people wander between hotspots). The board holds
# data/crew.json:
#
#   {"schema": 1, "salt": "<32 hex>", "codes": ["<64 hex>" or null, x7]}
#
# where each code is sha256(salt || crew byte || 4 ASCII digits). The hash only keeps the
# digits out of a casual file listing: there are 10,000 codes, so anyone holding the file
# can recover them in a moment. The lockout below is what slows down guessing at the page.
#
# Runs on CPython and MicroPython. Time is the board's own monotonic milliseconds
# (time.ticks_ms on the Pico), never the phone's clock, so a phone can't wind a lockout
# away. A restart clears lockouts and remembered phones; both are cheap to redo.
try:
    import hashlib
except ImportError:  # pragma: no cover
    import uhashlib as hashlib
try:
    from binascii import hexlify, unhexlify
except ImportError:  # pragma: no cover
    from ubinascii import hexlify, unhexlify

N = 7
MAX_TRIES = 5            # wrong codes in a row before a lockout
LOCK_MS = 5 * 60 * 1000  # how long the lockout lasts
MAX_PHONES = 16          # remembered phones per ship (the hotspot takes 4 at a time)

OK = 0
WRONG = 1      # value: tries left before a lockout
LOCKED = 2     # value: seconds until the next try is allowed
NO_CODE = 3    # Phill hasn't set a code for this crew member
BAD = 4        # not a crew number / not four digits


def digest(salt, crew, code):
    """salt: bytes, crew: 0-6, code: '0000'-'9999'. Returns 64 lower-case hex chars."""
    h = hashlib.sha256(salt + bytes([crew]) + code.encode())
    return hexlify(h.digest()).decode()


try:
    from time import ticks_add as _add, ticks_diff as _diff  # MicroPython: ticks wrap around
except ImportError:
    def _add(a, b):
        return a + b

    def _diff(a, b):
        return a - b


class CodeBook:
    def __init__(self, cfg):
        self.salt = unhexlify(cfg["salt"])
        codes = list(cfg.get("codes") or [])
        self.codes = [(codes[c] if c < len(codes) else None) for c in range(N)]
        self.fails = [0] * N
        self.until = [None] * N     # ticks_ms when the lockout ends
        self.phones = []            # [key, crew, day], oldest first
        self.seen = [False] * N     # signed in at least once since boot (for "meet")

    def is_set(self, crew):
        return 0 <= crew < N and bool(self.codes[crew])

    def check(self, crew, code, now):
        """-> (status, value). Wrong tries count per crew member, whichever phone sends them."""
        if not (isinstance(crew, int) and 0 <= crew < N):
            return BAD, 0
        if not (isinstance(code, str) and len(code) == 4 and code.isdigit()):
            return BAD, 0
        if not self.codes[crew]:
            return NO_CODE, 0
        u = self.until[crew]
        if u is not None:
            left = _diff(u, now)
            if left > 0:
                return LOCKED, (left + 999) // 1000
            self.until[crew] = None
            self.fails[crew] = 0
        if digest(self.salt, crew, code) == self.codes[crew]:
            self.fails[crew] = 0
            return OK, 0
        self.fails[crew] += 1
        if self.fails[crew] >= MAX_TRIES:
            self.until[crew] = _add(now, LOCK_MS)
            return LOCKED, LOCK_MS // 1000
        return WRONG, MAX_TRIES - self.fails[crew]

    # -- remembered phones ---------------------------------------------------------------
    # key is whatever the server can see that stays put for a day: the phone's IP on the
    # hotspot (the DHCP server hands a returning MAC its old address) plus its User-Agent.
    def remember(self, key, crew, day):
        self.forget(key)
        self.phones.append([key, crew, day])
        if len(self.phones) > MAX_PHONES:
            self.phones.pop(0)

    def recall(self, key, day):
        """The crew member this phone signed in as today, or None. Yesterday's entries go."""
        self.phones = [p for p in self.phones if p[2] == day]
        for p in self.phones:
            if p[0] == key:
                return p[1]
        return None

    def forget(self, key):
        self.phones = [p for p in self.phones if p[0] != key]


def make_config(codes, salt):
    """codes: list of 7 '0000'-'9999' strings or None. For tests, the mock and tools."""
    return {"schema": 1, "salt": hexlify(salt).decode(),
            "codes": [digest(salt, c, k) if k else None for c, k in enumerate(codes)]}
