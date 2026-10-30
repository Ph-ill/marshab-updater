# Fleet validation and scoring, released before durable saves.
from lvduel import integer


def fleet(layout):
    if not isinstance(layout, (bytes, bytearray)) or len(layout) != 3:
        raise ValueError("bad layout")
    x = layout[0] << 16 | layout[1] << 8 | layout[2]
    if x & 15:
        raise ValueError("bad layout")
    # Wire packing: seven bits, seven bits, six bits, four zero bits.
    slots = ((x >> 18, (x >> 17) & 1, 3), ((x >> 11) & 63, (x >> 10) & 1, 2), ((x >> 4) & 63, 0, 1))
    out = []
    used = []
    for c, d, size in slots:
        if c >= 36 or (c // 6 + size > 6 if d else c % 6 + size > 6):
            raise ValueError("bad layout")
        cells = [c + j * (6 if d else 1) for j in range(size)]
        for a in cells:
            for b in used:
                if a == b or abs(a // 6 - b // 6) + abs(a % 6 - b % 6) == 1:
                    raise ValueError("bad layout")
        out.append(cells)
        used.extend(cells)
    return out


def encode(slots):
    if not isinstance(slots, (list, tuple)) or len(slots) != 3:
        raise ValueError("bad layout")
    for z in slots:
        if not isinstance(z, (list, tuple)) or len(z) != 2 or not integer(z[0], 0, 35) or not integer(z[1], 0, 1):
            raise ValueError("bad layout")
    x = (slots[0][0] << 18 | slots[0][1] << 17 | slots[1][0] << 11 |
         slots[1][1] << 10 | slots[2][0] << 4)
    b = bytes((x >> 16, x >> 8 & 255, x & 255))
    fleet(b)
    return b


def result(layout, fired, cell):
    return score(fleet(layout), fired, cell)


def replay(layout, transcript, even):
    ships = fleet(layout)
    fired = []
    for i in range(0, len(transcript), 2):
        if ((i // 2 + 1) % 2 == 0) == even:
            cell, r = ord(transcript[i]) - 65, ord(transcript[i + 1]) - 97
            if cell in fired or score(ships, fired, cell) != r:
                return False
            fired.append(cell)
    return True


def score(ships, fired, cell):
    for cells in ships:
        if cell in cells:
            hit = all(c == cell or c in fired for c in cells)
            r = len(cells) + 1 if hit else 1
            if all(c == cell or c in fired for ship in ships for c in ship):
                r += 8
            return r
    return 0
