# Stop-and-wait shots and answers; other protocol phases load their own rules.
from lvduel import end, gid, emit, history, lvship, mine, moved, result, reveal, sync, terminal, unhexlify


def other(lk, frm, kind, b, j):
    import lvduelother
    try:
        return lvduelother.take(lk, frm, kind, b, j)
    finally:
        lvship.drop("lvduelother")


def take(lk, frm, kind, b, j):
    # Mutate only: the caller releases this module before durable publication.
    # None means no change; (light, retry) commits before optional recovery.
    if kind not in (5, 6):
        return other(lk, frm, kind, b, j)
    ident = b[:2]
    g = next((x for x in j["g"] if x["to"] == frm and gid(x) == ident), None)
    if g is None:
        return other(lk, frm, kind, b, j)
    light = False
    if kind == 5:
        n, cell = b[2], b[3]
        if not 1 <= n <= 71 or cell >= 36:
            return
        if n <= g["n"]:
            # Semantic duplicate with a fresh envelope: replay the saved answer only.
            h = g["h"]
            z = (n, ord(h[2 * n - 2]) - 65, ord(h[2 * n - 1]) - 97)
            if z and not mine(lk, g, n) and z[1] == cell:
                emit(lk, g, 6, ident + bytes(z), False)
                return False, None
            return
        if g["s"] != "active" or n != g["n"] + 1 or mine(lk, g, n) or g.get("p") is not None:
            sync(lk, g)
        else:
            cells = [z[1] for z in history(g) if not mine(lk, g, z[0])]
            if cell in cells:
                sync(lk, g)
            else:
                r = result(unhexlify(g["l"]), cells, cell)
                g["h"] += chr(65 + cell) + chr(97 + r)
                g["n"] = n
                moved(lk, g)
                emit(lk, g, 6, ident + bytes((n, cell, r)))
                if r & 8:
                    g["win"] = False
                    g["s"] = "reveal"
                    reveal(lk, g)
                else:
                    light = True
    elif kind == 6:
        n, cell, r = b[2:5]
        if n <= g["n"]:
            return
        if g["s"] != "active" or n != g["n"] + 1 or not mine(lk, g, n) or g.get("p") != cell or r not in (0, 1, 2, 3, 4, 10, 11, 12):
            sync(lk, g)
        else:
            g["h"] += chr(65 + cell) + chr(97 + r)
            g["n"], g["p"] = n, None
            moved(lk, g)
            if r & 8:
                g["win"], g["s"] = True, "reveal"
                reveal(lk, g)
            else:
                # 30 cells are water and 6 are ships, and the sixth hit always ends
                # the game: a 31st miss or a sixth hit without "+8" can't be true
                # (review 0.3.1-4 #5). Don't wait for a reveal that a ship answering
                # this way may never send: the game ends here, with no result.
                got = [z[2] for z in history(g) if mine(lk, g, z[0])]
                miss = got.count(0)
                if miss > 30 or len(got) - miss >= 6:
                    terminal(g, "cheat")
                    end(lk, g, 6)
    return light, None
