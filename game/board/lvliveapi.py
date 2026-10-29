# Ship-to-ship for the phone page (web/live.js): Hail, the Settings switches and the radio
# check. Loaded per request by board/main.py's ota_route and dropped after, so none of this
# stays in RAM; the resident part is lvlive.py.
#
#   GET  /api/live            the switches, crewmates heard, today's hails both ways, the
#                             light's day (lights of cap) and quiet ([from, to] min or null)
#   POST /api/live/hail       {to, ph, back}   hail crewmate `to` (0-based) with phrase ph
#   POST /api/live/seen       {id}             "X saw it": tell the hailer it was seen
#   POST /api/live/set        {on, light}
#   GET  /api/coex            the radio check: Bluetooth sync and Wi-Fi side by side
#   GET  /api/coex/ping?kb=N  the radio test's probe (main.py streams it: N KB, at most
#                             PING_KB, in 512 B pieces, with the Bluetooth state then)
# Everything but GET /api/coex needs a signed-in phone (401). The hailer is the ship's crew
# member: crew N lives on ship N, so "to" is a ship as well as a crewmate.
#
# Hails are kept in /data/hail.json for the day (at most HMAX each way):
#   o: [ref, to, phrase, epoch ms, state]  state 0 sending, 2 delivered, 3 seen, 4 didn't go
#   i: [ref, from ship, phrase, epoch ms it arrived, seen, back, from crew (who was signed
#       in there), epoch ms it was sent (to the minute, by its ship's clock) or None]
# Hail back is offered for BACK_MS after it arrived (not after the phone first read it).
# A hail not delivered by the end of its day expires (its item leaves lvlive's out queue:
# lvlivein.expire, on the ship's own) and stays listed as "Didn't go" through the next day.
# Fair use: one undelivered hail per crewmate, a 2 min gap to the same crewmate, 20 a day.
import lvship
import lvlive
from lvlivein import load, save, keep, send   # (dropped with this module: api's finally)
from binascii import hexlify

PHRASES = 8          # web/live.js has the words; the radio carries the number
GAP_MS = 120000
DAY_MAX = 20
HMAX = 30
BACK_MS = 600000     # "Hail back" within 10 minutes
PING_KB = 8
F = "/hail.json"


def _ep(sh):
    e = sh.clock.epoch_ms() if sh.clock.known() else None
    return int(e) if e is not None else None


def _hl(sh):
    j = load(sh.data + F) or {}
    if j.get("d") != sh.clock.date():
        # A new day: undelivered hails expire (lvlivein.expire takes them out of the queue)
        # and are listed as "Didn't go" for one more day; the rest start again.
        L = sh.live
        if L is not None:
            import lvlivein
            lvlivein.expire(L)
        g = [o[:4] + [4] for o in j.get("o", ()) if o[4] < 2]
        j = {"d": sh.clock.date(), "o": g, "i": []}
    return j


def drain(sh, j):
    """Move what lvlive took off the air into hail.json."""
    L = sh.live
    if L is None or not L.inb:
        return False
    now = _ep(sh)
    for frm, b, t, up in L.inb:
        k = b[0]
        if t is None and now and up is not None:
            t = now - max(0, L.now - up)        # came before the clock was known: from uptime
        r = b[5:8]
        if k == 0 or k == 2:
            for o in j["o"]:
                if o[1] == frm and o[0] == hexlify(r).decode():
                    o[4] = max(o[4], 2 if k == 0 else 3)
        elif k == 1:
            # sent: the sender's clock to the minute (body bytes 3-4, lvlivein.mins), as
            # epoch ms near the arrival time; None if it didn't say
            sm, a = b[8] << 8 | b[9], t or now
            if a and sm and sm != 65535:
                a0 = a // 60000
                sm = (a0 - ((a0 - sm) & 65535)) * 60000
            else:
                sm = None
            j["i"].append([hexlify(b[2:5]).decode(), frm, b[5] % PHRASES, a, 0, b[6] & 1,
                           b[7] if b[7] < 16 else frm, sm])
    del L.inb[:]
    j["i"] = j["i"][-HMAX:]
    keep(L)
    return True


def _pending(L, o):
    # 0 sending (the first two dials, to a ship heard just now), 1 "will deliver" (waiting
    # for them to be in range)
    if L is None:
        return 1
    x = L.nx.get(o[1])
    p = L.ble.peers.get(o[1])
    if p is None or not p.seen or L.now - p.seen >= lvlive.NEAR:
        return 1
    return 1 if x is None or x[0] >= 2 else 0


