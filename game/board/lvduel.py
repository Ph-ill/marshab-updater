# Asteroid duel: loaded per item/request, never kept on the Link.
# History uses two ASCII characters per shot (cell and answer); n is its index.
import os
import lvship
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


def timer(lk, g):
    # These stamps belong to this Link's boot, never duel.json. Accumulate
    # ticks_diff regularly so wrapping ticks do not become epoch deadlines.
    t = lvship.ticks_ms()
    key = (g["to"], g["id"])
    sig = (g["s"], g["n"], g.get("p"))
    timers = lk.duel_times
    z = timers.get(key)
    if z is None:
        z = [t, 0, sig, -21600000 if g["s"] == "active" else 0, None]
        timers[key] = z
    else:
        dt = lvship.ticks_diff(t, z[0])
        z[0] = t
        if dt < 0:
            z[4] = None
        else:
            z[1] += dt
        if sig != z[2]:
            z[2], z[3] = sig, z[1]
    return z


def box(lk):
    return load(lk.sh.data + F) or {"g": [], "r": {}}


def store(lk, j):
    # Write-ahead intents: no item may reach livebox before its game state does.
    save(lk.sh.data + F, j)
    lk.v += 1
    cleanout(lk, j)
    flush(lk, j)


def belongs(o, g):
    b = o[1]
    return o[0] == g["to"] and 3 <= b[0] <= 9 and (b[6:8] if b[0] in (3, 4) else b[5:7]) == gid(g)


def allowed(g, kind):
    if g.get("unknown"):
        return kind == 9
    if g.get("why") == 2:
        return kind in (7, 8)
    if g["s"] in ACTIVE:
        return True
    # A completed game still owes its final ANSWER and mutual verification.
    return kind in ((6, 7, 8) if g["s"] == "done" else (8,))


def cleanout(lk, j, orphans=False):
    games = j["g"] + j.get("e", [])
    out = []
    for o in lk.out:
        if not 3 <= o[1][0] <= 9:
            out.append(o)
            continue
        g = next((g for g in games if belongs(o, g)), None)
        if g is None and not orphans:
            out.append(o)
            continue
        if g is not None and allowed(g, o[1][0]):
            if o[1][0] != 8 or not any(belongs(z, g) and z[1][0] == 8 for z in out):
                out.append(o)
    if len(out) != len(lk.out):
        lk.out[:] = out
        keep(lk)


def flush(lk, j):
    changed = False
    for g in j["g"] + j.get("e", []):
        q = g.get("q", [])
        # Reserve the whole reply group, including the fleet-ending reveal.
        needed = sum(not queued(lk, g, z[0], unhexlify(z[1])) for z in q)
        if needed > 24 - len(lk.out):
            continue
        for kind, body in q:
            body = unhexlify(body)
            if not queued(lk, g, kind, body):
                send(lk, kind, g["to"], body)
            if kind == 7:
                g["sent"] = 1
        if q:
            g["q"] = []
            changed = True
    if j.get("e"):
        retained = [g for g in j["e"] if pending(lk, g)]
        if len(retained) != len(j["e"]):
            j["e"] = retained
            changed = True
    if changed:
        # A crash here replays identical bodies, never a new commitment/move.
        save(lk.sh.data + F, j)


def terminal(g, state):
    g["s"] = state
    g["q"] = [z for z in g.get("q", []) if allowed(g, z[0])]


def rejected(lk, j, g, why):
    # At most seven pending replies, one per sender. Retire after acknowledgement.
    j["e"] = [x for x in j.get("e", []) if x["to"] != g["to"]]
    j["e"].append(g)
    end(lk, g, why)
    store(lk, j)


def gid(g):
    return unhexlify(g["id"])


