# Serial self-test for the bench. With main.py stopped (Ctrl-C in mpremote, or /data/maint):
#   mpremote exec "import selftest; selftest.run(120, gift_to=2)"
# Prints BLE state, peers seen, records exchanged, free heap, the gift path and the LED
# path, then one PASS/CHECK line per check and a SELFTEST RESULT line.
#   wifi=True       also the hotspot, the phone server (or the status page on stock
#                   MicroPython) and the captive DNS, as main.py runs them
#   epoch=ms, tz=m  the time, as a phone would bring it (the flight day, the LED's quiet hours)
#   led=True/False  the LED notifier on/off for this run; led_test=True plays 3 slow breaths
#                   (the LED fades up and down 3 times, about 7 s) to watch for (lvled.py)
# docs/BENCH_TEST.md has the full checklist and what to send back when something fails;
# tools/bench.py runs all of it with one command and reads these lines.
import os
import sys

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship
from lv import sync as S


def _exists(f):
    try:
        os.stat(f)
        return True
    except OSError:
        return False


def _where(mod):
    f = getattr(mod, "__file__", "")
    return ("file " + f) if f and _exists(f) else "frozen"


def run(seconds=120, gift_to=None, epoch=None, tz=0, wifi=False, led=None, led_test=False,
        data="/data", dns_port=53):
    """Serial self-test. Prints BLE state, peers, records exchanged, free heap, the gift
    path and the LED path, then a SELFTEST summary. See docs/BENCH_TEST.md."""
    cfg = lvship.load_config(data + "/ship.json")
    if led is not None:
        cfg["led_notify"] = bool(led)
    print("SELFTEST lvship %s on %s, MicroPython %s" % (lvship.VERSION, sys.platform, sys.version))
    print("SELFTEST config: ship %d, day %d, story %s, hotspot %s, led_notify %s" % (
        cfg["ship_id"], cfg["day"], cfg["story"], wifi and cfg["hotspot"], cfg["led_notify"]))
    print("SELFTEST heap before start: free %d" % lvship.free())
    ip = "192.168.4.1"
    ap_ok = None
    if wifi and cfg["hotspot"]:
        import lvwifi
        ap = lvwifi.hotspot(cfg)
        try:
            a = ap.ifconfig()[0]
            if a and a != "0.0.0.0":
                ip = a
            ap_ok = bool(ap.active())
        except Exception as e:
            print("SELFTEST wifi: %r" % (e,))
            ap_ok = False
        print("SELFTEST wifi: hotspot %s%d active %s, ip %s" % (cfg["ssid_prefix"], cfg["ship_id"], ap_ok, ip))
    game = wifi and cfg["hotspot"] and lvship.phone_game(cfg)
    days = None
    if game:
        import lvdays
        days = lvdays.Days(data + "/days.bin")
    ship = lvship.Ship(cfg, data=data, days=days)
    # Game firmware: the core lv/ is frozen (lvfrozen.py says which), the glue and content
    # are files; /lvx/ can override frozen modules. Stock MicroPython: everything is files.
    import lv
    print("SELFTEST firmware: " + lv.describe())
    src = getattr(lvship, "__file__", "?")
    try:
        os.stat(src)
        where = "filesystem"
    except OSError:
        where = "frozen"
    print("SELFTEST code: %s (%s), engine %s, pack: %s" % (src, where, _where(lv.engine), ship.pack_src))
    missing = [f for f in ("www/app.html.gz", "www/text.json.gz", "www/engage.json.gz", "engage.bin")
               if not _exists(f)]
    print("SELFTEST phone game: %s, files %s" % (
        "on" if lvship.phone_game(cfg) else "off (needs the game firmware, or phone_game in ship.json)",
        "all there" if not missing else "MISSING " + ", ".join(missing)))
    if epoch:
        ship.clock.learn(epoch, tz)
        ship.day_check()
    print("SELFTEST day: flight day %d (%s), launch date %s, time known %s" % (
        ship.day, ship.status()["day_src"], cfg.get("launch_date") or "none (manual day)", ship.clock.known()))
    b = ship.ble
    print("SELFTEST ble: active %s, advert %s" % (b.ble.active(), S.adv_data(ship.node.advert()).hex()))
    print("SELFTEST log: %d records, digest %s, story %s" % (
        len(ship.log), ship.node.digest().hex(), ship.st.hexdigest() if ship.st else "off"))
    if gift_to:
        r = ship.gift(gift_to)
        print("SELFTEST gift out: ship %d -> ship %d, record %s" % (ship.me + 1, int(gift_to), r.hex()))
    if led_test and ship.led_on(True):
        ship._led("test")
        print("SELFTEST led test: watch the board's LED now: 3 slow breaths (fades up and down, 2 s each)")
    elif led_test:
        print("SELFTEST led test: skipped, the notifier needs the game firmware")
    print("SELFTEST led: notifier %s (led_notify %s), time known %s, waiting %s" % (
        "ON" if ship.led.enabled else "off", cfg["led_notify"], ship.clock.known(), ship.led.waiting))
    low = [lvship.free()]
    srv = [None, None]          # [phone/status server ok, dns: None running, True bound, or the error]
    stop = [False]

    def bound(msg):
        srv[1] = True

    async def dns():
        import lvweb
        try:
            await lvweb.dns(ip, dns_port, say=bound, stop=lambda: stop[0])
        except Exception as e:
            srv[1] = repr(e)

    async def run():
        server = None
        try:
            if game:
                import lvweb
                web = lvweb.Server(ship, ip=ip)
                server = await asyncio.start_server(web.handle, "0.0.0.0", cfg["http_port"])
                if cfg["captive_dns"]:
                    asyncio.create_task(dns())
                srv[0] = "phone game"
            elif wifi and cfg["hotspot"]:
                import lvstat
                server = await asyncio.start_server(lvstat.server(ship), "0.0.0.0", cfg["http_port"])
                srv[0] = "status page only (stock MicroPython)"
        except Exception as e:
            srv[0] = False
            print("SELFTEST server: %r" % (e,))
        if srv[0]:
            print("SELFTEST server: %s listening on port %d" % (srv[0], cfg["http_port"]))
        t = 0
        while t < seconds:
            await ship.loop(stop_after_ms=10000, stat_every_ms=10 ** 9)
            t += 10
            f = lvship.free()
            if f < low[0]:
                low[0] = f
            print("SELFTEST t=%ds %s" % (t, ship.stat_line()))
        stop[0] = True
        if server is not None:
            server.close()
            await server.wait_closed()
        await asyncio.sleep_ms(100)
    asyncio.run(run())
    if game and cfg["captive_dns"]:
        print("SELFTEST dns: %s" % ("every name -> %s on port %d" % (ip, dns_port) if srv[1] is True
                                    else "NOT listening %s" % (srv[1],)))
    st = ship.status()
    n = st["ble"]["n"]
    peers = st["ble"]["peers"]
    same = [p["ship"] for p in peers if p["same"]]
    print("SELFTEST peers seen: %s" % (", ".join(["ship %d (%s, %s records, ok %d, fails %d%s)" % (
        p["ship"], "same log" if p["same"] else "different log", p["n"], p["ok"], p["fails"],
        ", " + p["why"] if p["why"] else "") for p in peers]) or "none"))
    print("SELFTEST records: sent %d, received %d, new %d; sessions ok %d, failed %d, retries %d" % (
        n["sent"], n["got"], n["new"], n["ok"], n["fail"], n["retries"]))
    print("SELFTEST gifts in: %s" % (", ".join(["from ship %d item %d day %d" % (g[0] + 1, g[1], g[2])
                                                for g in ship.gifts_in]) or "none"))
    print("SELFTEST led: notifier %s, waiting %s, pin writes %d, now %s, write cost %d us%s" % (
        "ON" if ship.led.enabled else "off", ship.led.waiting, ship.led.writes, st["led"]["why"],
        getattr(ship.led, "wus", 0), ", plain blinks (slow radio)" if getattr(ship.led, "wus", 0) > 2000 else ""))
    print("SELFTEST day: flight day %d (%s) at the end" % (ship.day, st["day_src"]))
    print("SELFTEST heap: used %d, peak %d, free now %d, lowest free %d" % (
        st["heap_used"], ship.mem_peak, st["heap_free"], low[0]))
    checks = [("ble active", b.ble.active()), ("peer heard", bool(peers)),
              ("in sync with a peer", bool(same)), ("no stuck session", b.state == "idle"),
              ("heap used < 80 KB", 0 < ship.mem_peak < 80 * 1024),
              ("led off unless asked", ship.led.enabled == bool(cfg["led_notify"]) or led_test)]
    if wifi and cfg["hotspot"]:
        checks.append(("wifi hotspot up", bool(ap_ok)))
        checks.append(("server listening", bool(srv[0])))
        if game and cfg["captive_dns"]:
            checks.append(("dns listening", srv[1] is True))
    if led_test:
        checks.append(("led test played", ship.led.writes >= 6))
    for name, ok in checks:
        print("SELFTEST %-22s %s" % (name, "PASS" if ok else "CHECK"))
    print("SELFTEST RESULT", "PASS" if all([c[1] for c in checks]) else "CHECK (see docs/BENCH_TEST.md)")
    return ship
