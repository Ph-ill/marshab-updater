# Ship-to-ship for the phone page (web/live.js): Hail, the Settings switches and the radio
# check. Loaded per request by board/main.py's ota_route and dropped after, so none of this
# stays in RAM; the resident part is lvlive.py.
#
#   GET  /api/live            the switches, crewmates heard, the newest SHOW (6) of today's
#                             hails each way (no, ni: how many there are), the light's day
#                             (lights of cap) and quiet ([from, to] min or null). Made from
#                             small pieces into one buffer of its length and written PIECE
#                             bytes at a time (live(), from main.py): never a dict of the
#                             whole list or a string built up by copies (FIXREVIEW2 B1)
#   POST /api/live/hail       {to, ph, back}   hail crewmate `to` (0-based) with phrase ph
#   POST /api/live/seen       {id}             "X saw it": tell the hailer it was seen
#   POST /api/live/set        {on, light}
#   GET  /api/coex            the radio check: Bluetooth sync and Wi-Fi side by side
#   GET  /api/coex/ping?kb=N  the radio test's probe (main.py streams it: N KB, at most
#                             PING_KB, in 512 B pieces, with the Bluetooth state then)
# Everything needs a signed-in phone (401; the radio check too since 0.3.0 review R3 m3). The
# hailer is the ship's crew member: crew N lives on ship N, so "to" is a ship as well as a
# crewmate. The page learns that something changed from "lv" in its 5 s GET /api/bat
# (main.py: the Link's version), then asks GET /api/live; /api/hello has nothing of Hail.
#
# Hails are kept in /data/hail.json for the day (at most HOUT sent, still-waiting ones
# kept first, and HIN received; n: how many were sent today):
#   o: [ref, to, phrase, epoch ms, state]  state 0 sending, 2 delivered, 3 seen, 4 didn't go
#   i: [ref, from ship, phrase, epoch ms it arrived (None: before this ship knew the time,
#       and read back after a restart), seen, back, from crew (who was signed in there),
#       epoch ms it was sent (to the minute, by its ship's clock) or None]
# Hail back is offered for BACK_MS after it arrived (not after the phone first read it).
# A hail not delivered by the end of its day expires (its item leaves lvlive's out queue:
# lvlivein.expire, on the ship's own) and stays listed as "Didn't go" through the next day;
# a receipt that comes in late still makes it Delivered (FIXREVIEW2 J4). Days only turn
# forward: a phone's clock set back a day changes nothing here (FIXREVIEW3 f2).
# Fair use: one undelivered hail per crewmate, a 2 min gap to the same crewmate, 20 a day.
import lvship
import lvlive
# lvlivein (the box file and item helpers) is imported where it's used, not here, so GET
# /api/live can let it go before its answer goes out (main.py's finally drops it as well)
from binascii import hexlify

PHRASES = 8          # web/live.js has the words; the radio carries the number
GAP_MS = 120000
DAY_MAX = 20
HOUT = 12            # kept in hail.json: sent...
HIN = 16             # ...and received
SHOW = 6             # GET /api/live: the newest this many each way
BACK_MS = 600000     # "Hail back" within 10 minutes
PING_KB = 8
PIECE = 256          # GET /api/live goes out this many bytes at a time
F = "/hail.json"

# review 3 MAJOR-1: a phone that stops taking bytes mid-stream (out of range, screen locked,
# Wi-Fi stalled) would leave drain() waiting until lwIP gives up, minutes, with main.py's
# admission holding every other phone's /api/* off. Each stream write here waits at most
# DRAIN_MS; then the stream fails (TimeoutError), lvweb.Server.handle closes the socket and
# main.py's finally clears state_busy (GET /api/live; the radio test's ping holds nothing).
# (Here, not in lvweb: lvweb is frozen in the lv-core firmware, and any change would ship
# it as a ~4 KB .mpy that stays in RAM all the time.)
DRAIN_MS = 15000


async def wdrain(w):
    import asyncio
    if hasattr(asyncio, "wait_for_ms"):
        return await asyncio.wait_for_ms(w.drain(), DRAIN_MS)
    return await asyncio.wait_for(w.drain(), DRAIN_MS / 1000)   # CPython (the tests)


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
        import lvduelview
        try:
            top["duel"] = lvduelview.view(L)
        finally:
            lvship.drop("lvduelview")
    else:
        top["duel"] = []
    return pe, o, st, incoming, epoch, top


def _probe():
    p = getattr(lvship, "heap_probe", None)
    if p:
        lvship.heap_stage = "http"
        p()


def _json(obj):
    import json
    text = json.dumps(obj)
    _probe()
    return text


