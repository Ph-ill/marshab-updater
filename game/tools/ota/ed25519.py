"""Ed25519 signing for releases (RFC 8032), pure Python, for the release machine only:
the ship only verifies (board/lvsig.py). Slow and not constant-time, which is fine for
signing a release on your own computer; never use it where someone else can time it.
Keys are 32-byte seeds; load_pem() reads the PKCS#8 file that keygen writes (the format
OpenSSL and the `cryptography` package use too)."""
import base64
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
_GY = 4 * pow(5, P - 2, P) % P
_GX = None


def _recover_x(y, sign):
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * pow(2, (P - 1) // 4, P) % P
    if x & 1 != sign:
        x = P - x
    return x


G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % P)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % P
    b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P
    d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _enc(p):
    zi = pow(p[2], P - 2, P)
    x, y = p[0] * zi % P, p[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _h(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    return _enc(_mul(_expand(seed)[0], G))


def sign(seed, msg):
    a, prefix = _expand(seed)
    pub = _enc(_mul(a, G))
    r = _h(prefix, msg) % L
    R = _enc(_mul(r, G))
    s = (r + _h(R, pub, msg) * a) % L
    return R + s.to_bytes(32, "little")


# PKCS#8 for Ed25519 (RFC 8410): this fixed prefix, then the 32-byte seed.
_PK8 = bytes.fromhex("302e020100300506032b657004220420")


def load_pem(text):
    body = "".join(l for l in text.splitlines() if l and not l.startswith("-----"))
    der = base64.b64decode(body)
    if len(der) != 48 or der[:16] != _PK8:
        raise ValueError("not an Ed25519 private key (PKCS#8 PEM)")
    return der[16:]


def dump_pem(seed):
    b = base64.b64encode(_PK8 + seed).decode()
    return "-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----\n" % b
