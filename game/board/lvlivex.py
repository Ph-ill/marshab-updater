# The once-in-a-while parts of lvlive.py (Hail, 0.3.0): install (the checks and the hooks),
# a Link's start (its box file read back), dial/completion, expiry/reset and the fault net.
# Loaded for each and dropped
# straight after (lvship.drop), so none of it stays resident next to two phones and a sync.
# Common box-file and retry-state helpers are lvlivein's, loaded alongside and dropped too.
import lvship
from lv import sync as S
from binascii import unhexlify
import lvlive as L
from lvlivein import load, save, keep, nx


def forget(sh):
    # Reset this ship (lvcode.reset, 0.3.0 review R2 m10): the hails that came in and
    # no phone has read go, and so do this ship's own still waiting (FIXREVIEW2 minor 10:
    # Reset says everyone's hails go). The rest of livebox.json stays: its epoch, sequence
    # and each sender's highest taken (replay protection).
    L = getattr(sh, "live", None)
    if L is not None:
        del L.inb[:]
        del L.out[:]
    p = sh.data + "/livebox.json"
    b = load(p)
    if b and (b.get("i") or b.get("o")):
        b["i"] = []
        b["o"] = []
        save(p, b)


def expire(lk):
    """Waiting items from an earlier day go (hail.json shows an undelivered hail as "Didn't
    go" for a day: lvliveapi._hl); a "seen" for a crewmate who never came back goes too."""
    d = lk.sh.clock.date()
    k = []
    for o in lk.out:
        if o[1][0] > 2:                # duels survive the day turning
            continue
        if d and not isinstance(o[2], int):
            o[2] = d                    # queued before the clock was known: today's
        elif d and o[2] < d:            # (a clock set back expires nothing: FIXREVIEW3 f2)
            k.append(o)
    if k:
        for o in k:
            lk.out.remove(o)
        lk.n["gone"] += len(k)
        keep(lk)


def failed(lk, x, now):
    # a dial that got nowhere: from the second in a row, back off 1, 2, 4... min, MAXB at most
    x[3] += 1
    if x[3] >= 2:
        x[1] = now + min(L.MAXB, L.EVERY << min(x[3] - 2, 8))


def dial(lk, b, now):
    """Dial one ship with a hail waiting that can take one now (Link.poll, idle radio): heard
    in the last L.NEAR, its own next dial due, and none to anyone for L.GAP. Of those, the
    one whose last hail dial is oldest (never dialled first), so ships that keep failing
    take turns with, and can't starve, one that just came back (FIXREVIEW2 J1). Sets
    lk.due, the earliest time another look is worth an import."""
    expire(lk)
    wait = 5000                     # nobody in range: look again in 5 s
    best = None
    seen = []
    for o in lk.out:
        to = o[0]
        if to in seen:
            continue
        seen.append(to)
        p = b.peers.get(to)
        x = nx(lk, to)
        if (x[2] or x[3]) and not L.near(now, p, L.OUT):
            x[0] = x[1] = x[2] = x[3] = 0   # out of range a while: back, it starts over (and first)
        if not L.near(now, p) or p.addr is None or not p.info or not p.info.get("cap"):
            continue
        # GAP between hail dials; a crewmate not dialled yet (new, or back in range) waits
        # only a quarter of it, so a run of dials to ships that won't answer can't hold up
        # one that just came back (FIXREVIEW2 J1)
        g = lk.gap if x[2] or not lk.gap else lk.gap - L.GAP + L.GAP // 4
        if p.info["busy"] or not L.due(now, x[1]) or not L.due(now, g):
            r = max(0 if L.due(now, x[1]) else L.dt(x[1], now), 0 if L.due(now, g) else L.dt(g, now))
            wait = min(wait, max(1000, r))
            continue
        a = L.dt(now, x[2]) if x[2] else 0x3FFFFFFF        # how long since its last dial
        if best is None or a > best[0]:
            best = (a, to, p, x)
    if best is None:
        lk.due = now + wait
        return
    a, to, p, x = best
    x[0] += 1
    x[1] = now + (L.FAST if x[0] < 2 else L.EVERY)
    x[2] = now or 1
    lk.gap = now + L.GAP
    lk.forced = (p, p.fails, p.next_try, lk._for(to))
    lk.n["dial"] += 1
    b._connect(p, now)
    if b.state != "connecting":     # the stack said no: put the backoff back
        f, lk.forced = lk.forced, None
        p.fails, p.next_try = f[1], f[2]
        lk.n["dial_fail"] += 1
        failed(lk, x, now)
    lk.due = 0                      # look again once the radio is idle


def done(lk, f, p, s, now):
    """After a session this Link dialled: count it, give the stack its backoff back."""
    ok = s is not None and s.complete()
    lk.n["dial_ok" if ok else "dial_fail"] += 1
    p.fails, p.next_try = f[1], f[2]
    x = nx(lk, p.ship)
    # anything left: the next session, but only if this one moved something (an
    # item the peer won't take, say a bad mac, keeps to the 2-then-1-a-minute dials)
    if ok:
        x[3] = 0
        k = lk._for(p.ship)
        if 0 < k < f[3]:                # moved some, more for them: straight on (the GAP
            x[0], x[1] = 0, now + 1000  # is between crewmates, not within one)
            lk.gap = 0
    else:
        failed(lk, x, now)
    lk.due = 0


