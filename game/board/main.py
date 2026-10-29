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
# has to keep that call. An update is kept only once the game has run OTA_OK_MS AND served
# a phone at least one 2xx answer (ota_ok, ok2xx), so a set that starts but can't serve the
# page goes back too (lvboot's deadline restarts it until MAX_BOOTS, then rolls back).
# A trial's update can also be kept without a phone: once OTA_OK_MS has passed, the ship
# checks its hotspot is up and its web server is still listening, then hands its own server
# three raw requests (the page, /api/crew and /api/ota) the way a phone's arrive, through
# the request parser and Server.handle (serves()); three 2xx do.
# Crashes (board/lvsafe.py): whatever main() lets escape, and a failure of the web server's
# own accept loop, is noted in /data/fault.json once asyncio has let go of the game's heap,
# and the ship restarts; SAFE_AFTER in a row and the next boot is safe mode (hotspot +
# update page only, the game tried again on its own after a while). Any other task that
# fails (the light, Test light, the charger watch, the update keeper...) is said in the log
# and stops by itself; the captive DNS and the phones' saves start again after a pause
# (keep()). An unusable ship.json or crew.json is put back from its backup. After
# lvsafe.HEALTHY_MS of play the crash count goes (healthy(): no import, no heap).
import gc
import os
import time

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship


BOOT_WINDOW_MS = 2000
OTA_OK_MS = 30000
FAULT = "/data/fault.json"
reboot = None               # tests: called instead of machine.reset()
MAIN = []                   # the game's own task (run()): cancelled to stop the game
FATAL = []                  # tasks whose failure stops the game: the web server's accept loop
CRASH = []                  # what stopped it (noted after asyncio.run has returned)


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
    net_hooks(lvweb, web)
    route = web.route

    async def ota_route(req, w):
        if req.path == "/api/reset":
            return await reset_ship(lvweb, web, req, w)
        if req.path.startswith("/ls/"):
            # iOS launch screens, www/ls/<W>x<H>.png (web/launch.py), as they are (a PNG
            # doesn't gzip). A prefix rather than seven STATIC entries: no RAM until asked.
            n = req.path[4:]
            d = n[:-4].split("x")
            if req.method == "GET" and n[-4:] == ".png" and len(d) == 2 and d[0].isdigit() and d[1].isdigit():
                return await lvweb.send_file(w, web.root + "www/ls/" + n, "image/png", False)
        if req.path == "/api/code":
            # "Change your code" (board/lvcode.py, web/settings.js): a signed-in crew member
            # sets a new sign-in code in data/crew.json. Loaded per request, like lvota.
            if req.method != "POST":
                return await lvweb.send_json(w, 404, {"err": "no such thing"})
            import lvcode
            try:
                s, j = lvcode.change(web.get_phone(), req)
            finally:
                lvship.drop("lvcode")
            return await lvweb.send_json(w, s, j)
        if req.path == "/api/led/test":
            # "Test light" (board/lvledtest.py, web/settings.js): a signed-in crew member makes
            # the light play ~4 s of blinks and a breath, on or off. Loaded per request.
            if req.method != "POST":
                return await lvweb.send_json(w, 404, {"err": "no such thing"})
            import lvledtest
            try:
                s, j = lvledtest.start(web, req)
            finally:
                lvship.drop("lvledtest")
            return await lvweb.send_json(w, s, j)
        if req.path == "/api/bat" and req.method == "GET":
            # The page's poll every 5 s while it's showing (web/app.html startPoll): the
            # state's version, as /api/v, and the battery, [percent, mV, charging] or null
            # (lvbatt.py, web/batt.js). One small answer: no story, nothing to sign.
            # Like every phone request in lvweb.route, it carries the phone's clock: learn it,
            # so the flight day turns at 06:00 and v says so.
            sh = web.ship
            if sh.clock.learn_headers(req.header):
                sh.day_check()
            b = sh.bat
            return await lvweb.send_json(w, 200, {"v": sh.v, "bat": b[:3] if b else None})
        if req.path == "/api/hello" and req.method == "GET":
            # The home-screen funnel (board/lvfunnel.py, web/funnel.js): has the ship seen
            # this phone open the game from its icon? Loaded per request, like lvota.
            import lvfunnel
            try:
                return await lvweb.send_json(w, 200, lvfunnel.api(web, req))
            finally:
                lvship.drop("lvfunnel")
        if req.path.startswith("/api/ota"):
            import lvota
            try:
                return await lvota.api(web, req, w)
            finally:
                lvship.drop("lvota")
        return await route(req, w)
    web.route = ota_route


