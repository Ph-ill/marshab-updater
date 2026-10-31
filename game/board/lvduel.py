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
    import lvduelaction
    try:
        return lvduelaction.encode(slots)
    finally:
        lvship.drop("lvduelaction")
        lvduelaction = None


def commit(g, layout, salt):
    return sha256(b"LVD1" + g + layout + salt).digest()[:8]


def result(layout, fired, cell):
    return layout_call("result", layout, fired, cell)


def now(lk):
    c = lk.sh.clock
    return int(c.epoch_ms()) // 1000 if c.known() else None


def moved(lk, g):
    # Stamp a move's wall time. With the clock unknown (every boot until a phone
    # sets it) keep the old stamp and mark it "tu": the move came at an unknown
    # time after it (review 0.3.1-6 #1). No switched-off time is credited from such
    # a stamp; reconcile writes an exact one, from same-boot idle, once the clock
    # is known. Under-counting only delays Call it.
    t = now(lk)
    if t is None:
        g["tu"] = 1
    else:
        g["t"] = t
        g.pop("tu", None)


def maint_call(name, *args):
    import sys
    loaded = "lvduelmaint" in sys.modules
    if not loaded:
        # Cleanup/publication can precede scheduling in this transaction.
        # Release its discarded helpers and parser scratch before importing
        # the separate scheduler, not inside the maintenance heap probe.
        lvship.free()
    import lvduelmaint
    try:
        value = getattr(lvduelmaint, name)(*args)
        probe("maintenance")
        return value
    finally:
        # sweep can call sync, which asks for a timer from this same helper.
        # Only the outer owner releases it, never a nested call.
        if not loaded:
            lvship.drop("lvduelmaint")


def timer(lk, g):
    return maint_call("timer", lk, g)


def box(lk):
    # Start a transaction without garbage from an earlier phone/radio dispatch.
    # This is admission, not a collecting heap probe: parsing is still sampled.
    lvship.free()
    return load(lk.sh.data + F) or {"g": [], "r": {}}


def persist(name, *args):
    import lvduelstore
    try:
        return getattr(lvduelstore, name)(*args)
    finally:
        lvship.drop("lvduelstore")
        lvduelstore = None


def store(lk, j):
    from lvlivein import duel_store
    # Observe each new activity signature in the transaction that creates it,
    # before a later clock correction could be mistaken for idle time.
    maint_call("reconcile_all", lk, j)
    return duel_store(lk, j)


def cleanout(lk, j, orphans=False):
    return persist("cleanout", lk, j, orphans)


def flush(lk, j):
    if persist("flush", lk, j):
        lvship.free()
        save(lk.sh.data + F, j)


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
    return kind in ((6, 7, 8) if g["s"] == "done" else (8,))


def gid(g):
    return unhexlify(g["id"])


def pending(lk, g):
    return bool(g.get("q")) or any(belongs(o, g) for o in lk.out)


def queued(lk, g, kind, body):
    return any(o[0] == g["to"] and o[1][0] == kind and o[1][5:16] == body for o in lk.out)


def terminal(g, state):
    g["s"] = state
    g["q"] = [z for z in g.get("q", []) if allowed(g, z[0])]


def owed(j, to):
    # A retired game's END/REVEAL still on its way to this crewmate (see room).
    return any(x["to"] == to and x.get("o") for x in j.get("e", []))


def defer(j, to, ident, why):
    # A reply to a crewmate this ship still owes a stub waits on that stub ("rj",
    # one per crewmate, why 0 for the unknown-game SYNC); flush sends it once the
    # stub's items are acked (review 0.3.1-9 #3). An END outranks a SYNC.
    x = [x for x in j["e"] if x["to"] == to and x.get("o")][-1]
    if why or not x.get("rj"):
        x["rj"] = [ident, why]


def rejected(lk, j, g, why):
    # At most seven pending replies, one per sender. Retire after acknowledgement.
    # A retired game's stub outranks a reply: its END/REVEAL decides a result on
    # the other ship (review 0.3.1-8 #1). The reply waits on the stub (defer).
    if owed(j, g["to"]):
        defer(j, g["to"], g["id"], why)
        return
    g = {"to": g["to"], "id": g["id"], "s": "called"}
    j["e"] = [x for x in j.get("e", []) if x["to"] != g["to"]]
    j["e"].append(g)
    end(lk, g, why)