def setup(lk, ship, data, cfg):
    import os
    lk.sh, lk.ble, lk.node = ship, ship.ble, ship.node
    lk.f = data + "/livebox.json"
    lk.cf = data + "/live.json"
    lk.cfg = cfg or {}
    lk.v = 1
    lk.nx = {}            # ship -> [dials, next ms, last dial ms (0 never), failures in a row]
    lk.forced = None
    lk.due = 0            # Link.poll: no dial is worth a look before this
    lk.now = 0
    lk.gap = 0            # no hail dial (to anyone) before this
    lk.tf = 0             # MemoryErrors in a row (Link.fault: passing, up to L.TRANSIENT)
    lk.cm = 0             # the core's MemoryErrors in a row (Link.poll; not Hail's)
    lk.et = 0             # the last MemoryError's time (Link.calm)
    lk.hx = None          # an error in Hail's parts of a hooked call, for Link.poll's fault()
    lk.duel_due = 0
    lk.duel_times = {}    # monotonic retry/activity stamps, invalid across boots
    lk.duel_unknown = None
    lk.n = {"dial": 0, "dial_ok": 0, "dial_fail": 0, "in": 0, "acked": 0, "dup": 0, "bad": 0, "out": 0,
            "held": 0, "oom": 0, "old": 0, "gone": 0}
    b = load(lk.f) or {}
    lk.ep = b.get("e")
    if lk.ep is None:
        lk.ep = os.urandom(1)[0]
    lk.seq = b.get("s", 0)
    d = ship.clock.date()
    # out: [to, item, the day it was queued]; in: [from, item, arrived (epoch ms or None),
    # arrived (uptime ms: this boot's only, so None once read back)]
    lk.out = [[o[0], unhexlify(o[1]), o[2] if len(o) > 2 else d] for o in b.get("o", ())]
    lk.inb = [[o[0], unhexlify(o[1]), o[2] if len(o) > 2 else None, None] for o in b.get("i", ())]
    lk.hw = {}
    for k, v in b.get("h", {}).items():
        lk.hw[int(k)] = v
    lk.lc = b.get("l") or [0, 0]


def fault(lk, e):
    sh = lk.sh
    try:
        import sys
        sys.print_exception(e)
    except Exception:
        pass
    why = "fault: %s" % (type(e).__name__,)
    sh.say("live: off after a fault: %r" % (e,))
    L.unhook(lk)
    sh.live = None
    sh.live_why = why[:80]
    try:
        c = load(lk.cf) or {}
        c.update({"on": False, "why": why[:80], "at": sh.clock.date()})
        save(lk.cf, c)
    except Exception:
        pass
    try:
        if lk.ble.state != "idle":
            lk.fin0(lk.now, "live fault")
    except Exception:
        pass


def core_ok():
    try:
        import lvfrozen
        if not str(getattr(lvfrozen, "CORE", "")).startswith("2661c2144844"):
            return False
    except ImportError:
        pass                                # a desk run: the sources are the core
    import lv
    o = getattr(lv, "OVERRIDES", ()) or ()
    return "ble" not in o and "sync" not in o


def crash(data):
    """The crash board/lvsafe.py last counted, as a short fingerprint, or None. Only a
    counted crash (fault.json "n" >= 1) in Hail's own code (fault.json "live": main.py's
    crashed() found lvlive*/lvflick in the traceback; 0.3.0 review R2 M3) counts: a web
    server MemoryError or a story bug is no reason to turn Hail off, nor is a boot note
    alone ("boot": a file put back, a ship.json that plays but isn't whole). The file is
    set aside (fault.last.json) after 10 healthy minutes, so a crash only turns Hail off at
    the boot straight after it."""
    j = load(data + "/fault.json")
    if not j or not j.get("live"):
        return None
    try:
        n = int(j.get("n", 0))
    except (TypeError, ValueError):
        n = 1                               # a count that won't read: take it as a crash
    if n < 1:
        return None
    return ("%s|%s|%s" % (n, j.get("why"), j.get("up")))[:120]


def install(ship, data):
    cf = data + "/live.json"
    c = load(cf) or {}
    why = None
    fx = crash(data)
    if fx is not None and getattr(ship, "trial", False) and c.get("fx") != fx:
        # The first boot of an update (often installed from safe mode, after that very
        # crash): the crash was the old software's, so it doesn't turn Hail off; noted as
        # dealt with, so the boot after the trial is kept doesn't either (0.3.0 R1 m2).
        c["fx"] = fx
        save(cf, c)
    # (a phone turned it back on since this very crash: leave it on)
    if fx is not None and c.get("on", True) and c.get("fx") != fx:
        why = "restarted after a fault"
        c.update({"on": False, "why": why, "at": ship.clock.date()})
        save(cf, c)
    if not L.ON:
        why = "paused for the fleet"
    elif not c.get("on", True):
        why = c.get("why") or "turned off"
    elif getattr(ship, "ble", None) is None:
        why = "no Bluetooth"
    elif not core_ok():
        why = "core changed"
    elif getattr(ship, "fk", None) is None:
        why = "no fleet key"
    ship.live_why = why
    ship.live = None
    n = getattr(ship, "node", None)
    try:
        delattr(n, "advert")                # (a paused advert: the plain one back first)
    except (AttributeError, TypeError):
        pass
    if why:
        if why != "core changed" and n is not None and getattr(ship, "ble", None) is not None:
            L.pause(n)                      # Hail here, paused: crewmates' pages say so
            ship.ble.adv = None
        return None
    lk = L.Link()
    setup(lk, ship, data, c)
    b = lk.ble
    lk.poll0, lk.fin0, lk.adv0 = b.poll, b._finish, lk.node.advert
    if b.cfg.get("peer_ttl_ms", 0) < 86400000:
        b.cfg["peer_ttl_ms"] = 86400000     # remember crewmates' addresses for a day
    b.poll, b._finish = lk.poll, lk.finish
    lk.node.advert = lk.advert
    S.Session, S.parse_advert = L.Session, L.parse      # (both stay: plain without a Link)
    b.adv = None                                        # (the advert made again, with the bit)
    lk.node.live = ship.live = lk
    return lk