def net_hooks(lvweb, web):
    # For the game and for safe mode: update pieces (lvota.CHUNK) fit a request; the
    # 2xx answers are counted (ota_ok keeps an update only once a phone got one); GitHub
    # is left unanswered by the captive DNS.
    lvweb.MAX_BODY = 1024
    web.ok2xx = 0
    head = getattr(lvweb, "head", None)     # (the tests' stand-ins may have none)

    def counted(code, *a, **k):
        if 200 <= code < 300:
            web.ok2xx += 1
        return head(code, *a, **k)
    if head:
        lvweb.head = counted
    answer = lvweb.dns_answer

    def dns_answer(q, ip):
        # REFUSED for GitHub (where phones fetch updates), so no phone caches this board
        # as github.com; every other name is still the board (the captive portal).
        r = answer(q, ip)
        if r and (b"\x06github\x03com\x00" in q or b"\x11githubusercontent\x03com\x00" in q):
            return r[:2] + b"\x81\x85\x00\x01\x00\x00\x00\x00\x00\x00" + r[12:len(r) - 16 * r[7]]
        return r
    lvweb.dns_answer = dns_answer


# "Reset this ship" (the page's Settings): the players' progress goes, the ship's setup stays.
# Deleted from /data: log.bin (every record this ship holds: taps, votes, gifts; other ships
# in range sync theirs back), days.bin (the days told), clock.json (the saved flight day and
# time; the launch date in ship.json brings the day back once a phone tells the time),
# local.bin (what phones opened and saw), and funnel.bin (the phones the home-screen funnel
# has seen, and which opened the game from the icon: board/lvfunnel.py). Sign-ins and
# sessions live in RAM, so the restart forgets them.
# fault.json (board/lvsafe.py: the crash count) goes too: a reset ship starts with a clean count.
# Kept: ship.json (identity, hotspot password, ota_src, the Ship light), crew.json (the crew
# codes, including any changed in Settings: board/lvcode.py), their backups ship.json.bak and
# crew.json.bak (lvsafe), the installed software and ota/ (the update state and rollback
# copy), maint/safe.
RESET = ("log.bin", "days.bin", "clock.json", "local.bin", "funnel.bin", "fault.json")


async def reset_ship(lvweb, web, req, w):
    # POST /api/reset {confirm: this ship's number} with a signed-in X-Crew-Token, else
    # 401/403 and nothing changes. 200, then the files go and the board restarts.
    if req.method != "POST":
        return await lvweb.send_json(w, 404, {"err": "no such thing"})
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    sh = web.ship
    try:
        import json
        ok = int(json.loads(req.body or b"{}")["confirm"]) == sh.cfg["ship_id"]
    except Exception:
        ok = False
    if not ok:
        return await lvweb.send_json(w, 403, {"err": "Type this ship's number to confirm."})
    await lvweb.send_json(w, 200, {"ok": True, "restart_ms": 1500})

    async def later():
        await asyncio.sleep(1)
        # No await from here on: nothing can write a file back before the restart.
        import os
        for f in RESET:
            try:
                os.remove(sh.data + "/" + f)
            except OSError:
                pass
        print("reset: player progress cleared, restarting")
        if reboot:
            return reboot()
        import machine
        machine.reset()
    asyncio.create_task(later())


class Sink:
    # serves()'s stand-in for a phone's connection, both ends: reads out the raw request
    # it was given (as a socket's stream would), keeps the answer's status line, drops the rest.
    def __init__(self, req):
        self.b = req
        self.st = None

    async def readline(self):
        i = self.b.find(b"\n") + 1 or len(self.b)
        r, self.b = self.b[:i], self.b[i:]
        return r

    async def readexactly(self, n):
        r, self.b = self.b[:n], self.b[n:]
        return r

    def write(self, d):
        if self.st is None:
            self.st = bytes(d[:12])

    async def drain(self):
        pass

    def get_extra_info(self, k):
        return ("127.0.0.1", 0)

    def close(self):
        pass

    async def wait_closed(self):
        pass


