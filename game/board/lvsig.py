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
# double scalar multiplication is Straus' method on a 2-bit joint window: 16 combinations
# of B and -A built per call, then 127 steps of 2 doublings + at most one addition.
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
# this string and the message schedule is the 16 words in use, about 1 KB of heap at most.
M64 = 0xFFFFFFFFFFFFFFFF
# The first 64 bits of the fractional parts of the cube roots of the first 80 primes.
_KH = ("428a2f98d728ae227137449123ef65cdb5c0fbcfec4d3b2fe9b5dba58189dbbc"
       "3956c25bf348b53859f111f1b605d019923f82a4af194f9bab1c5ed5da6d8118"
       "d807aa98a303024212835b0145706fbe243185be4ee4b28c550c7dc3d5ffb4e2"
       "72be5d74f27b896f80deb1fe3b1696b19bdc06a725c71235c19bf174cf692694"
       "e49b69c19ef14ad2efbe4786384f25e30fc19dc68b8cd5b5240ca1cc77ac9c65"
       "2de92c6f592b02754a7484aa6ea6e4835cb0a9dcbd41fbd476f988da831153b5"
       "983e5152ee66dfaba831c66d2db43210b00327c898fb213fbf597fc7beef0ee4"
       "c6e00bf33da88fc2d5a79147930aa72506ca6351e003826f142929670a0e6e70"
       "27b70a8546d22ffc2e1b21385c26c9264d2c6dfc5ac42aed53380d139d95b3df"
       "650a73548baf63de766a0abb3c77b2a881c2c92e47edaee692722c851482353b"
       "a2bfe8a14cf10364a81a664bbc423001c24b8b70d0f89791c76c51a30654be30"
       "d192e819d6ef5218d69906245565a910f40e35855771202a106aa07032bbd1b8"
       "19a4c116b8d2d0c81e376c085141ab532748774cdf8eeb9934b0bcb5e19b48a8"
       "391c0cb3c5c95a634ed8aa4ae3418acb5b9cca4f7763e373682e6ff3d6b2b8a3"
       "748f82ee5defb2fc78a5636f43172f6084c87814a1f0ab728cc702081a6439ec"
       "90befffa23631e28a4506cebde82bde9bef9a3f7b2c67915c67178f2e372532b"
       "ca273eceea26619cd186b8c721c0c207eada7dd6cde0eb1ef57d4f7fee6ed178"
       "06f067aa72176fba0a637dc5a2c898a6113f9804bef90dae1b710b35131c471b"
       "28db77f523047d8432caab7b40c724933c9ebe0a15c9bebc431d67c49c100d4c"
       "4cc5d4becb3e42b6597f299cfc657e2a5fcb6fab3ad6faec6c44198c4a475817")


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
                  + int(_KH[16 * i:16 * i + 16], 16) + w[i & 15]) & M64
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
