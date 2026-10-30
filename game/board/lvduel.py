# Asteroid duel: loaded per item/request, never kept on the Link.
# History is packed as hex triples (global shot number, cell, answer).
import os
from binascii import hexlify, unhexlify
from lvlivein import load, save, send, sha256, keep

DAY = 86400
F = "/duel.json"
ACTIVE = ("draft", "wait", "invited", "active", "reveal")


def integer(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


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


def commit(g, layout, salt):
    return sha256(b"LVD1" + g + layout + salt).digest()[:8]


def result(layout, fired, cell):
    ships = fleet(layout)
    for cells in ships:
        if cell in cells:
            hit = all(c == cell or c in fired for c in cells)
            r = len(cells) + 1 if hit else 1
            if all(c == cell or c in fired for ship in ships for c in ship):
                r += 8
            return r
    return 0


def now(lk):
    c = lk.sh.clock
    return int(c.epoch_ms()) // 1000 if c.known() else None


def box(lk):
    return load(lk.sh.data + F) or {"g": [], "r": {}}


def store(lk, j):
    save(lk.sh.data + F, j)
    lk.v += 1


def gid(g):
    return unhexlify(g["id"])


def history(g):
    b = unhexlify(g["h"])
    return [list(b[i:i + 3]) for i in range(0, len(b), 3)]


def mine(lk, g, n):
    return (n % 2 == 0) == (g["i"] == lk.node.ship)


def pending(lk, g):
    return any(o[0] == g["to"] and 3 <= o[1][0] <= 9 and o[1][5:7] == gid(g) for o in lk.out if o[1][0] not in (3, 4)) or any(o[0] == g["to"] and o[1][0] in (3, 4) and o[1][6:8] == gid(g) for o in lk.out)


def emit(lk, g, kind, body, remember=True):
    body = body + bytes(11 - len(body))
    if remember:
        g["last"] = [kind, hexlify(body).decode()]
    if len(lk.out) < 24 and not any(o[0] == g["to"] and o[1][0] == kind and o[1][5:16] == body for o in lk.out):
        send(lk, kind, g["to"], body)


def end(lk, g, why):
    emit(lk, g, 8, gid(g) + bytes((why,)), False)


def sync(lk, g):
    t = now(lk)
    if g.get("sync") is not None and (t is None or t - g["sync"] < 3600):
        return
    h = history(g)
    c, r = h[-1][1:] if h else (255, 255)
    # State 0 waiting, 1 active, 2 awaiting answer, 3 revealing, 4 terminal.
    s = 2 if g.get("p") is not None else 1 if g["s"] == "active" else 3 if g["s"] == "reveal" else 0 if g["s"] in ("wait", "invited") else 4
    s |= 128 if not lk.cfg.get("dl", True) else 0
    emit(lk, g, 9, gid(g) + bytes((g["n"], c, r, s)), False)
    g["sync"] = t if t is not None else 0


def repeat(lk, g):
    z = g.get("last")
    if z:
        emit(lk, g, z[0], unhexlify(z[1]), False)


def reveal(lk, g):
    if g.get("l"):
        emit(lk, g, 7, gid(g) + unhexlify(g["l"]) + unhexlify(g["salt"]), False)
        g["sent"] = 1


def finish(lk, j, g):
    if not g.get("verified") or g.get("win") is None or g.get("counted"):
        return
    r = j["r"].get(str(g["to"]), [0, 0])
    r[0 if g["win"] else 1] += 1
    j["r"][str(g["to"])] = r
    g["counted"] = 1
    g["s"] = "done"


def sweep(lk, j):
    t = now(lk)
    changed = False
    for g in j["g"]:
        if g["s"] not in ACTIVE:
            continue
        if g.get("t") is None:
            g["t"] = t
            changed = t is not None or changed
        age = t - g["t"] if t is not None and g.get("t") is not None else 0
        if g["s"] == "wait" and age >= 3600 and not g.get("update"):
            g["update"] = True
            changed = True
        if g["s"] in ("wait", "invited") and age >= 3 * DAY:
            g["s"] = "called"
            end(lk, g, 3)
            changed = True
        if age >= 21600 and g["s"] == "active" and not mine(lk, g, g["n"] + 1):
            p = lk.ble.peers.get(g["to"])
            if p is not None and p.seen:
                before = g.get("sync")
                sync(lk, g)
                changed = changed or before != g.get("sync")
        if g["s"] == "called":
            lk.out[:] = [o for o in lk.out if not (o[0] == g["to"] and 3 <= o[1][0] <= 7 and (o[1][6:8] if o[1][0] in (3, 4) else o[1][5:7]) == gid(g))]
            keep(lk)
    return changed


def maintain(lk):
    j = box(lk)
    if sweep(lk, j):
        store(lk, j)


def room(j):
    while len(j["g"]) >= 3:
        old = next((g for g in j["g"] if g["s"] not in ACTIVE), None)
        if old is None:
            return
        j["g"].remove(old)


def fresh(lk, to, ident, inviter, state):
    return {"id": hexlify(ident).decode(), "to": to, "i": inviter, "s": state,
            "n": 0, "h": "", "p": None, "t": now(lk)}


def take(lk, frm, kind, b):
    # Validate shape before looking at state: authenticated nonsense is still nonsense.
    if len(b) != 11 or not 3 <= kind <= 9:
        return False
    ident = b[1:3] if kind in (3, 4) else b[:2]
    j = box(lk)
    if sweep(lk, j):
        store(lk, j)
    g = next((x for x in j["g"] if x["to"] == frm and gid(x) == ident), None)
    if kind in (3, 4) and b[0] != 1:
        temp = fresh(lk, frm, ident, frm, "called")
        end(lk, temp, 4)
        return False
    light = False
    if kind == 3:
        if g is not None:
            repeat(lk, g)
            return False
        other = next((x for x in j["g"] if x["to"] == frm and x["s"] in ACTIVE), None)
        # Crossing invites: the lower numbered inviter wins, consistently at both ends.
        if other and other["s"] in ("draft", "wait") and frm < lk.node.ship:
            other["s"] = "called"
            end(lk, other, 3)
            other = None
        if other or sum(x["s"] in ACTIVE for x in j["g"]) >= 3:
            end(lk, fresh(lk, frm, ident, frm, "called"), 5)
            return False
        # Keep one completed game per opponent, for the reveal screen and rematch.
        j["g"] = [x for x in j["g"] if x["to"] != frm or x["s"] in ACTIVE]
        room(j)
        g = fresh(lk, frm, ident, frm, "invited")
        g["c"] = hexlify(b[3:11]).decode()
        j["g"].append(g)
        light = True
    elif g is None:
        if kind != 9 and len(lk.out) < 24 and (not getattr(lk, "duel_unknown", None) or (now(lk) is not None and now(lk) - lk.duel_unknown >= 3600)):
            temp = fresh(lk, frm, ident, frm, "called")
            sync(lk, temp)
            lk.duel_unknown = now(lk) or 1
        return False
    elif kind == 4:
        if g["s"] != "wait":
            return False
        g["c"] = hexlify(b[3:11]).decode()
        g["s"] = "active"
        g["t"] = now(lk)
    elif kind == 5:
        n, cell = b[2], b[3]
        if not 1 <= n <= 71 or cell >= 36:
            return False
        if n <= g["n"]:
            # Semantic duplicate with a fresh envelope: replay the saved answer only.
            h = history(g)
            z = next((z for z in h if z[0] == n), None)
            if z and not mine(lk, g, n) and z[1] == cell:
                emit(lk, g, 6, ident + bytes(z), False)
            return False
        if g["s"] != "active" or n != g["n"] + 1 or mine(lk, g, n) or g.get("p") is not None:
            sync(lk, g)
        else:
            h = history(g)
            cells = [z[1] for z in h if not mine(lk, g, z[0])]
            if cell in cells:
                sync(lk, g)
            else:
                r = result(unhexlify(g["l"]), cells, cell)
                g["h"] += hexlify(bytes((n, cell, r))).decode()
                g["n"] = n
                g["t"] = now(lk)
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
            return False
        if g["s"] != "active" or n != g["n"] + 1 or not mine(lk, g, n) or g.get("p") != cell or r not in (0, 1, 2, 3, 4, 10, 11, 12):
            sync(lk, g)
        else:
            g["h"] += hexlify(bytes((n, cell, r))).decode()
            g["n"], g["p"], g["t"] = n, None, now(lk)
            if r & 8:
                g["win"], g["s"] = True, "reveal"
                reveal(lk, g)
    elif kind == 7:
        if g["s"] not in ("reveal", "done", "cheat"):
            sync(lk, g)
        else:
            layout, salt = b[2:5], b[5:11]
            ok = False
            try:
                fleet(layout)
                ok = hexlify(commit(ident, layout, salt)).decode() == g.get("c")
                fired = []
                for n, cell, r in history(g):
                    if mine(lk, g, n):
                        if cell in fired or result(layout, fired, cell) != r:
                            ok = False
                        fired.append(cell)
            except ValueError:
                pass
            if not ok:
                # Undo a previously counted result if a contradictory reveal follows it.
                if g.get("counted"):
                    j["r"][str(frm)][0 if g["win"] else 1] -= 1
                    g["counted"] = 0
                g["s"] = "cheat"
                end(lk, g, 6)
            else:
                g["verified"] = 1
                g["their"] = hexlify(layout).decode()
                if not g.get("sent"):
                    reveal(lk, g)
                finish(lk, j, g)
    elif kind == 8:
        why = b[2]
        if why not in (1, 2, 3, 4, 5, 6):
            return False
        if why == 2 and g["s"] in ACTIVE:
            g["win"], g["s"] = True, "reveal"
            reveal(lk, g)
        elif why == 6:
            if g.get("counted"):
                j["r"][str(frm)][0 if g["win"] else 1] -= 1
                g["counted"] = 0
            g["s"] = "cheat"
        elif g["s"] in ACTIVE:
            g["s"] = {1: "declined", 3: "called", 4: "version", 5: "busy"}.get(why, "called")
    elif kind == 9:
        n, cell, r, state = b[2:6]
        g["nl"] = bool(state & 128)
        state &= 127
        if n > 71 or state > 4:
            return False
        # If the peer lacks our last shot/answer, replay it with a new envelope.
        # Equal n + awaiting answer also repairs a pending shot lost before receipt.
        if n < g["n"] or (n == g["n"] and g.get("p") is not None):
            repeat(lk, g)
        elif n > g["n"]:
            if n == g["n"] + 1 and g.get("p") == cell and mine(lk, g, n):
                return take(lk, frm, 6, ident + bytes((n, cell, r)) + bytes(6))
            sync(lk, g)
        elif g["s"] == "reveal":
            reveal(lk, g)
    store(lk, j)
    return light


def action(lk, b):
    j = box(lk)
    if sweep(lk, j):
        store(lk, j)
    a, to = b.get("action"), b.get("to")
    if not integer(to, 0, 7) or to == lk.node.ship:
        return 400, {"err": "Pick a crewmate."}
    if len(lk.out) >= 24:
        return 429, {"err": "Your previous moves are on their way."}
    peer = lk.ble.peers.get(to)
    if a == "new" and peer is not None and peer.info and not peer.info.get("cap"):
        return 409, {"err": "This ship needs ship-to-ship enabled and the duel update."}
    g = next((x for x in j["g"] if x["to"] == to and x["s"] in ACTIVE), None)
    if a == "new":
        if g or sum(x["s"] in ACTIVE for x in j["g"]) >= 3:
            return 409, {"err": "A duel is already going, or three duels are open."}
        j["g"] = [x for x in j["g"] if x["to"] != to]
        room(j)
        g = fresh(lk, to, os.urandom(2), lk.node.ship, "draft")
        j["g"].append(g)
    elif g is None:
        return 409, {"err": "No duel is open."}
    elif a in ("lock", "invite", "accept"):
        if g["s"] not in ("draft", "invited") or g.get("l"):
            return 409, {"err": "Your fleet is locked."}
        try:
            layout = encode(b.get("layout"))
        except (ValueError, TypeError):
            return 400, {"err": "Bad layout. Ships cannot overlap or touch sides."}
        salt = os.urandom(6)
        g["l"], g["salt"] = hexlify(layout).decode(), hexlify(salt).decode()
        kind = 4 if g["s"] == "invited" else 3
        g["s"] = "active" if kind == 4 else "wait"
        g["t"] = now(lk)
        emit(lk, g, kind, bytes((1,)) + gid(g) + commit(gid(g), layout, salt))
        sync(lk, g)
    elif a == "fire":
        cell = b.get("cell")
        if not integer(cell, 0, 35) or cell in [z[1] for z in history(g) if mine(lk, g, z[0])] or cell == g.get("p"):
            return 400, {"err": "Bad cell or already fired."}
        if pending(lk, g):
            return 429, {"err": "Your previous move is on its way."}
        if g["s"] != "active" or g.get("p") is not None or not mine(lk, g, g["n"] + 1):
            return 409, {"err": "It is not your turn."}
        g["p"] = cell
        g["t"] = now(lk)
        emit(lk, g, 5, gid(g) + bytes((g["n"] + 1, cell)))
    elif a == "decline":
        if g["s"] != "invited":
            return 409, {"err": "No invitation is waiting."}
        g["s"] = "declined"
        end(lk, g, 1)
    elif a == "resign":
        if g["s"] not in ("wait", "active"):
            return 409, {"err": "No duel is playing."}
        g["s"], g["win"] = "reveal", False
        end(lk, g, 2)
        reveal(lk, g)
    elif a == "call":
        t = now(lk)
        if t is None or g.get("t") is None or t - g["t"] < 3 * DAY or (g["s"] == "active" and mine(lk, g, g["n"] + 1) and g.get("p") is None):
            return 409, {"err": "Wait three days for the next move."}
        g["s"] = "called"
        end(lk, g, 3)
    else:
        return 400, {"err": "Bad duel action."}
    store(lk, j)
    return 200, {"ok": True}


def view(lk):
    j = box(lk)
    if sweep(lk, j):
        store(lk, j)
    out = []
    for g in j["g"]:
        x = dict((k, g.get(k)) for k in ("id", "to", "s", "n", "p", "t", "win", "their", "update", "nl"))
        x["layout"] = fleet(unhexlify(g["l"])) if g.get("l") else None
        x["shots"] = [z for z in history(g) if mine(lk, g, z[0])]
        x["incoming"] = [z for z in history(g) if not mine(lk, g, z[0])]
        x["turn"] = g["s"] == "active" and g.get("p") is None and mine(lk, g, g["n"] + 1)
        x["pending"] = pending(lk, g)
        x["record"] = j["r"].get(str(g["to"]), [0, 0])
        if g.get("their"):
            x["their"] = fleet(unhexlify(g["their"]))
        out.append(x)
    return out
