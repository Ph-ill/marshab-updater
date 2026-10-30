# Expiry and recovery scheduling, released before radio rules and persistence.
import lvship
from binascii import unhexlify

ACTIVE = ("draft", "wait", "invited", "active", "reveal")
DAY = 86400


def now(lk):
    c = lk.sh.clock
    return int(c.epoch_ms()) // 1000 if c.known() else None


def gid(g):
    return unhexlify(g["id"])


def mine(lk, g, n):
    return (n % 2 == 0) == (g["i"] == lk.node.ship)


def rule(name, *args):
    # Timer checks need no action/receive rules unless a retry or expiry is due.
    import sys
    loaded = "lvduel" in sys.modules
    import lvduel
    try:
        return getattr(lvduel, name)(*args)
    finally:
        if not loaded:
            lvship.drop("lvduel")


def sync(lk, g):
    return rule("sync", lk, g)


def terminal(g, state):
    return rule("terminal", g, state)


def end(lk, g, why):
    return rule("end", lk, g, why)


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
    web = getattr(lk.sh, "web", None)
    if web is not None and web.busy > 0 and all(
            g["s"] not in ("draft", "wait", "invited") for g in j["g"]):
        lk.duel_due = 0
        changed = False
        for g in j["g"]:
            if g["s"] in ACTIVE and g.get("t") is None and t is not None:
                g["t"] = t
                changed = True
        return changed
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
