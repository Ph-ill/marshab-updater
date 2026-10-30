# Ed25519 signature check (RFC 8032) for over-the-air updates (lvota.py), in plain Python:
# runs on CPython (tests, tools/validate_firmware.py) and on MicroPython 1.29 with its
# arbitrary-precision ints (the rp2 port has no Ed25519 or SHA-512 of its own).
#
#   lvsig.verify(public_key_32_bytes, message, signature_64_bytes) -> True / False
#
# Verify only: the private key never leaves the release machine. The phone relays an
# update from GitHub; only a manifest signed with that key is accepted, so anyone else on
# the ship's hotspot can't push code to it (the repository is public, so a shared secret
# such as an HMAC key couldn't work). Callers sign a short message (lvota: a domain tag +
# the manifest's sha256), so SHA-512 runs over one or two 128-byte blocks.
#
# Checked: S < L (no malleable signatures), A and R decode to curve points (A, R with
# x = 0 and the sign bit set are rejected), then [S]B == R + [k]A with k = SHA-512(R|A|M)
# mod L, compared as encoded points (cofactorless, as RFC 8032 5.1.7 without the x8).
# One field inversion and one square root (both pow(), native mpz on the board); the
# double scalar multiplication is Straus' (Shamir's) method a bit at a time: 4 combinations
# of B and -A built per call, then 253 steps of a doubling + at most one addition.
# Extended twisted Edwards coordinates (Hisil et al. 2008), the a = -1 formulas.
# Not constant-time: it only ever handles public data.

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = 37095705934669439343138083508754565189542113879843219016388785533085940283555
D2 = D * 2 % P
SQRT_M1 = 19681161376707505956807079304988542015446066515923890162744021073123829784752
BX = 15112221349535400772501151409588531511454012693041857206046113283949847762202
BY = 46316835694926478169428394003475163141307993866256225615783033603165251855960
MASK = 2 ** 255 - 1
probe = None      # tests: called a few times inside verify() (the heap at its fullest)


def _red(x):
    # x mod P for 0 <= x < 2**510 without a long division: 2**255 = 19 (mod P).
    x = (x & MASK) + 19 * (x >> 255)
    x = (x & MASK) + 19 * (x >> 255)
    return x - P if x >= P else x


def _add(p, q):
    # Extended coordinates (X, Y, Z, T), x = X/Z, y = Y/Z, xy = T/Z. "add-2008-hwcd-3".
    X1, Y1, Z1, T1 = p
    X2, Y2, Z2, T2 = q
    a = _red((Y1 - X1) % P * ((Y2 - X2) % P))
    b = _red((Y1 + X1) * (Y2 + X2))
    c = _red(_red(T1 * D2) * T2)
    d = _red(2 * Z1 * Z2)
    e, f, g, h = (b - a) % P, (d - c) % P, d + c, b + a
    return (_red(e * f), _red(g * h), _red(f * g), _red(e * h))


def _dbl(p):
    # "dbl-2008-hwcd" for a = -1.
    X1, Y1, Z1, _ = p
    a = _red(X1 * X1)
    b = _red(Y1 * Y1)
    c = _red(2 * Z1 * Z1)
    h = a + b
    e = (h - _red((X1 + Y1) * (X1 + Y1))) % P
    g = (a - b) % P
    f = (c + g) % P
    return (_red(e * f), _red(g * h), _red(f * g), _red(e * h))


def _neg(p):
    return ((-p[0]) % P, p[1], p[2], (-p[3]) % P)


