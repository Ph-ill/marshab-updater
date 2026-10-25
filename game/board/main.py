# Boot: hotspot first, then the ship (BLE sync + story), the web server (the phone game,
# lvweb.py + lvphone.py) and the captive-portal DNS.
# Ways to keep the game from starting (the board is sealed in its case: no BOOTSEL):
#   * the first 2 s after power-up: any mpremote command (it sends Ctrl-C) stops main.py
#     here, before the radio is touched, and leaves the REPL:
#       mpremote connect /dev/ttyACM0 exec "print('stopped')"     (or: mpremote repl)
#   * /data/maint (an empty file): skip the game once (bench.py uses it), then it's removed
#   * /data/safe (an empty file): skip the game on every boot until it is removed
# Ctrl-C works later too (any point in the Python code); the window is for a board whose
# game would otherwise lock up straight away.
import os
import time

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship


BOOT_WINDOW_MS = 2000


def flag(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def main():
    print("boot: The Long Voyage starts in %d s (Ctrl-C or any mpremote command stops it)" % (
        BOOT_WINDOW_MS // 1000))
    time.sleep_ms(BOOT_WINDOW_MS)
    if flag("/data/safe"):
        print("safe: /data/safe found, not starting (remove it to play)")
        return
    cfg = lvship.load_config()
    try:
        os.stat("/data/maint")
        os.remove("/data/maint")
        print("maint: /data/maint found, not starting (once)")
        return
    except OSError:
        pass
    try:
        os.mkdir("/data")
    except OSError:
        pass
    try:
        import lv
        print("firmware: " + lv.describe())
    except Exception as e:
        print("firmware: %r" % (e,))
    print("lvship %s ship %d, free heap %d" % (lvship.VERSION, cfg["ship_id"], lvship.free()))
    ip = "192.168.4.1"
    if cfg["hotspot"]:
        import lvwifi
        ap = lvwifi.hotspot(cfg)
        try:
            a = ap.ifconfig()[0]
            if a and a != "0.0.0.0":
                ip = a
        except Exception:
            pass
    game = cfg["hotspot"] and lvship.phone_game(cfg)
    days = None
    if game:
        import lvdays
        days = lvdays.Days("/data/days.bin")
    ship = lvship.Ship(cfg, days=days)

    async def run():
        if game:
            import lvweb
            web = lvweb.Server(ship, ip=ip)
            await asyncio.start_server(web.handle, "0.0.0.0", cfg["http_port"])
            asyncio.create_task(web.tick())
            if cfg["captive_dns"]:
                asyncio.create_task(lvweb.dns(ip))
            print("web: phone game on http://%s/ (status: /status)" % ip)
        elif cfg["hotspot"]:
            import lvstat
            await asyncio.start_server(lvstat.server(ship), "0.0.0.0", cfg["http_port"])
            print("web: status only on http://%s/ (the phone game needs the game firmware)" % ip)
        await ship.loop()
    asyncio.run(run())


main()
