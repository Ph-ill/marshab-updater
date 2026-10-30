# Settings and diagnostic operations, not needed beside a streamed live view.
import lvship
import lvlive
from lvliveapi import _in, light, PING_KB, wdrain


def api(web, req):
    """Non-stream live requests, kept out of the response encoder's working set."""
    from lvliveapi import state, hail, seen
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


def setting(sh, b):
    cf = sh.data + "/live.json"
    c = _in().load(cf) or {}
    for k in ("light", "dl"):
        if k in b:
            c[k] = bool(b[k])
    L = sh.live
    if L is not None and "light" in b and sh.ble is not None:
        sh.ble.adv = None           # the advert again: its no-hail-light bit (lvlive.advert)
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
    _in().save(cf, c)
    if L is not None:
        L.cfg = c
        if "dl" in b:
            import lvduel
            try:
                lvduel.lighting(L)
            finally:
                lvship.drop("lvduel")
        if not c.get("on", True):
            lvlive.unhook(L)
            sh.live = None
            sh.live_why = "turned off"
            sh.say("live: turned off from a phone")
    elif c.get("on", True) and sh.ble is not None:
        lvlive.install(sh, sh.data)
        sh.say("live: turned on from a phone" if sh.live else "live: still off (%s)" % getattr(sh, "live_why", None))
    return 200, {"ok": True, "on": sh.live is not None, "why": getattr(sh, "live_why", None), "light": light(c), "dl": c.get("dl", True)}


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
            await wdrain(w)
    else:
        await wdrain(w)
