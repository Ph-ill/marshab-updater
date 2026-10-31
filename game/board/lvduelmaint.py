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
        epoch = now(lk)
        age = g.get("age", 0)
        # A "tu" stamp predates the move (lvduel.moved): never idle time.
        if epoch is not None and g.get("t") is not None and not g.get("tu"):
            age = max(age, epoch - g["t"])
        age = max(0, min(3 * DAY, age))
        # z[6]: made with the clock unknown (after every boot: the Pico has no
        # RTC), the last activity's wall time as saved, until a phone sets the clock.
        # None for a "tu" stamp: that move's wall time is unknown, so no credit.
        base = g.get("t") if epoch is None and not g.get("tu") else None
        z = [t, 0, sig, -21600000 if g["s"] == "active" else 0, None, -age * 1000,
             base]
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
            z[5] = z[1]
            z[6] = None
    if z[6] is not None:
        # The first time the clock is known again, time spent switched off counts
        # (review 0.3.1-4 #6): idle is at least the wall time since the saved
        # activity, if that gap is plausible (0 to 30 days). Only once: from then on
        # reconcile's same-boot rebasing keeps corrections, either way, monotonic.
        epoch = now(lk)
        if epoch is not None:
            gap = epoch - z[6]
            if 0 <= gap <= 30 * DAY:
                z[5] = min(z[5], z[1] - min(3 * DAY, gap) * 1000)
            z[6] = None
    return z


def age(lk, g):
    z = timer(lk, g)
    return (z[1] - z[5]) // 1000


def reconcile(lk, g):
    # Same-boot idle age is authoritative. Rebase persisted epoch deadlines
    # after learning/correction; checkpoint unknown-clock uptime hourly too.
    idle = min(3 * DAY, age(lk, g))
    t = now(lk)
    stamp = t - idle if t is not None else None
    changed = False
    if stamp is not None and (g.get("tu") or g.get("t") is None or abs(g["t"] - stamp) > 2):
        g["t"] = stamp
        g.pop("tu", None)
        changed = True
    if abs(g.get("age", 0) - idle) >= 3600 or (idle == 0 and g.get("age", 0)):
        g["age"] = idle
        changed = True
    return changed


def reconcile_all(lk, j):
    changed = False
    for g in j["g"]:
        if g["s"] in ACTIVE:
            changed = reconcile(lk, g) or changed
    return changed


def sweep(lk, j):
    web = getattr(lk.sh, "web", None)
    if web is not None and web.busy > 0 and all(
            g["s"] not in ("draft", "wait", "invited") for g in j["g"]):
        lk.duel_due = 0
        return reconcile_all(lk, j)
    changed = False
    for g in j["g"][:]:
        if g["s"] not in ACTIVE:
            continue
        z = timer(lk, g)
        changed = reconcile(lk, g) or changed
        idle = (z[1] - z[5]) // 1000
        if g["s"] == "draft" and idle >= 3 * DAY:
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
        if g["s"] in ("wait", "invited") and idle >= 3 * DAY:
            terminal(g, "called")
            end(lk, g, 3)
            changed = True
        if z[1] - z[3] >= 21600000 and (g["s"] == "reveal" or (g["s"] == "active" and (g.get("p") is not None or not mine(lk, g, g["n"] + 1)))):
            p = lk.ble.peers.get(g["to"])
            if p is not None and p.seen:
                before = g.get("sync")
                sync(lk, g)
                changed = changed or before != g.get("sync")

    return changed