def history(g):
    b = g["h"]
    return [[i // 2 + 1, ord(b[i]) - 65, ord(b[i + 1]) - 97] for i in range(0, len(b), 2)]


def mine(lk, g, n):
    return (n % 2 == 0) == (g["i"] == lk.node.ship)


def pending(lk, g):
    return bool(g.get("q")) or any(belongs(o, g) for o in lk.out)


def queued(lk, g, kind, body):
    return any(o[0] == g["to"] and o[1][0] == kind and o[1][5:16] == body for o in lk.out)


def emit(lk, g, kind, body, remember=True):
    body = body + bytes(11 - len(body))
    if not allowed(g, kind):
        return False
    if remember:
        g["last"] = [kind, hexlify(body).decode()]
    if queued(lk, g, kind, body):
        return True
    z = [kind, hexlify(body).decode()]
    q = g.setdefault("q", [])
    if z not in q:
        # Only the latest SYNC is useful; stop-and-wait bounds the other intents.
        if kind in (5, 6, 9):
            if kind == 6 and any(x[0] == 6 and unhexlify(x[1])[2] > body[2] for x in q):
                return False
            q[:] = [x for x in q if x[0] != kind]
        q.append(z)
    return False


def end(lk, g, why):
    emit(lk, g, 8, gid(g) + bytes((why,)), False)


def sync(lk, g):
    z = timer(lk, g)
    if z[4] is not None and z[1] - z[4] < 3600000:
        return
    h = history(g)
    c, r = h[-1][1:] if h else (255, 255)
    # State 0 waiting, 1 active, 2 awaiting answer, 3 revealing, 4 terminal.
    s = 2 if g.get("p") is not None else 1 if g["s"] == "active" else 3 if g["s"] == "reveal" else 0 if g["s"] in ("wait", "invited") else 4
    s |= 128 if not lk.cfg.get("dl", True) else 0
    emit(lk, g, 9, gid(g) + bytes((g["n"], c, r, s)), False)
    z[4] = z[1]
    # A revision, not a clock stamp: callers use it to notice a new intent.
    g["sync"] = g.get("sync", 0) + 1


def repeat(lk, g):
    z = g.get("last")
    if z:
        emit(lk, g, z[0], unhexlify(z[1]), False)


def reveal(lk, g):
    if g.get("l"):
        if emit(lk, g, 7, gid(g) + unhexlify(g["l"]) + unhexlify(g["salt"]), False):
            g["sent"] = 1


def finish(lk, j, g):
    if not g.get("verified") or g.get("win") is None or g.get("counted"):
        return
    r = j["r"].get(str(g["to"]), [0, 0])
    r[0 if g["win"] else 1] += 1
    j["r"][str(g["to"])] = r
    g["counted"] = 1
    terminal(g, "done")


def sweep(lk, j):
    t = now(lk)
    changed = False
    for g in j["g"][:]:
        if g["s"] not in ACTIVE:
            continue
        z = timer(lk, g)
        if g.get("t") is None:
            g["t"] = t
            changed = t is not None or changed
        age = t - g["t"] if t is not None and g.get("t") is not None else 0
        if g["s"] == "draft" and (age >= 3 * DAY or z[1] >= 3 * DAY * 1000):
            j["g"].remove(g)
            changed = True
            continue
        if g.get("light_dirty"):
            before = g.get("sync")
            sync(lk, g)
            if before != g.get("sync"):
                g.pop("light_dirty", None)
                changed = True
        if g["s"] == "wait" and z[1] - z[3] >= 3600000 and not g.get("update") and not any(o[0] == g["to"] and o[1][0] == 3 and o[1][6:8] == gid(g) for o in lk.out):
            g["update"] = True
            changed = True
        if g["s"] in ("wait", "invited") and age >= 3 * DAY:
            terminal(g, "called")
            end(lk, g, 3)
            changed = True
        if z[1] - z[3] >= 21600000 and g["s"] == "active" and (g.get("p") is not None or not mine(lk, g, g["n"] + 1)):
            p = lk.ble.peers.get(g["to"])
            if p is not None and p.seen:
                before = g.get("sync")
                sync(lk, g)
                changed = changed or before != g.get("sync")

    return changed


def maintain(lk):
    j = box(lk)
    keys = [(g["to"], g["id"]) for g in j["g"] if g["s"] in ACTIVE]
    for key in list(lk.duel_times):
        if key not in keys:
            del lk.duel_times[key]
    cleanout(lk, j, True)
    if sweep(lk, j):
        store(lk, j)
    else:
        flush(lk, j)


def lighting(lk):
    j = box(lk)
    for g in j["g"]:
        if g["s"] in ACTIVE and g["s"] != "draft":
            g["light_dirty"] = True
    sweep(lk, j)
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
        rejected(lk, j, temp, 4)
        return False
    light = False
    if kind == 3:
        other = next((x for x in j["g"] if x["to"] == frm and x["s"] in ACTIVE), None)
        # Opposing inviter roles must be arbitrated before an ID-only lookup.
        # Equal IDs cannot carry an END: it would also cancel the winning invite.
        if other and other["i"] == lk.node.ship and other["s"] in ("draft", "wait"):
            if frm > lk.node.ship and gid(other) == ident:
                return False
            if frm < lk.node.ship:
                if gid(other) == ident:
                    lk.out[:] = [o for o in lk.out if not belongs(o, other)]
                    keep(lk)
                    j["g"].remove(other)
                else:
                    terminal(other, "called")
                    end(lk, other, 3)
                other = g = None
        if g is not None:
            repeat(lk, g)
            store(lk, j)
            return False
        if other or sum(x["s"] in ACTIVE for x in j["g"]) >= 3:
            rejected(lk, j, fresh(lk, frm, ident, frm, "called"), 5)
            return False
        # Keep one completed game per opponent, for the reveal screen and rematch.
        j["g"] = [x for x in j["g"] if x["to"] != frm or x["s"] in ACTIVE]
        room(j)
        g = fresh(lk, frm, ident, frm, "invited")
        g["c"] = hexlify(b[3:11]).decode()
        j["g"].append(g)
        light = True
    elif g is None:
        tick = lvship.ticks_ms()
        previous = getattr(lk, "duel_unknown", None)
        elapsed = lvship.ticks_diff(tick, previous) if previous is not None else 3600000
        if kind not in (8, 9) and (elapsed >= 3600000 or elapsed < 0):
            temp = fresh(lk, frm, ident, frm, "called")
            temp["unknown"] = True
            sync(lk, temp)
            j["e"] = [x for x in j.get("e", []) if x["to"] != frm] + [temp]
            store(lk, j)
            lk.duel_unknown = tick
        return False
    elif kind == 4:
        if g["s"] != "wait" and not (g.get("why") == 2 and not g.get("c")):
            return False
        g["c"] = hexlify(b[3:11]).decode()
        if g["s"] == "wait":
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
                store(lk, j)
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
                g["h"] += chr(65 + cell) + chr(97 + r)
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
            g["h"] += chr(65 + cell) + chr(97 + r)
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
                terminal(g, "cheat")
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
            g["why"] = 2
            g["win"], g["s"] = True, "reveal"
            reveal(lk, g)
            if not g.get("c"):
                # The opponent resigned before committing: there were no answers
                # to verify. Our own committed field still goes to the opponent.
                g["verified"] = 1
                finish(lk, j, g)
        elif why == 6:
            if g.get("counted"):
                j["r"][str(frm)][0 if g["win"] else 1] -= 1
                g["counted"] = 0
            terminal(g, "cheat")
        elif g["s"] in ACTIVE:
            terminal(g, {1: "declined", 3: "called", 4: "version", 5: "busy"}.get(why, "called"))
    elif kind == 9:
        n, cell, r, state = b[2:6]
        g["nl"] = bool(state & 128)
        state &= 127
        if n > 71 or state > 4:
            return False
        # Stop-and-wait means normally at most one completed answer is missing.
        # If both views say 'my turn', keep the lower ship's view. The higher
        # ship can rewind its existing transcript, or recover its one lost answer.
        conflict = (state == 1 and g["s"] == "active" and g.get("p") is None and
                    mine(lk, g, g["n"] + 1) and not mine(lk, g, n + 1))
        if conflict and lk.node.ship > frm:
            if n <= g["n"]:
                g["h"] = g["h"][:2 * n]
                g["n"] = n
                if n:
                    last = history(g)[-1]
                    if last[1:] != [cell, r]:
                        g["h"] = g["h"][:-2] + chr(65 + cell) + chr(97 + r) if cell < 36 and r in (0, 1, 2, 3, 4) else g["h"]
                    g["last"] = [5 if mine(lk, g, n) else 6,
                                 hexlify(ident + bytes((n, cell)) + (b"" if mine(lk, g, n) else bytes((r,)))).decode()]
                store(lk, j)
                return False
            if n == g["n"] + 1 and mine(lk, g, n) and cell < 36:
                g["p"] = cell
                g["last"] = [5, hexlify(ident + bytes((n, cell))).decode()]
                store(lk, j)
                return take(lk, frm, 6, ident + bytes((n, cell, r)) + bytes(6))
        elif conflict:
            sync(lk, g)
            store(lk, j)
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
    probe = getattr(lk.sh, "duel_probe", None)
    if probe:
        probe()
    return light


def action(lk, b):
    j = box(lk)
    if sweep(lk, j):
        store(lk, j)
    a, to = b.get("action"), b.get("to")
    if not integer(to, 0, 7) or to == lk.node.ship:
        return 400, {"err": "Pick a crewmate."}
    if len(lk.out) >= 24 and a not in ("resign", "call", "new", "discard"):
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
    elif a == "discard":
        if g["s"] != "draft":
            return 409, {"err": "Your fleet is locked."}
        j["g"].remove(g)
    elif a in ("lock", "invite", "accept"):
        if g.get("l") and g["s"] in ("wait", "active") and any(z[0] in (3, 4) for z in g.get("q", [])):
            store(lk, j)
            return 200, {"ok": True}
        if g["s"] not in ("draft", "invited") or g.get("l") or (a == "accept" and g["s"] != "invited") or (a == "invite" and g["s"] != "draft"):
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
        terminal(g, "declined")
        end(lk, g, 1)
    elif a == "resign":
        if g["s"] not in ("wait", "invited", "active"):
            return 409, {"err": "No duel is playing."}
        terminal(g, "called")  # discard obsolete moves before the terminal exchange
        g["s"], g["win"] = "reveal", False
        g["why"] = 2
        end(lk, g, 2)
        reveal(lk, g)
        if not g.get("c"):
            g["verified"] = 1
            finish(lk, j, g)
    elif a == "call":
        t = now(lk)
        if t is None or g.get("t") is None or t - g["t"] < 3 * DAY or (g["s"] == "active" and mine(lk, g, g["n"] + 1) and g.get("p") is None):
            return 409, {"err": "Wait three days for the next move."}
        terminal(g, "called")
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
        x = dict((k, g.get(k)) for k in ("id", "to", "s", "n", "p", "t", "win", "why", "their", "update", "nl"))
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