def _decode(s):
    """32 bytes -> extended point, or None if it isn't one."""
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= MASK
    if y >= P:
        return None
    yy = y * y % P
    u = (yy - 1) % P
    v = (D * yy + 1) % P
    # x = sqrt(u/v) = u v^3 (u v^7)^((p-5)/8)  (RFC 8032 5.1.3)
    v3 = v * v % P * v % P
    x = u * v3 % P * pow(u * v3 % P * v3 % P * v % P, (P - 5) // 8, P) % P
    vxx = v * x % P * x % P
    if vxx != u:
        if vxx != (-u) % P:
            return None
        x = x * SQRT_M1 % P
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = P - x
    return (x, y, 1, x * y % P)


def _encode(p):
    X, Y, Z, _ = p
    zi = pow(Z, P - 2, P)
    x = X * zi % P
    y = Y * zi % P
    return (y | (x & 1) << 255).to_bytes(32, "little")


# ---- SHA-512 (FIPS 180-4), small and slow: only ever one or two blocks here ------------
# Nothing is kept between calls and no table is built: each round reads its constant out of
# _KH and the message schedule is the 16 words in use, about 1 KB of heap at most.
M64 = 0xFFFFFFFFFFFFFFFF
# The first 64 bits of the fractional parts of the cube roots of the first 80 primes, as
# bytes (640 B on the heap with the code, half what the same as hex text took).
_KH = (b"\x42\x8a\x2f\x98\xd7\x28\xae\x22\x71\x37\x44\x91\x23\xef\x65\xcd"
       b"\xb5\xc0\xfb\xcf\xec\x4d\x3b\x2f\xe9\xb5\xdb\xa5\x81\x89\xdb\xbc"
       b"\x39\x56\xc2\x5b\xf3\x48\xb5\x38\x59\xf1\x11\xf1\xb6\x05\xd0\x19"
       b"\x92\x3f\x82\xa4\xaf\x19\x4f\x9b\xab\x1c\x5e\xd5\xda\x6d\x81\x18"
       b"\xd8\x07\xaa\x98\xa3\x03\x02\x42\x12\x83\x5b\x01\x45\x70\x6f\xbe"
       b"\x24\x31\x85\xbe\x4e\xe4\xb2\x8c\x55\x0c\x7d\xc3\xd5\xff\xb4\xe2"
       b"\x72\xbe\x5d\x74\xf2\x7b\x89\x6f\x80\xde\xb1\xfe\x3b\x16\x96\xb1"
       b"\x9b\xdc\x06\xa7\x25\xc7\x12\x35\xc1\x9b\xf1\x74\xcf\x69\x26\x94"
       b"\xe4\x9b\x69\xc1\x9e\xf1\x4a\xd2\xef\xbe\x47\x86\x38\x4f\x25\xe3"
       b"\x0f\xc1\x9d\xc6\x8b\x8c\xd5\xb5\x24\x0c\xa1\xcc\x77\xac\x9c\x65"
       b"\x2d\xe9\x2c\x6f\x59\x2b\x02\x75\x4a\x74\x84\xaa\x6e\xa6\xe4\x83"
       b"\x5c\xb0\xa9\xdc\xbd\x41\xfb\xd4\x76\xf9\x88\xda\x83\x11\x53\xb5"
       b"\x98\x3e\x51\x52\xee\x66\xdf\xab\xa8\x31\xc6\x6d\x2d\xb4\x32\x10"
       b"\xb0\x03\x27\xc8\x98\xfb\x21\x3f\xbf\x59\x7f\xc7\xbe\xef\x0e\xe4"
       b"\xc6\xe0\x0b\xf3\x3d\xa8\x8f\xc2\xd5\xa7\x91\x47\x93\x0a\xa7\x25"
       b"\x06\xca\x63\x51\xe0\x03\x82\x6f\x14\x29\x29\x67\x0a\x0e\x6e\x70"
       b"\x27\xb7\x0a\x85\x46\xd2\x2f\xfc\x2e\x1b\x21\x38\x5c\x26\xc9\x26"
       b"\x4d\x2c\x6d\xfc\x5a\xc4\x2a\xed\x53\x38\x0d\x13\x9d\x95\xb3\xdf"
       b"\x65\x0a\x73\x54\x8b\xaf\x63\xde\x76\x6a\x0a\xbb\x3c\x77\xb2\xa8"
       b"\x81\xc2\xc9\x2e\x47\xed\xae\xe6\x92\x72\x2c\x85\x14\x82\x35\x3b"
       b"\xa2\xbf\xe8\xa1\x4c\xf1\x03\x64\xa8\x1a\x66\x4b\xbc\x42\x30\x01"
       b"\xc2\x4b\x8b\x70\xd0\xf8\x97\x91\xc7\x6c\x51\xa3\x06\x54\xbe\x30"
       b"\xd1\x92\xe8\x19\xd6\xef\x52\x18\xd6\x99\x06\x24\x55\x65\xa9\x10"
       b"\xf4\x0e\x35\x85\x57\x71\x20\x2a\x10\x6a\xa0\x70\x32\xbb\xd1\xb8"
       b"\x19\xa4\xc1\x16\xb8\xd2\xd0\xc8\x1e\x37\x6c\x08\x51\x41\xab\x53"
       b"\x27\x48\x77\x4c\xdf\x8e\xeb\x99\x34\xb0\xbc\xb5\xe1\x9b\x48\xa8"
       b"\x39\x1c\x0c\xb3\xc5\xc9\x5a\x63\x4e\xd8\xaa\x4a\xe3\x41\x8a\xcb"
       b"\x5b\x9c\xca\x4f\x77\x63\xe3\x73\x68\x2e\x6f\xf3\xd6\xb2\xb8\xa3"
       b"\x74\x8f\x82\xee\x5d\xef\xb2\xfc\x78\xa5\x63\x6f\x43\x17\x2f\x60"
       b"\x84\xc8\x78\x14\xa1\xf0\xab\x72\x8c\xc7\x02\x08\x1a\x64\x39\xec"
       b"\x90\xbe\xff\xfa\x23\x63\x1e\x28\xa4\x50\x6c\xeb\xde\x82\xbd\xe9"
       b"\xbe\xf9\xa3\xf7\xb2\xc6\x79\x15\xc6\x71\x78\xf2\xe3\x72\x53\x2b"
       b"\xca\x27\x3e\xce\xea\x26\x61\x9c\xd1\x86\xb8\xc7\x21\xc0\xc2\x07"
       b"\xea\xda\x7d\xd6\xcd\xe0\xeb\x1e\xf5\x7d\x4f\x7f\xee\x6e\xd1\x78"
       b"\x06\xf0\x67\xaa\x72\x17\x6f\xba\x0a\x63\x7d\xc5\xa2\xc8\x98\xa6"
       b"\x11\x3f\x98\x04\xbe\xf9\x0d\xae\x1b\x71\x0b\x35\x13\x1c\x47\x1b"
       b"\x28\xdb\x77\xf5\x23\x04\x7d\x84\x32\xca\xab\x7b\x40\xc7\x24\x93"
       b"\x3c\x9e\xbe\x0a\x15\xc9\xbe\xbc\x43\x1d\x67\xc4\x9c\x10\x0d\x4c"
       b"\x4c\xc5\xd4\xbe\xcb\x3e\x42\xb6\x59\x7f\x29\x9c\xfc\x65\x7e\x2a"
       b"\x5f\xcb\x6f\xab\x3a\xd6\xfa\xec\x6c\x44\x19\x8c\x4a\x47\x58\x17")


def _r(x, n):
    return (x >> n | x << (64 - n)) & M64


def sha512(msg):
    H = [0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
         0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179]
    n = len(msg)
    msg = bytes(msg) + b"\x80" + bytes((111 - n) % 128) + (n * 8).to_bytes(16, "big")
    for o in range(0, len(msg), 128):
        w = [int.from_bytes(msg[o + 8 * i:o + 8 * i + 8], "big") for i in range(16)]
        a, b, c, d, e, f, g, h = H
        for i in range(80):
            if i >= 16:
                x, y = w[(i - 15) & 15], w[(i - 2) & 15]
                w[i & 15] = (w[i & 15] + (_r(x, 1) ^ _r(x, 8) ^ (x >> 7)) + w[(i - 7) & 15]
                             + (_r(y, 19) ^ _r(y, 61) ^ (y >> 6))) & M64
            t1 = (h + (_r(e, 14) ^ _r(e, 18) ^ _r(e, 41)) + ((e & f) ^ (~e & g))
                  + int.from_bytes(_KH[8 * i:8 * i + 8], "big") + w[i & 15]) & M64
            t2 = ((_r(a, 28) ^ _r(a, 34) ^ _r(a, 39)) + ((a & b) ^ (a & c) ^ (b & c))) & M64
            h, g, f, e, d, c, b, a = g, f, e, (d + t1) & M64, c, b, a, (t1 + t2) & M64
        H = [(H[i] + v) & M64 for i, v in enumerate((a, b, c, d, e, f, g, h))]
    return b"".join(x.to_bytes(8, "big") for x in H)


def verify(pub, msg, sig):
    if len(sig) != 64 or len(pub) != 32:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    A = _decode(pub)
    if A is None or _decode(sig[:32]) is None:
        return False
    k = int.from_bytes(sha512(sig[:32] + pub + msg), "little") % L
    # [s]B + [k](-A) in one pass, a bit of each scalar at a time (Shamir's trick): four
    # points in the table. Two bits at a time is about 15% faster but needs 16 (3.5 KB more).
    B = (BX, BY, 1, BX * BY % P)
    nA = _neg(A)
    tab = (None, nA, B, _add(B, nA))
    q = (0, 1, 1, 0)
    for sh in range(252, -1, -1):
        q = _dbl(q)
        i = (s >> sh & 1) * 2 + (k >> sh & 1)
        if i:
            q = _add(q, tab[i])
        if probe and not sh & 63:
            probe()
    return _encode(q) == bytes(sig[:32])
