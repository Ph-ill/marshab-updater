# Compact phone snapshot, loaded after the duel rules have been released.
import lvship
from binascii import unhexlify
from lvlivein import load, probe


def fleet(layout):
    if not isinstance(layout, (bytes, bytearray)) or len(layout) != 3:
        raise ValueError("bad layout")
    x = layout[0] << 16 | layout[1] << 8 | layout[2]
    if x & 15:
        raise ValueError("bad layout")
    slots = ((x >> 18, (x >> 17) & 1, 3), ((x >> 11) & 63, (x >> 10) & 1, 2), ((x >> 4) & 63, 0, 1))
    out, used = [], []
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


def view(lk, j=None):
    # maintain() has already applied expiry/recovery before this read-only snapshot.
    if j is None:
        lvship.free()
        j = load(lk.sh.data + "/duel.json") or {"g": [], "r": {}}
    # Rejection intents are not phone state. Release them before building views,
    # and consume this private parsed copy so old games do not overlap new views.
    j.pop("e", None)
    out = []
    while j["g"]:
        g = j["g"].pop(0)
        x = dict((k, g.get(k)) for k in ("id", "to", "s", "n", "p", "t", "win", "why", "update", "nl", "doubt"))
        if g.get("tu"):
            x["t"] = None  # a stamp from before the move (lvduel.moved), not its time
        if g.get("mutual") and g["s"] in ("reveal", "done"):
            x["status"] = "Your game ended with both ships standing down. No result."
        x["layout"] = fleet(unhexlify(g["l"])) if g.get("l") else None
        x["history"], x["even"] = g["h"], g["i"] == lk.node.ship
        x["turn"] = g["s"] == "active" and g.get("p") is None and ((g["n"] + 1) % 2 == 0) == x["even"]
        ident = unhexlify(g["id"])
        x["pending"] = bool(g.get("q")) or any(o[0] == g["to"] and 3 <= o[1][0] <= 9 and
            (o[1][6:8] if o[1][0] in (3, 4) else o[1][5:7]) == ident for o in lk.out)
        x["record"] = j["r"].get(str(g["to"]), [0, 0])
        x["their"] = fleet(unhexlify(g["their"])) if g.get("their") and g["s"] not in ("draft", "wait", "invited", "active", "reveal") else None
        out.append(x)
        g = None
        probe("view")
    return out


def expanded(lk):
    # Object API for local callers; HTTP expands only one shot at a time.
    out = view(lk)
    for g in out:
        h, even = g.pop("history"), g.pop("even")
        g["shots"], g["incoming"] = [], []
        for i in range(0, len(h), 2):
            n = i // 2 + 1
            key = "shots" if (n % 2 == 0) == even else "incoming"
            g[key].append([n, ord(h[i]) - 65, ord(h[i + 1]) - 97])
    return out
