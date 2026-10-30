# Fleet validation, scoring and proof replay, released before durable saves.


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


def proof(lk, frm, b, j, g):
    from lvduel import commit, hexlify, sync, terminal, end, reveal, finish, probe
    if g["s"] not in ("reveal", "done", "cheat"):
        sync(lk, g)
    else:
        layout, salt = b[2:5], b[5:11]
        ok = False
        try:
            ok = hexlify(commit(b[:2], layout, salt)).decode() == g.get("c")
            ok = replay(layout, g["h"], g["i"] == lk.node.ship) and ok
            probe("layout")
        except ValueError:
            ok = False
        if not ok:
            # Undo a previously counted result after a contradictory reveal.
            if g.get("counted"):
                j["r"][str(frm)][0 if g["win"] else 1] -= 1
                g["counted"] = 0
            terminal(g, "cheat")
            end(lk, g, 6)
        else:
            g["verified"] = 1
            g["their"] = hexlify(layout).decode()
            if not g.get("sent"):
                reveal(lk, g)
            finish(lk, j, g)
    return False, None
