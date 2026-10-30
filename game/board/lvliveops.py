# Synchronous Hail operations and snapshots; released before HTTP streaming.
import lvship
import lvlive
import lvliveapi as A
from binascii import hexlify
from lvliveapi import PHRASES, DAY_MAX, HOUT, HIN, SHOW, BACK_MS, F

def _in():
    # Box operations are synchronous phases; do not inherit discarded parsed
    # files or encoder garbage from the preceding phase of this request.
    lvship.free()
    import lvlivein
    return lvlivein



def _ep(sh):
    e = sh.clock.epoch_ms() if sh.clock.known() else None
    return int(e) if e is not None else None



def _hl(sh):
    j = _in().load(sh.data + F) or {}
    d = sh.clock.date()
    if "o" not in j or "i" not in j:
        j = {"d": d, "o": [], "i": [], "n": 0}
    jd = j.get("d")
    if jd is None:
        j["d"] = d                  # (started before the ship knew the date: today's)
    elif d and (not isinstance(jd, int) or jd < d):
        # A new day: receipts that came in first go on the day they belong to (FIXREVIEW2
        # J4); undelivered hails expire (lvlivein.expire takes them out of the queue) and are
        # listed as "Didn't go" for one more day; the rest start again. Only forward: a
        # clock set back a day changes nothing (FIXREVIEW3 f2).
        L = sh.live
        if L is not None:
            drain(sh, j, True)
            import lvlivein
            lvlivein.expire(L)
        g = [o[:4] + [4] for o in j.get("o", ()) if o[4] < 2]
        j = {"d": d, "o": g, "i": [], "n": 0}
        _in().save(sh.data + F, j)        # (now: the receipts it took are in it, not in the box)
    return j



def drain(sh, j, rc=False):
    """Move what lvlive took off the air into hail.json (rc: only the receipts)."""
    L = sh.live
    if L is None or not L.inb:
        return False
    now = _ep(sh)
    left = []
    for z in L.inb:
        frm, b, t, up = z
        k = b[0]
        if k == 0 or k == 2:
            # a receipt: Delivered (ack) or Seen, also for one listed as "Didn't go" (its
            # receipt was late: it did go); never back from Seen to Delivered
            r, v = hexlify(b[5:8]).decode(), 2 if k == 0 else 3
            for o in j["o"]:
                if o[1] == frm and o[0] == r and (o[4] == 4 or o[4] < v):
                    o[4] = v
        elif rc:
            left.append(z)
        elif k == 1:
            if t is None and now and up is not None:
                t = now - max(0, lvlive.dt(L.now, up))  # before the clock was known: from uptime
            # sent: the sender's clock to the minute (body bytes 3-4, lvlivein.mins), as
            # epoch ms near the arrival time and never after it; None if it didn't say
            # (or this ship doesn't know when it arrived)
            sm, a = b[8] << 8 | b[9], t
            if a and sm and sm != 65535:
                a0 = a // 60000
                sm = min(a, (a0 - ((a0 - sm) & 65535)) * 60000)
            else:
                sm = None
            j["i"].append([hexlify(b[2:5]).decode(), frm, b[5] % PHRASES, a, 0, b[6] & 1,
                           b[7] if b[7] < 16 else frm, sm])
    L.inb[:] = left
    j["i"] = j["i"][-HIN:]
    _in().keep(L)
    return True



def _pending(L, o):
    # 0 sending (the first two dials, to a ship heard just now), 1 "will deliver" (waiting
    # for them to be in range)
    if L is None:
        return 1
    x = L.nx.get(o[1])
    if not lvlive.near(L.now, L.ble.peers.get(o[1])):
        return 1
    return 1 if x is None or x[0] >= 2 else 0



