# Durable duel publication, independent of receive-rule module lifetimes.
import lvship
from binascii import hexlify, unhexlify
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
        due = False
        for g in j["e"]:
            z, ri = g.get("rj"), g.get("ri")
            if g in retained or not (z or ri):
                continue
            x = [x for x in retained if x["to"] == g["to"] and x.get("o")]
            if x:
                # Unreachable with one owed stub per crewmate (review 0.3.1-10 #1):
                # hand the reply on, never a waiting END replaced by a SYNC (#4).
                if z and (z[1] or not x[-1].get("rj")):
                    x[-1]["rj"] = z
                if ri:
                    x[-1]["ri"] = ri
                continue
            if ri:
                # The invitation held on this stub (lvduelother) opens now, as an
                # INVITE would have: room for it, or END 5 with three duels open.
                # With no finished game free to drop, it stays held a little longer.
                old = [x for x in j["g"] if x["s"] not in ACTIVE]
                if len(j["g"]) - len(old) >= 3:
                    z = [ri[0], 5]
                elif len(j["g"]) >= 3 and all(pending(lk, x) for x in old):
                    retained.append(g)
                    continue
                else:
                    if len(j["g"]) >= 3:
                        j["g"].remove([x for x in old if not pending(lk, x)][0])
                    c = lk.sh.clock
                    j["g"].append({"id": ri[0], "to": g["to"], "i": g["to"], "s": "invited",
                                   "n": 0, "h": "", "p": None, "c": ri[1],
                                   "t": int(c.epoch_ms()) // 1000 if c.known() else None})
                    changed = True
            if z:
                # A reply that waited on this stub (lvduel.defer), queued now.
                b = unhexlify(z[0]) + (bytes((z[1],)) if z[1] else
                    bytes((0, 255, 255, 4 if lk.cfg.get("dl", True) else 132)))
                x = {"to": g["to"], "id": z[0], "s": "called",
                     "q": [[8 if z[1] else 9, hexlify(b + bytes(11 - len(b))).decode()]]}
                if not z[1]:
                    x["unknown"] = True
                retained.append(x)
                due = True
        if len(retained) != len(j["e"]) or due:
            j["e"] = retained
            changed = True
        if due:
            flush(lk, j)
    # The caller checkpoints only after releasing this helper's globals.
    return changed


def gid(g):
    return unhexlify(g["id"])


def pending(lk, g):
    return bool(g.get("q")) or any(belongs(o, g) for o in lk.out)


def queued(lk, g, kind, body):
    return any(o[0] == g["to"] and o[1][0] == kind and o[1][5:16] == body for o in lk.out)
