# Expiry and recovery scheduling, released before radio rules and persistence.
import lvship
from lvduel import ACTIVE, DAY, end, gid, mine, now, sync, terminal


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
