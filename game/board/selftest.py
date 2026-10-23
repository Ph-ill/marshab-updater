# Serial self-test for the bench. With main.py stopped (Ctrl-C in mpremote, or /data/maint):
#   mpremote exec "import selftest; selftest.run(120, gift_to=2)"
# Prints BLE state, peers seen, records exchanged, free heap, the gift path and the LED
# path, then one PASS/CHECK line per check and a SELFTEST RESULT line.
# docs/BENCH_TEST.md has the full checklist and what to send back when something fails.
import os
import sys

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship
from lv import sync as S


def run(seconds=120, gift_to=None, epoch=None, tz=0, wifi=False, led=None):
    """Serial self-test. Prints BLE state, peers, records exchanged, free heap, the gift
    path and the LED path, then a SELFTEST summary. See docs/BENCH_TEST.md."""
    cfg = lvship.load_config()
    if led is not None:
        cfg["led_notify"] = bool(led)
    print("SELFTEST lvship %s on %s, MicroPython %s" % (lvship.VERSION, sys.platform, sys.version))
    print("SELFTEST config: ship %d, day %d, story %s, hotspot %s, led_notify %s" % (
        cfg["ship_id"], cfg["day"], cfg["story"], wifi and cfg["hotspot"], cfg["led_notify"]))
    print("SELFTEST heap before start: free %d" % lvship.free())
    if wifi and cfg["hotspot"]:
        import lvwifi
        lvwifi.hotspot(cfg)
    ship = lvship.Ship(cfg)
    # Variant A (.mpy copy): code and pack from files. Variant B (game firmware): both frozen;
    # a frozen module's __file__ names no file on the filesystem.
    src = getattr(lvship, "__file__", "?")
    try:
        os.stat(src)
        where = "filesystem"
    except OSError:
        where = "frozen"
    print("SELFTEST code: %s (%s), pack: %s" % (src, where, ship.pack_src))
    if epoch:
        ship.clock.learn(epoch, tz)
    b = ship.ble
    print("SELFTEST ble: active %s, advert %s" % (b.ble.active(), S.adv_data(ship.node.advert()).hex()))
    print("SELFTEST log: %d records, digest %s, story %s" % (
        len(ship.log), ship.node.digest().hex(), ship.st.hexdigest() if ship.st else "off"))
    if gift_to:
        r = ship.gift(gift_to)
        print("SELFTEST gift out: ship %d -> ship %d, record %s" % (ship.me + 1, int(gift_to), r.hex()))
    print("SELFTEST led: notifier %s (led_notify %s), time known %s, waiting %s" % (
        "ON" if ship.led.enabled else "off", cfg["led_notify"], ship.clock.known(), ship.led.waiting))
    low = [lvship.free()]

    async def run():
        if wifi and cfg["hotspot"]:
            await asyncio.start_server(ship.http, "0.0.0.0", cfg["http_port"])
        t = 0
        while t < seconds:
            await ship.loop(stop_after_ms=10000, stat_every_ms=10 ** 9)
            t += 10
            f = lvship.free()
            if f < low[0]:
                low[0] = f
            print("SELFTEST t=%ds %s" % (t, ship.stat_line()))
    asyncio.run(run())
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
    print("SELFTEST led: notifier %s, waiting %s, pin writes %d" % (
        "ON" if ship.led.enabled else "off", ship.led.waiting, ship.led.writes))
    print("SELFTEST heap: used %d, peak %d, free now %d, lowest free %d" % (
        st["heap_used"], ship.mem_peak, st["heap_free"], low[0]))
    checks = [("ble active", b.ble.active()), ("peer heard", bool(peers)),
              ("in sync with a peer", bool(same)), ("no stuck session", b.state == "idle"),
              ("heap used < 80 KB", 0 < ship.mem_peak < 80 * 1024),
              ("led off unless asked", ship.led.enabled == bool(cfg["led_notify"]))]
    for name, ok in checks:
        print("SELFTEST %-22s %s" % (name, "PASS" if ok else "CHECK"))
    print("SELFTEST RESULT", "PASS" if all([c[1] for c in checks]) else "CHECK (see docs/BENCH_TEST.md)")
    return ship
