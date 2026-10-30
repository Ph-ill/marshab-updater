# Asteroid duel: loaded per item/request, never kept on the Link.
# History uses two ASCII characters per shot (cell and answer); n is its index.
import os
import lvship
from binascii import hexlify, unhexlify
from lvlivein import load, save, send, sha256, keep, probe

DAY = 86400
F = "/duel.json"
ACTIVE = ("draft", "wait", "invited", "active", "reveal")


def integer(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def layout_call(name, *args):
    lvship.free()
    import lvduellayout
    try:
        value = getattr(lvduellayout, name)(*args)
        probe("layout")
        return value
    finally:
        lvship.drop("lvduellayout")


def fleet(layout):
    return layout_call("fleet", layout)


def encode(slots):
    return layout_call("encode", slots)


def commit(g, layout, salt):
    return sha256(b"LVD1" + g + layout + salt).digest()[:8]


def result(layout, fired, cell):
    return layout_call("result", layout, fired, cell)


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
    # Start a transaction without garbage from an earlier phone/radio dispatch.
    # This is admission, not a collecting heap probe: parsing is still sampled.
    lvship.free()
    return load(lk.sh.data + F) or {"g": [], "r": {}}


def store(lk, j):
    # Write-ahead intents: no item may reach livebox before its game state does.
    lvship.free()
    save(lk.sh.data + F, j)
    lk.v += 1
    probe()
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
                # Each durable enqueue is a separate persistence phase. Do not
                # carry the previous file's serialization garbage into it.
                lvship.free()
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
        lvship.free()
        save(lk.sh.data + F, j)


def terminal(g, state):
    g["s"] = state
    g["q"] = [z for z in g.get("q", []) if allowed(g, z[0])]


def rejected(lk, j, g, why):
    # At most seven pending replies, one per sender. Retire after acknowledgement.
    g = {"to": g["to"], "id": g["id"], "s": "called"}
    j["e"] = [x for x in j.get("e", []) if x["to"] != g["to"]]
    j["e"].append(g)
    end(lk, g, why)


def gid(g):
    return unhexlify(g["id"])


def history(g):
    b = g["h"]
    for i in range(0, len(b), 2):
        yield (i // 2 + 1, ord(b[i]) - 65, ord(b[i + 1]) - 97)


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
    h = g["h"]
    c, r = (ord(h[-2]) - 65, ord(h[-1]) - 97) if h else (255, 255)
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
    if len(b) != 11 or not 3 <= kind <= 9:
        return False
    while True:
        j = box(lk)
        if sweep(lk, j):
            store(lk, j)
        unknown = getattr(lk, "duel_unknown", None)
        import lvduelrx
        try:
            change = lvduelrx.take(lk, frm, kind, b, j)
        finally:
            lvship.drop("lvduelrx")
            lvduelrx = None
        if change is None:
            return False
        # Rule evaluation and persistence are separate phases. Release the
        # receiver's bytecode and scratch lists; store reclaims that phase
        # before allocating save buffers.
        try:
            store(lk, j)
        except Exception:
            # An unknown-game reply is throttled only once it is durable.
            lk.duel_unknown = unknown
            raise
        light, retry = change
        if retry is None:
            p = getattr(lk.sh, "duel_probe", None)
            if p:
                p(j)
            return light
        # Recovery commits its rewind/pending move before accepting the answer.
        # Reload the durable box, as the former recursive receiver did.
        kind, b = retry
        j = change = None


def action(lk, b):
    import lvduelaction
    try:
        return lvduelaction.action(lk, b, globals())
    finally:
        lvship.drop("lvduelaction")


def view(lk):
    maintain(lk)
    import lvduelview
    try:
        return lvduelview.expanded(lk)
    finally:
        lvship.drop("lvduelview")