def history(g):
    b = g["h"]
    for i in range(0, len(b), 2):
        yield (i // 2 + 1, ord(b[i]) - 65, ord(b[i + 1]) - 97)


def mine(lk, g, n):
    return (n % 2 == 0) == (g["i"] == lk.node.ship)


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
    if g.get("mutual"):
        terminal(g, "done")
        return
    r = j["r"].get(str(g["to"]), [0, 0])
    r[0 if g["win"] else 1] += 1
    j["r"][str(g["to"])] = r
    g["counted"] = 1
    terminal(g, "done")


def sweep(lk, j, receiving=False):
    web = getattr(lk.sh, "web", None)
    if (receiving or (web is not None and web.busy > 0)) and all(
            g["s"] not in ("draft", "wait", "invited") for g in j["g"]):
        # Active-game retry/light scheduling can wait for HTTP to release its
        # snapshot, or the radio to finish its current receive transaction.
        # Do not defer draft/invitation expiry or clock backfilling.
        # Actual SHOT/ANSWER mutation and durable publication still run now.
        lk.duel_due = 0
        return maint_call("reconcile_all", lk, j)
    return maint_call("sweep", lk, j)


def maintain(lk):
    from lvlivein import duel_maintain
    return duel_maintain(lk)


def lighting(lk):
    j = box(lk)
    for g in j["g"]:
        if g["s"] in ACTIVE and g["s"] != "draft":
            g["light_dirty"] = True
    sweep(lk, j)
    store(lk, j)


def retire(lk, j, g):
    # Drop a finished game. If its END/REVEAL hasn't been delivered, keep a small
    # stub in j["e"] (crewmate, id, state, reason, intents): flush and cleanout keep
    # it, and its queued items, until they are acked (review 0.3.1-8 #1). Still one
    # j["e"] entry per crewmate, except: a game opened by the INVITE that retired an
    # owed game, itself finished before that stub's items were acked. The earlier
    # stub is then kept beside it, never replaced (review 0.3.1-9 #5). An INVITE
    # from a crewmate with a stub is refused (lvduelother), so never more than two.
    j["g"].remove(g)
    if pending(lk, g):
        x = {"to": g["to"], "id": g["id"], "s": g["s"], "o": 1}
        if g.get("why") is not None:
            x["why"] = g["why"]
        if g.get("q"):
            x["q"] = g["q"]
        j["e"] = [y for y in j.get("e", []) if y["to"] != g["to"] or (y.get("o") and pending(lk, y))]
        j["e"].append(x)


def room(lk, j):
    while len(j["g"]) >= 3:
        old = next((g for g in j["g"] if g["s"] not in ACTIVE), None)
        if old is None:
            return
        retire(lk, j, old)


def fresh(lk, to, ident, inviter, state):
    return {"id": hexlify(ident).decode(), "to": to, "i": inviter, "s": state,
            "n": 0, "h": "", "p": None, "t": now(lk)}


def receive(lk, frm, kind, b, j=None):
    if j is None:
        j = box(lk)
    if sweep(lk, j, True):
        store(lk, j)
    if kind == 7:
        g = next((x for x in j["g"] if x["to"] == frm and gid(x) == b[:2]), None)
        if g is not None:
            # Proof needs layout/replay, not the shot receiver or the larger
            # invitation/recovery rules beside that same private game box.
            return j, layout_call("proof", lk, frm, b, j, g)
    import lvduelrx
    try:
        change = lvduelrx.take(lk, frm, kind, b, j)
    finally:
        lvship.drop("lvduelrx")
        lvduelrx = None
    return j, change


def take(lk, frm, kind, b):
    if len(b) != 11 or not 3 <= kind <= 9:
        return False
    while True:
        unknown = getattr(lk, "duel_unknown", None)
        j, change = receive(lk, frm, kind, b)
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
