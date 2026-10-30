# Durable duel publication, independent of receive-rule module lifetimes.
import lvship
from binascii import unhexlify
import lvlivein as I

F = "/duel.json"
ACTIVE = ("draft", "wait", "invited", "active", "reveal")


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
        I.keep(lk)


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
                I.send(lk, kind, g["to"], body)
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
        I.save(lk.sh.data + F, j)


def gid(g):
    return unhexlify(g["id"])


def pending(lk, g):
    return bool(g.get("q")) or any(belongs(o, g) for o in lk.out)


def queued(lk, g, kind, body):
    return any(o[0] == g["to"] and o[1][0] == kind and o[1][5:16] == body for o in lk.out)