def state(sh, you):
    L = sh.live
    j = _hl(sh)
    if drain(sh, j):
        save(sh.data + F, j)
    c = load(sh.data + "/live.json") or {}
    ble = sh.ble
    peers = []
    if ble is not None:
        up = L.now if L is not None else None     # the loop's clock, as p.seen
        for k, p in ble.peers.items():
            i = p.info or {}
            # cap: 1 takes hails, 0 doesn't (an older ship), None not known yet (heard before
            # Hail started here); off: has Hail, paused (advert bit 6)
            peers.append({"s": k, "ago": max(0, (up - p.seen) // 1000) if up and p.seen else None,
                          "cap": (1 if i["cap"] else 0) if "cap" in i else None, "off": 1 if i.get("off") else 0})
    e = _ep(sh)
    o = []
    for h in j["o"]:
        st = h[4] if h[4] >= 2 else _pending(L, h)
        o.append({"id": h[0], "to": h[1], "ph": h[2], "t": h[3], "st": st})
    i = [{"id": h[0], "from": h[1], "by": h[6] if len(h) > 6 else h[1], "ph": h[2], "t": h[3], "seen": h[4],
          "back": 1 if h[5] else 0, "can": 1 if e and h[3] and e - h[3] < BACK_MS else 0,
          "sent": h[7] if len(h) > 7 else None} for h in j["i"]]
    r = {"on": L is not None, "why": getattr(sh, "live_why", None) if L is None else None,
         "light": light(sh, c), "lv": L.v if L else 0,
         "me": sh.node.ship, "peers": peers, "out": o, "in": i, "today": today(j),
         "max": DAY_MAX, "lights": L.lc[1] if L and L.lc[0] == sh.clock.date() else 0,
         "cap": lvlive.LIGHTS, "quiet": _quiet(sh), "qw": list(getattr(sh.led, "q", None) or (1320, 420))}
    return r


def light(sh, c):
    # the hail light: as set in Settings, else as the Ship light is (lvflick.maybe, the same)
    v = c.get("light")
    return bool(getattr(sh.led, "enabled", False)) if v is None else v


def today(j):
    return len([h for h in j["o"] if h[4] != 4])     # (yesterday's "didn't go" don't count)


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
    for h in j["o"]:
        if h[4] == 4:
            continue
        if h[1] == to and h[4] < 2:
            return 429, {"err": "Your last hail is still on its way."}
        if h[1] == to and e and h[3] and e - h[3] < GAP_MS:
            return 429, {"err": "You just hailed them: give it a couple of minutes.", "ms": GAP_MS - (e - h[3])}
    back = 0
    if b.get("back"):
        for h in j["i"]:
            if h[1] == to and e and h[3] and e - h[3] < BACK_MS:
                back = 1
    from lvlivein import mins
    m = mins(sh.clock)
    m = 65535 if m is None else m
    ref = send(L, 1, to, bytes((ph % PHRASES, back, you & 255, m >> 8, m & 255)))
    j["o"].append([hexlify(ref).decode(), to, ph % PHRASES, e, 0])
    j["o"] = j["o"][-HMAX:]
    save(sh.data + F, j)
    sh.say("live: hail to ship %d" % (to + 1))
    return 200, {"ok": True, "id": hexlify(ref).decode()}


def seen(sh, b):
    L = sh.live
    j = _hl(sh)
    drain(sh, j)
    from binascii import unhexlify
    for h in j["i"]:
        if h[0] == b.get("id") and not h[4]:
            h[4] = 1
            if L is not None:
                send(L, 2, h[1], unhexlify(h[0]))
    save(sh.data + F, j)
    return 200, {"ok": True}


def setting(sh, b):
    cf = sh.data + "/live.json"
    c = load(cf) or {}
    for k in ("light",):
        if k in b:
            c[k] = bool(b[k])
    L = sh.live
    if "on" in b:
        on = bool(b["on"])
        c["on"] = on
        if on:
            c.pop("why", None)
            import lvlivex
            try:
                fx = lvlivex.crash(sh.data)     # the crash it was off for: not again for it
            finally:
                lvship.drop("lvlivex")
            if fx is not None:
                c["fx"] = fx
            else:
                c.pop("fx", None)
        else:
            c["why"] = "turned off"
    save(cf, c)
    if L is not None:
        L.cfg = c
        if not c.get("on", True):
            lvlive.unhook(L)
            sh.live = None
            sh.live_why = "turned off"
            sh.say("live: turned off from a phone")
    elif c.get("on", True) and sh.ble is not None:
        lvlive.install(sh, sh.data)
        sh.say("live: turned on from a phone" if sh.live else "live: still off (%s)" % getattr(sh, "live_why", None))
    return 200, {"ok": True, "on": sh.live is not None, "why": getattr(sh, "live_why", None), "light": light(sh, c)}


def coex(sh):
    # The radio check (Settings > Ship-to-ship > Radio check): what the ship's one radio
    # has done for Bluetooth and Wi-Fi since it started. No names, codes or keys.
    b = sh.ble
    L = sh.live
    r = {"ble": None, "live": None, "web": None, "heap": lvship.free(), "up": sh.clock.uptime() // 1000}
    if b is not None:
        n = b.n
        r["ble"] = {"state": b.state, "heard": len(b.peers), "ok": n["ok"], "fail": n["fail"],
                    "out": n["out"], "in": n["in"], "refused": n["refused"], "last": b.last[:60]}
    if L is not None:
        r["live"] = dict(L.n)
        r["live"]["waiting"] = len(L.out)
    w = sh.web
    if w is not None:
        r["web"] = {"served": w.served, "refused": w.refused, "busy": w.busy}
    return 200, r


async def ping(lvweb, web, req, w):
    # The radio test's probe (web/live.js coexTest): kb KB of spaces, written 512 B at a time
    # with a drain after each, as an update's download to the phone would be, and what the
    # Bluetooth side was doing as it started (X-Ble) so the page can tell which answers ran
    # alongside a link. Signed-in phones only; nothing kept.
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    try:
        kb = min(PING_KB, max(0, int(req.q.get("kb", "0"))))
    except ValueError:
        kb = 0
    b = web.ship.ble
    st = b.state if b is not None else "off"
    w.write(lvweb.head(200, "text/plain", kb * 1024, extra="X-Ble: %s\r\n" % st))
    if kb:
        z = b" " * 512
        for _ in range(2 * kb):
            w.write(z)
            await w.drain()
    else:
        await w.drain()


def api(web, req):
    """main.py routes /api/live* and /api/coex here. -> (status, obj)"""
    sh = web.ship
    p = req.path
    if p == "/api/coex" or p == "/api/live/coex":
        return coex(sh) if req.method == "GET" else (404, {"err": "no such thing"})
    you = web.get_phone().who(req)
    if you is None:
        return 401, {"err": "signed out"}
    if sh.clock.learn_headers(req.header):
        sh.day_check()
    if req.method == "GET" and p == "/api/live":
        return 200, state(sh, you)
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
