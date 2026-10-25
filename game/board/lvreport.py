# The ship's status (lvship.Ship.status: the bench's /status, the selftest) and its STAT
# line (once a minute on the serial console). Loaded for a moment and dropped (like
# lvledcfg), so its code isn't on the heap while the ship runs; lvship keeps two small
# methods that call it. The heap figures are taken before it loads: the ship's own.
from lvship import VERSION, free


def status(ship, u):
    """u: the heap in use (lvship.used()) measured before this module was loaded."""
    now = ship.clock.uptime()
    if u > ship.mem_peak:
        ship.mem_peak = u
    s = {"ship": ship.me + 1, "version": VERSION, "day": ship.day, "records": len(ship.log),
         "digest": ship.node.digest().hex(), "story": ship.st.hexdigest() if ship.st else None,
         "replays": ship.replays, "gifts_in": len(ship.gifts_in), "gifts_out": ship.gifts_out,
         "led": {"enabled": ship.led.enabled, "waiting": ship.led.waiting, "writes": ship.led.writes,
                 "time_known": ship.clock.known(),
                 "why": getattr(ship.led, "state", "off")},
         "heap_used": u, "heap_free": free(), "heap_peak": ship.mem_peak, "http": ship.http_hits,
         "v": ship.v, "day_src": ship.cal.src if ship.cal else "manual"}
    s["ble"] = ship.ble.status(now) if ship.ble else None
    return s


def stat_line(ship, u):
    s = status(ship, u)
    b = s["ble"] or {"state": "off", "peers": [], "n": {}}
    n = b["n"]
    peers = " ".join(["%d%s" % (p["ship"], "=" if p["same"] else "*") for p in b["peers"]]) or "-"
    return ("STAT ship=%d recs=%d digest=%s ble=%s peers=%s ok=%s fail=%s sent=%s got=%s new=%s "
            "gifts_in=%d led=%s/%d heap_used=%d heap_free=%d day=%d/%s" % (
                s["ship"], s["records"], s["digest"], b["state"], peers, n.get("ok"), n.get("fail"),
                n.get("sent"), n.get("got"), n.get("new"), s["gifts_in"],
                s["led"]["why"], ship.led.writes, s["heap_used"], s["heap_free"], ship.day, s["day_src"]))