async def serves(web):
    """Does this set serve a phone? The hotspot is up as this ship's own SSID, the web
    server's accept loop is still running, and GET /, /api/crew and /api/ota, as raw bytes
    through Server.handle (lvweb's request parser, the busy count, route, head), each get a
    2xx. The counts a phone's visit moves (the 2xx count, served, the ship's hits) are left
    as they were. (A real socket round trip would be stronger; lwIP loopback on the Pico W
    is unconfirmed, so the listening socket is shown by its accept task instead.)"""
    sh = web.ship
    ap = getattr(web, "ap", None)
    if ap is not None:
        try:
            c = sh.cfg
            if not ap.active() or ap.config("essid") != "%s%d" % (c["ssid_prefix"], c["ship_id"]):
                print("ota: self-check: the hotspot isn't up")
                return False
        except Exception as e:
            print("ota: self-check hotspot %r" % (e,))
            return False
    t = getattr(getattr(web, "srv", None), "task", None)
    if t is not None and t.done():
        print("ota: self-check: the web server stopped")
        return False
    n, s, h = web.ok2xx, web.served, sh.http_hits
    try:
        for p in ("/", "/api/crew", "/api/ota"):
            w = Sink(("GET %s HTTP/1.0\r\nHost: self\r\n\r\n" % p).encode())
            await web.handle(w, w)
            if not (w.st and w.st[9:10] == b"2"):
                print("ota: %s answered %r" % (p, w.st))
                return False
        return True
    except Exception as e:
        print("ota: self-check %r" % (e,))
        return False
    finally:
        web.ok2xx, web.served, sh.http_hits = n, s, h


async def ota_ok(web=None):
    # Keep the update: OTA_OK_MS up and (with the phone game) one 2xx answer to a phone, or
    # the ship's own check that it serves the page (serves()), every 5 s until one says so.
    # Until then lvboot's deadline (USB-only, TRIAL_MS) restarts the ship and counts the boot.
    await lvship.sleep_ms(OTA_OK_MS)
    while web is not None and not web.ok2xx and not await serves(web):
        await lvship.sleep_ms(5000)
    import lvota
    if lvota.good():
        print("ota: update kept")
        try:
            os.remove(FAULT)                    # the new set starts with a clean count
        except OSError:
            pass
    lvship.drop("lvota")


def restart():
    if reboot:
        return reboot()
    import machine
    machine.reset()


def note(trial):
    # lvsafe couldn't note the crash (no heap to load it?): the count, in a few bytes. The
    # other keys (tries: safe mode's next wait; up) are kept. At the cap (lvsafe.SAFE_CAP)
    # nothing is written: a boot loop must not wear the flash.
    if trial:
        return
    try:
        import json
        j = {}
        try:
            with open(FAULT) as f:
                j = json.load(f)
            n = int(j["n"])
        except Exception:
            n = 0
        if not isinstance(j, dict):
            j = {}
        if n >= 5:
            return
        j["n"], j["why"] = n + 1, "noted the short way"
        with open(FAULT + ".new", "w") as f:
            f.write(json.dumps(j))
        os.rename(FAULT + ".new", FAULT)
    except Exception as e:
        print("crash: not noted %r" % (e,))


# Modules that hold the game once it has run (lvweb.head is net_hooks' counter, whose
# closure holds the server, and through it the ship; lvphone and the rest hang off them).
GAME = ("lvweb", "lvphone", "lvdays", "lvfunnel", "lvota", "lvled", "lvledcfg", "lvstat", "lvwifi")


