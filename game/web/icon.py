"""Draw the home-screen icon (web/icon.png, 192x192) with no image library.

The icon is the game's trajectory chart: Earth (ink) and Mars (rust) on a dashed rule,
the transfer arc between them, and the ship on it. Paper background, edge to edge: iOS
rounds the corners itself. Run it again after changing the drawing; the PNG is committed
so a build doesn't need to redraw it.

    python3 web/icon.py          # writes web/icon.png and prints its size
"""
import math
import os
import struct
import zlib

S = 192
SS = 4                                  # 4x4 samples a pixel: smooth edges
PAPER, INK, RUST = (0xF2, 0xEC, 0xDF), (0x1C, 0x1B, 0x19), (0xC8, 0x55, 0x2B)
CX, CY, RX, RY = 96.0, 124.0, 62.0, 66.0  # the transfer arc (upper half-ellipse)
EARTH, MARS = (CX - RX, CY), (CX + RX, CY)
T = math.radians(122)                   # where the ship is along the arc
SHIP = (CX + RX * math.cos(T), CY - RY * math.sin(T))


def disc(p, c, r):
    return (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 <= r * r


def arc(p, w):
    x, y = (p[0] - CX) / RX, (p[1] - CY) / RY
    return p[1] <= CY and abs(math.sqrt(x * x + y * y) - 1) * (RX + RY) / 2 <= w / 2


def rule(p):                            # dashed rule under the planets: 8 on, 6 off
    return abs(p[1] - CY) <= 1.5 and 20 <= p[0] <= 172 and (p[0] - 20) % 14 < 8


def colour(p):
    if disc(p, SHIP, 10):
        return RUST if disc(p, SHIP, 7) else PAPER   # a paper ring cuts the arc
    if disc(p, MARS, 15):
        return RUST
    if disc(p, EARTH, 12):
        return INK
    if arc(p, 6) or rule(p):
        return INK
    return PAPER


def draw():
    rows = []
    for j in range(S):
        row = bytearray(b"\0")          # PNG filter byte: none
        for i in range(S):
            acc = [0, 0, 0]
            for a in range(SS):
                for b in range(SS):
                    c = colour((i + (b + .5) / SS, j + (a + .5) / SS))
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
            n = SS * SS
            row += bytes(round(v / n) for v in acc)
        rows.append(bytes(row))
    return b"".join(rows)


def png(raw):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    data = png(draw())
    open(out, "wb").write(data)
    print("icon.png %d B" % len(data))