def parts(pe, o, st, i, e, top):
    """GET /api/live's JSON, a few dozen bytes at a time."""
    yield '{"peers": ['
    for n, x in enumerate(pe):
        yield (", " if n else "") + _json({"s": x[0], "ago": x[1], "cap": x[2], "off": x[3], "nl": x[4]})
    yield '], "out": ['
    for n, h in enumerate(o):
        yield (", " if n else "") + _json({"id": h[0], "to": h[1], "ph": h[2], "t": h[3], "st": st[n]})
    yield '], "in": ['
    for n, h in enumerate(i):
        t = h[3]
        yield (", " if n else "") + _json({
            "id": h[0], "from": h[1], "by": h[6] if len(h) > 6 else h[1], "ph": h[2], "t": t, "seen": h[4],
            "back": 1 if h[5] else 0, "can": 1 if e and t and 0 <= e - t < BACK_MS else 0,
            "sent": h[7] if len(h) > 7 else None})
    yield '], "duel": ['
    for n, game in enumerate(top.get("duel", ())):
        yield ", " if n else ""
        if "history" not in game:
            yield _json(game)
            continue
        yield _json(dict((k, v) for k, v in game.items()
                              if k not in ("history", "even", "shots", "incoming")))[:-1]
        h = game["history"]
        for key in ("shots", "incoming"):
            yield ', "' + key + '": ['
            first = True
            for i in range(0, len(h), 2):
                shot = i // 2 + 1
                mine = (shot % 2 == 0) == game["even"]
                if mine == (key == "shots"):
                    yield ("" if first else ", ") + _json((shot, ord(h[i]) - 65, ord(h[i + 1]) - 97))
                    first = False
            yield "]"
        yield "}"
    yield "], " + _json(dict((k, v) for k, v in top.items() if k != "duel"))[1:]


def state(sh, you):
    # (the tests, and anything that wants it as one object)
    import json
    return json.loads("".join(parts(*_prep(sh))))


async def live(lvweb, web, req, w, maintained=False):
    # GET /api/live (main.py): signed in, the clock learned as api() does, then the answer
    # with a Content-Length, PIECE bytes at a time with a drain after each. The answer is
    # counted from a compact immutable snapshot, then streamed without a response-sized
    # buffer or expanded transcript lists. Both passes use the same snapshot even if
    # a radio move is durably accepted between drains.
    sh = web.ship
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    if sh.clock.learn_headers(req.header):
        sh.day_check()
    snapshot = _prep(sh, maintained)
    n = sum(len(x.encode()) for x in parts(*snapshot))
    lvship.drop("lvlivein")         # (its code: not held while the answer goes out)
    w.write(lvweb.head(200, "application/json", n))
    k = 0
    for x in parts(*snapshot):
        b = x.encode()
        _probe()
        for offset in range(0, len(b), PIECE):
            chunk = b[offset:offset + PIECE]
            w.write(chunk)
            before, k = k, k + len(chunk)
            if before < 3 * PIECE <= k and lvweb.probe:
                lvweb.probe()
            await wdrain(w)


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
        if h[1] == to and e and h[3] and 0 <= e - h[3] < GAP_MS:
            return 429, {"err": "You just hailed them: give it a couple of minutes.", "ms": GAP_MS - (e - h[3])}
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


def setting(sh, b):
    import lvlivecfg
    try:
        return lvlivecfg.setting(sh, b)
    finally:
        lvship.drop("lvlivecfg")


def coex(sh):
    import lvlivecfg
    try:
        return lvlivecfg.coex(sh)
    finally:
        lvship.drop("lvlivecfg")


async def ping(lvweb, web, req, w):
    import lvlivecfg
    try:
        return await lvlivecfg.ping(lvweb, web, req, w)
    finally:
        lvship.drop("lvlivecfg")


def api(web, req):
    """main.py routes /api/live* and /api/coex here. -> (status, obj)"""
    sh = web.ship
    p = req.path
    if p == "/api/live/duel":
        import lvduelaction
        try:
            return lvduelaction.api(web, req)
        finally:
            lvship.drop("lvduelaction")
    you = web.get_phone().who(req)
    if you is None:
        return 401, {"err": "signed out"}
    if p == "/api/coex" or p == "/api/live/coex":
        return coex(sh) if req.method == "GET" else (404, {"err": "no such thing"})
    if sh.clock.learn_headers(req.header):
        sh.day_check()
    if req.method == "GET" and p == "/api/live":
        return 200, state(sh, you)      # (main.py streams it: live())
    if req.method != "POST":
        return 404, {"err": "no such thing"}
    import json
    try:
        b = json.loads(req.body or b"{}")
        if not isinstance(b, dict):
            raise ValueError
    except ValueError:
        return 400, {"err": "bad request"}
    if p == "/api/live/hail":
        return hail(sh, you, b)
    if p == "/api/live/seen":
        return seen(sh, b)
    if p == "/api/live/set":
        return setting(sh, b)
    return 404, {"err": "no such thing"}