def crashed(e, t0):
    # What stopped the game: let go of everything it had, so the note below has the heap
    # (review #2 M2): MAIN (run()'s finished task, whose coroutine holds run's closure:
    # ship, web, days, ap, cfg), FATAL (the accept loop's task, holding web.handle), CRASH,
    # the modules that hold the server, and the event loop's queues (a new event loop).
    # Only the exception's words are kept. Then say it, note it (not on an update's trial:
    # lvboot's boot count decides that one; read now, an update may have been kept since
    # boot), restart. Never raises.
    try:
        why = "%s: %s" % (type(e).__name__, str(e)[:40])
    except Exception:
        why = "?"
    del MAIN[:], FATAL[:], CRASH[:]
    try:
        import sys
        for m in GAME:
            sys.modules.pop(m, None)
        asyncio.new_event_loop()
    except Exception:
        pass
    gc.collect()
    try:
        sys.print_exception(e)
    except Exception:
        print("crash: %s" % why)
    e = None
    gc.collect()
    trial = flag("ota/state.json")
    try:
        import lvsafe
        lvsafe.crashed(why, trial, time.ticks_diff(time.ticks_ms(), t0))
    except Exception as e2:
        print("crash: noting %r" % (e2,))
        note(trial)
    print("crash: restarting")
    restart()


def task_error(loop, ctx):
    # asyncio's handler for a task that failed with nobody awaiting it. MicroPython hands
    # the same ctx dict every time: read it now. The web server's accept loop stops the game
    # (crashed(), through run()'s task); anything else is said and left stopped.
    e = ctx.get("exception")
    f = ctx.get("future")
    if f is not None and f in FATAL and MAIN:
        CRASH.append(e)
        MAIN[0].cancel()
    else:
        print("task stopped: %r" % (e,))


