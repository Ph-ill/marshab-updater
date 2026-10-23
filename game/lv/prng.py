# xorshift32 PRNG plus the per-day seed. Integer-only, identical on CPython and MicroPython.
# Note for rp2: values above 2**30 are heap-allocated ints on a 32-bit MicroPython, so each
# draw allocates a little. That's fine at a few hundred draws per flight day.
try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256

M32 = 0xFFFFFFFF


class Rng:
    def __init__(self, seed):
        s = seed & M32
        self.s = s if s else 0x9E3779B9

    def next(self):
        x = self.s
        x ^= (x << 13) & M32
        x ^= x >> 17
        x ^= (x << 5) & M32
        self.s = x
        return x

    def below(self, n):
        # Modulo bias is irrelevant here; determinism is what matters.
        return self.next() % n if n > 1 else 0

    def chance(self, pct):
        return self.next() % 100 < pct

    def weighted(self, weights):
        # Index chosen with probability weight / sum. Returns -1 if all weights are 0.
        tot = 0
        for w in weights:
            tot += w
        if tot <= 0:
            return -1
        r = self.next() % tot
        for i in range(len(weights)):
            r -= weights[i]
            if r < 0:
                return i
        return len(weights) - 1


def day_seed(voyage_key, day, salt=0):
    # First 4 bytes of SHA-256(voyage key + day + salt), little-endian.
    h = sha256(bytes(voyage_key) + bytes((day & 255, (day >> 8) & 255, salt & 255))).digest()
    return int.from_bytes(h[:4], "little")
