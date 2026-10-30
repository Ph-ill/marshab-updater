# Ship-to-ship for the phone page (web/live.js): Hail, the Settings switches and the radio
# check. Loaded per request by board/main.py's ota_route and dropped after, so none of this
# stays in RAM; the resident part is lvlive.py.
#
#   GET  /api/live            the switches, crewmates heard, the newest SHOW (6) of today's
#                             hails each way (no, ni: how many there are), the light's day
#                             (lights of cap) and quiet ([from, to] min or null). Made from
#                             small pieces and written at most PIECE bytes at a time
#                             (live(), from main.py): never a dict of the
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


from lvlive import PHRASES, DAY_MAX, HOUT, HIN, SHOW, BACK_MS, F
GAP_MS = 120000
PING_KB = 8
PIECE = 256          # GET /api/live goes out this many bytes at a time

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
    lvship.free()
    import lvlivein
    return lvlivein


def light(c):
    v = c.get("light")
    return True if v is None else bool(v)


def _call(name, *args):
    import lvliveops
    try:
        return getattr(lvliveops, name)(*args)
    finally:
        lvship.drop("lvliveops")


def _ep(sh):
    return _call("_ep", sh)


def _hl(sh):
    return _call("_hl", sh)


def _prep(sh, maintained=False):
    return _view(sh, _call("_prep", sh, maintained))


def _view(sh, snapshot):
    if isinstance(snapshot[-1].get("duel"), dict):
        # Hail preparation has returned and dropped its operation module. Reclaim
        # it before the view builder allocates beside the private parsed duel box.
        lvship.free()
        import lvduelview
        try:
            top = snapshot[-1]
            top["duel"] = lvduelview.view(sh.live, top["duel"])
        finally:
            lvship.drop("lvduelview")
    return snapshot


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


async def live(lvweb, web, req, w, maintained=False, snapshot=None):
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
    snapshot = _prep(sh, maintained) if snapshot is None else _view(sh, snapshot)
    # Snapshot construction has returned; its parsed files and operation code
    # must not survive into the two encoding passes or a concurrent radio save.
    lvship.free()
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


def hail(sh, you, b):
    return _call("hail", sh, you, b)


def seen(sh, b):
    return _call("seen", sh, b)


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