async def keep(name, make):
    # A task the ship can do without for a while (the captive DNS, the phones' saves): if
    # it stops with an error, say so and start it again after a pause, 5 s up to 5 min
    # (back to 5 s once a run has lasted a minute: a fault hours later isn't the same one).
    pause = 5000
    while True:
        t = lvship.ticks_ms()
        try:
            return await make()
        except Exception as e:
            if lvship.ticks_diff(lvship.ticks_ms(), t) > 60000:
                pause = 5000
            print("%s: stopped (%r), again in %d s" % (name, e, pause // 1000))
        await lvship.sleep_ms(pause)
        pause = min(pause * 2, 300000)


async def healthy():
    # lvsafe.HEALTHY_MS of play: the crash count goes. Inline (no import, no heap at
    # minute 10 under a busy game: review #2 M6); the backups are refreshed at each boot.
    await lvship.sleep_ms(600000)
    try:
        os.remove(FAULT)
    except OSError:
        pass


def safe_mode(cfg, why):
    # Safe mode or "off": lvsafe.start (its code lives there, loaded only for this).
    print("safe: " + why)
    import lvsafe
    lvsafe.start(cfg, why, globals())


def config(got):
    # cfg from the ship.json lvsafe.check() has just read and checked (got), not a second
    # read (a one-off read error there would give DEFAULTS: a fake ship 1, review #2 m1).
    # got None (lvsafe itself unusable): lvship.load_config() reads it, as 0.2.6 did.
    if got is None:
        return lvship.load_config()
    c = dict(lvship.DEFAULTS)
    if got:
        c.update(got[0])
    try:
        c["ship_id"] = min(8, max(1, int(c["ship_id"])))
    except (TypeError, ValueError):
        c["ship_id"] = 1
    return c


# ---- the charger line, watched (docs/BATTERY.md "Charging shows at once"). lvbatt reads the
# gauge and the charger pin once a minute (I2C, loaded and dropped); this only reads the pin,
# every CHG_EVERY_MS, and takes a new level once it has held CHG_STEADY_MS (a plug wiggling
# in its socket doesn't flicker the bolt). On a flip: ship.bat[2] at once, and the gauge
# read CHG_GAUGE_MS later (lvship's loop does it when bat[7] ms have passed since bat[6]),
# so the percent and voltage follow without reading the gauge any more often otherwise.
CHG_EVERY_MS = 100
CHG_STEADY_MS = 300
CHG_GAUGE_MS = 2000


class Debounce:
    def __init__(self, v):
        self.v = v              # the level taken
        self.new = None         # a different level seen, since self.t
        self.t = 0

    def step(self, v, now):
        """One look at the pin (v) at ticks_ms now. True when the taken level changes."""
        if v == self.v or v is None:
            self.new = None
            return False
        if v != self.new:
            self.new, self.t = v, now
            return False
        if lvship.ticks_diff(now, self.t) >= CHG_STEADY_MS:
            self.v, self.new = v, None
            return True
        return False


def charger(ship):
    """The charger reader: () -> True/False, or None when there's no pin (bat_chg -1/null).
    Tests set ship.bat_hw (lvbatt's fakes); on the board, one Pin set up as lvbatt does."""
    h = getattr(ship, "bat_hw", None)
    if h:
        return h[1]
    c = ship.cfg
    p = c.get("bat_chg", 6)
    if p is None or p < 0:
        return None
    from machine import Pin
    u = c.get("bat_chg_pull", "none")   # as lvbatt: R2 pulls it low (PAD1)
    pin = Pin(p, Pin.IN, Pin.PULL_DOWN if u == "down" else Pin.PULL_UP if u == "up" else None)
    return lambda: bool(pin.value())


async def charger_watch(ship, rd=None, every=CHG_EVERY_MS, stop=None):
    rd = rd or charger(ship)
    if ship.bat is None or rd is None:
        return
    d = Debounce(ship.bat[2])
    while not (stop and stop()):
        await lvship.sleep_ms(every)
        b = ship.bat
        if b is None:
            return
        if d.new is None:
            d.v = b[2]          # lvbatt's own reading may have moved it
        try:
            v = rd()
        except Exception:
            continue
        if d.step(v, lvship.ticks_ms()):
            b[2] = v
            b[6], b[7] = lvship.ticks_ms(), CHG_GAUGE_MS

def main():
    print("boot: The Long Voyage starts in %d s (Ctrl-C or any mpremote command stops it)" % (
        BOOT_WINDOW_MS // 1000))
    time.sleep_ms(BOOT_WINDOW_MS)
    if flag("/data/safe"):
        print("safe: /data/safe found, not starting (remove it to play)")
        return
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
    trial = flag("ota/state.json")
    got = []
    try:
        import lvsafe
        why = lvsafe.check(trial, got=got)
    except Exception as e:  # lvsafe itself unusable (a damaged lvsafe.mpy): play as 0.2.6 did,
        print("safe: no boot check %r" % (e,))    # rather than crash-loop with no hotspot
        why, got = None, None
    lvship.drop("lvsafe")
    lvship.drop("lvledcfg")                    # (lvsafe asked it whether ship.json is whole)
    cfg = config(got)
    if why:
        return safe_mode(cfg, why)
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
    web = None

    async def run():
        nonlocal web
        MAIN[:] = [asyncio.current_task()]
        asyncio.get_event_loop().set_exception_handler(task_error)
        if game:
            import lvweb
            web = lvweb.Server(ship, ip=ip)
            web.ap = ap                 # board/lvfunnel.py: MAC mode, where the firmware lists leases
            home_screen(lvweb)
            ota_hooks(lvweb, web)
            srv = web.srv = await asyncio.start_server(web.handle, "0.0.0.0", cfg["http_port"])
            if getattr(srv, "task", None):
                FATAL.append(srv.task)
            asyncio.create_task(keep("tick", web.tick))
            if cfg["captive_dns"]:
                asyncio.create_task(keep("dns", lambda: lvweb.dns(ip)))
            print("web: phone game on http://%s/ (status: /status)" % ip)
        elif cfg["hotspot"]:
            import lvstat
            await asyncio.start_server(lvstat.server(ship), "0.0.0.0", cfg["http_port"])
            print("web: status only on http://%s/ (the phone game needs the game firmware)" % ip)
        if trial:
            asyncio.create_task(ota_ok(web))
        asyncio.create_task(healthy())
        if ship.bat:
            asyncio.create_task(charger_watch(ship))
        await ship.loop()
    asyncio.run(run())


T0 = time.ticks_ms()
try:
    main()
except KeyboardInterrupt:
    print("stopped (Ctrl-C)")
except BaseException as e:      # (a cancelled run() is a CancelledError: CRASH says why)
    crashed(CRASH[0] if CRASH else e, T0)
