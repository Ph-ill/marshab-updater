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
# Over-the-air updates (lvota.py, lvboot.py): /api/ota* goes to lvota, loaded per request;
# the captive DNS leaves GitHub's names unanswered so a phone with another route can still
# fetch an update; and after an update this file reports in (lvota.good()) once the game
# has run OTA_OK_MS, or boot.py's deadline rolls the update back. Every release's main.py
# has to keep that call.
import os
import time

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship


BOOT_WINDOW_MS = 2000
OTA_OK_MS = 30000


def flag(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def home_screen(lvweb):
    # The phone's home-screen manifest and icon (web/build.py, web/a2hs.js), streamed from
    # flash like the page. Added here rather than in lvweb.STATIC so the frozen core stays
    # as it is (lvweb would otherwise ship again as a RAM-loaded .mpy). iOS also asks for
    # /apple-touch-icon*.png by name.
    i = ("www/icon.png.gz", "image/png")
    lvweb.STATIC.update({"/app.webmanifest": ("www/app.webmanifest.gz", "application/manifest+json"),
                         "/icon.png": i, "/apple-touch-icon.png": i, "/apple-touch-icon-precomposed.png": i})


def ota_hooks(lvweb, web):
    lvweb.MAX_BODY = 1024                       # update pieces (lvota.CHUNK)
    route = web.route

    async def ota_route(req, w):
        if req.path.startswith("/api/ota"):
            import lvota
            try:
                return await lvota.api(web, req, w)
            finally:
                lvship.drop("lvota")
        return await route(req, w)
    web.route = ota_route
    answer = lvweb.dns_answer

    def dns_answer(q, ip):
        # REFUSED for GitHub (where phones fetch updates), so no phone caches this board
        # as github.com; every other name is still the board (the captive portal).
        r = answer(q, ip)
        if r and (b"\x06github\x03com\x00" in q or b"\x11githubusercontent\x03com\x00" in q):
            return r[:2] + b"\x81\x85\x00\x01\x00\x00\x00\x00\x00\x00" + r[12:len(r) - 16 * r[7]]
        return r
    lvweb.dns_answer = dns_answer


async def ota_ok():
    await lvship.sleep_ms(OTA_OK_MS)
    import lvota
    if lvota.good():
        print("ota: update kept")
    lvship.drop("lvota")


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
            home_screen(lvweb)
            ota_hooks(lvweb, web)
            await asyncio.start_server(web.handle, "0.0.0.0", cfg["http_port"])
            asyncio.create_task(web.tick())
            if cfg["captive_dns"]:
                asyncio.create_task(lvweb.dns(ip))
            print("web: phone game on http://%s/ (status: /status)" % ip)
        elif cfg["hotspot"]:
            import lvstat
            await asyncio.start_server(lvstat.server(ship), "0.0.0.0", cfg["http_port"])
            print("web: status only on http://%s/ (the phone game needs the game firmware)" % ip)
        if flag("ota/state.json"):
            asyncio.create_task(ota_ok())
        await ship.loop()
    asyncio.run(run())


main()