def _prep(sh, maintained=False):
    # Everything GET /api/live says, read now (the pieces below are made from these alone,
    # twice, with awaits between: the same bytes both times)
    L = sh.live
    if L is not None and not maintained:
        import lvduel
        try:
            lvduel.maintain(L)
        finally:
            lvship.drop("lvduel")
            lvduel = None
    j = _hl(sh)
    if drain(sh, j):
        _in().save(sh.data + F, j)
    c = _in().load(sh.data + "/live.json") or {}
    ble = sh.ble
    pe = []
    if ble is not None:
        up = L.now if L is not None else None     # the loop's clock, as p.seen
        for k, p in ble.peers.items():
            i = p.info or {}
            # cap: 1 takes hails, 0 doesn't (an older ship), None not known yet (heard before
            # Hail started here); off: has Hail, paused (advert bit 6); nl: its hail light
            # is off (advert bit 7: a hail shows there as a note only)
            pe.append((k, max(0, lvlive.dt(up, p.seen) // 1000) if up and p.seen else None,
                       (1 if i["cap"] else 0) if "cap" in i else None, 1 if i.get("off") else 0,
                       1 if i.get("nl") else 0))
    o = j["o"][-SHOW:]
    st = [h[4] if h[4] >= 2 else _pending(L, h) for h in o]
    # why: the reason in a few fixed words (the page words it: web/live.js lvWhy); at: the
    # day it paused itself, if it did
    top = {"on": L is not None, "why": getattr(sh, "live_why", None) if L is None else None,
           "at": c.get("at") if L is None else None,
           "light": light(c), "dl": c.get("dl", True), "lv": L.v if L else 0,
           "me": sh.node.ship, "today": today(j), "no": len(j["o"]), "ni": len(j["i"]),
           "max": DAY_MAX, "lights": L.lc[1] if L and L.lc[0] == sh.clock.date() else 0,
           "cap": lvlive.LIGHTS, "quiet": _quiet(sh), "qw": list(getattr(sh.led, "q", None) or (1320, 420))}
    incoming, epoch = j["i"][-SHOW:], _ep(sh)
    # Only the phone-visible slice survives while the duel box is parsed.
    j = c = None
    if L is not None:
        # Parse the private box without the view builder's bytecode present.
        # The visible Hail slice remains immutable throughout this phase.
        j = _in().load(sh.data + "/duel.json") or {"g": [], "r": {}}
        lvship.free()
        import lvduelview
        try:
            top["duel"] = lvduelview.view(L, j)
        finally:
            lvship.drop("lvduelview")
    else:
        top["duel"] = []
    return pe, o, st, incoming, epoch, top



def light(c):
    # the hail light: its own switch (Settings, "Flicker for hails"), on unless switched off;
    # not the Ship light's (FIXREVIEW2 J5: lvflick.maybe, the same)
    v = c.get("light")
    return True if v is None else bool(v)



def today(j):
    # hails sent today: n counts each (the list keeps only HOUT); never fewer than listed
    n = j.get("n")
    return max(n if isinstance(n, int) else 0, len([h for h in j["o"] if h[4] != 4]))



def _trim(o):
    # at most HOUT sent hails: the oldest that are done go first, waiting ones stay
    while len(o) > HOUT:
        for h in o:
            if h[4] >= 2:
                o.remove(h)
                break
        else:
            del o[0]



def _quiet(sh):
    # [from, to] (minutes) while the ship's clock is in quiet hours, else None: the light
    # rests then (lvflick.maybe, the same rule) though hails still arrive
    c = sh.clock
    m = c.minute() if c.known() else None
    q = getattr(sh.led, "q", None) or (1320, 420)
    if m is None:
        return None
    return list(q) if ((m >= q[0] or m < q[1]) if q[0] > q[1] else q[0] <= m < q[1]) else None



def hail(sh, you, b):
    L = sh.live
    if L is None:
        return 409, {"err": "Ship-to-ship is off.", "why": getattr(sh, "live_why", None)}
    to = b.get("to")
    ph = b.get("ph", 0)
    if not isinstance(to, int) or isinstance(to, bool) or to == sh.node.ship or not 0 <= to < 8 \
            or not isinstance(ph, int) or not 0 <= ph < PHRASES:
        return 400, {"err": "Pick a crewmate."}
    p = sh.ble.peers.get(to) if sh.ble else None
    if p is not None and p.info and "cap" in p.info and not p.info["cap"]:
        if p.info.get("off"):
            return 409, {"err": "Their ship isn't taking hails right now."}
        return 409, {"err": "Their ship needs the update before it can be hailed."}
    j = _hl(sh)
    drain(sh, j)
    e = _ep(sh)
    if today(j) >= DAY_MAX:
        return 429, {"err": "That's today's hails: more tomorrow."}
    if len(L.out) >= 18:
        return 429, {"err": "Your out-box is full. Waiting moves stay until delivered."}
    for h in j["o"]:
        if h[4] == 4:
            continue
        if h[1] == to and h[4] < 2:
            return 429, {"err": "Your last hail is still on its way."}
        if h[1] == to and e and h[3] and 0 <= e - h[3] < A.GAP_MS:
            return 429, {"err": "You just hailed them: give it a couple of minutes.", "ms": A.GAP_MS - (e - h[3])}
    back = 0
    if b.get("back"):
        for h in j["i"]:
            if h[1] == to and e and h[3] and 0 <= e - h[3] < BACK_MS:
                back = 1
    from lvlivein import mins
    m = mins(sh.clock)
    m = 65535 if m is None else m
    ref = _in().send(L, 1, to, bytes((ph % PHRASES, back, you & 255, m >> 8, m & 255)))
    j["n"] = today(j) + 1
    j["o"].append([hexlify(ref).decode(), to, ph % PHRASES, e, 0])
    _trim(j["o"])
    _in().save(sh.data + F, j)
    sh.say("live: hail to ship %d" % (to + 1))
    return 200, {"ok": True, "id": hexlify(ref).decode()}



def seen(sh, b):
    L = sh.live
    if L is not None and len(L.out) >= 18:
        return 429, {"err": "Your out-box is full. Try again after delivery."}
    j = _hl(sh)
    drain(sh, j)
    from binascii import unhexlify
    for h in j["i"]:
        if h[0] == b.get("id") and not h[4]:
            h[4] = 1
            if L is not None:
                _in().send(L, 2, h[1], unhexlify(h[0]))
    _in().save(sh.data + F, j)
    return 200, {"ok": True}



