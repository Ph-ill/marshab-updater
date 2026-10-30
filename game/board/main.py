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
# raw requests the way a phone's arrive, through the request parser and Server.handle
# (serves()): the page, /api/crew and /api/ota must answer 2xx, and an update write with
# no sign-in must answer 401 (lvotap's own refusal: the write side is there too; this one
# is sent even after a phone's 2xx, a whole 1 KB piece, 0.3.0 FR1 m1). If that
# keeps failing for SELF_MS, the ship restarts (a real reset, which lvboot counts), so a
# trial that lvboot gave no deadline (a soft reset, on ota-hwfix's lvboot) still ends.
# Whatever served the phone, the update path is then checked too (kept(), board/lvotak.py,
# 0.3.0): lvotaq, lvotap, lvota, lvsig and lvsafe must import, lvota.KEYS must hold the
# release key and lvsig must check a known signature, or the trial isn't kept (a set that
# can't take the next update would need USB).
# Crashes (board/lvsafe.py): whatever main() lets escape, and a failure of the web server's
# own accept loop, is noted in /data/fault.json once asyncio has let go of the game's heap,
# and the ship restarts; SAFE_AFTER in a row and the next boot is safe mode (hotspot +
# update page only, the game tried again on its own after a while). Any other task that
# fails (the light, Test light, the charger watch, the update keeper...) is said in the log
# and stops by itself; the captive DNS and the phones' saves start again after a pause
# (keep()). An unusable ship.json or crew.json is put back from its backup. After
# lvsafe.HEALTHY_MS of play the crash count is set aside (healthy(): fault.json renamed to
# fault.last.json, no import, no heap), so its notes stay readable over USB.
import gc
if hasattr(gc, "threshold"):
    # Bound uncollected churn between radio and HTTP operations. Allocation-triggered
    # collection, not probe-triggered collection, also applies on the board.
    gc.threshold(1024)
import os
import time

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import lvship


BOOT_WINDOW_MS = 2000
OTA_OK_MS = 30000
SELF_MS = 180000            # serves() failing this long after OTA_OK_MS: restart (counted)
FAULT = "/data/fault.json"
FAULT_LAST = "/data/fault.last.json"
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


def http_admission(lvweb, web, slots=8):
    # One parser/response working set, with bounded unread browser connections.
    # Startup fetches static data, icons and API state concurrently. Static loads
    # cannot replay a 503, so queue that burst outside web.busy without parsing
    # it (OTA/radio admission must not wait on these unread sockets).
    handle = getattr(web, "handle", None)
    if handle is None:
        return
    lock = asyncio.Lock()
    web.http_waiting = 0

    async def busy(w):
        web.refused += 1
        try:
            await lvweb.send(w, 503, '{"err":"busy, try again"}', extra="Retry-After: 1\r\n")
        finally:
            await web._close(w)

    async def admitted(r, w):
        if web.http_waiting >= slots:
            return await busy(w)
        web.http_waiting += 1
        acquired = False
        try:
            try:
                if hasattr(asyncio, "wait_for_ms"):
                    await asyncio.wait_for_ms(lock.acquire(), 15000)
                else:
                    await asyncio.wait_for(lock.acquire(), 15)
                acquired = True
            except asyncio.TimeoutError:
                return await busy(w)
            return await handle(r, w)
        except BaseException:
            if not acquired:
                await web._close(w)
            raise
        finally:
            if acquired:
                try:
                    if getattr(web, "radio_turn", False):
                        web.radio_turn = False
                        # The response and its modules are gone, and handle has
                        # cleared web.busy. Keep the next parser unread while
                        # the radio gets a real turn, even under continuous polls.
                        await lvship.sleep_ms(250)
                        started = lvship.ticks_ms()
                        ble = getattr(web.ship, "ble", None)
                        retry = getattr(web, "radio_retry", None)
                        link = getattr(web.ship, "live", None)
                        # A deferred trailer may need another dial after an
                        # idle gap. Wait for receive progress, not just idle;
                        # bound an absent sender so phones cannot wait forever.
                        while lvship.ticks_diff(lvship.ticks_ms(), started) < (15000 if retry is not None else 2000):
                            waiting = retry is not None and link is not None and link.n["in"] == retry
                            if not waiting and (ble is None or ble.state == "idle"):
                                break
                            await lvship.sleep_ms(25)
                        web.radio_retry = None
                        web.radio_pending = ble is not None and ble.state != "idle"
                finally:
                    lock.release()
                    web.http_waiting -= 1
            else:
                web.http_waiting -= 1

    web.handle = admitted


def ota_hooks(lvweb, web):
    net_hooks(lvweb, web)
    # Bound request-parser/socket working sets as well as API dispatch. Extra
    # phones receive the existing 503 + Retry-After before reading a request.
    # Heavy state/live streams defer item receive until their snapshot is gone.
    lvweb.MAX_CONN = 1
    http_admission(lvweb, web)
    route = web.route
    clock_gate(web)
    # Admission for the heavy answers, decided before Phone.state_writer (or lvliveapi.live)
    # allocates anything (0.3.0 review 1 R1, reworked in review 2 M2-M4). One streamed
    # /api/state at a time; no /api/state or /api/live while an update piece is being taken;
    # and no other /api/* dispatch while a state is half sent (its auth/dispatch modules must
    # not sit on the heap next to it). Those get 503 + Retry-After: 1 at once, before their
    # handler loads: web/app.html api() and web/ota.js (otaFetch, review 2 M4) replay it, so
    # the phone just sees a slightly slower answer. Refusing, not parking: a parked request
    # holds a connection (lvweb.MAX_CONN) and counts in web.busy, which an update piece
    # (lvotaq.quiet), a hail's send and the notifier all wait on, so parking stalled the
    # heap run (--ota --live --everyone) and put the board's peak over 78,000 B.
    # A light playback (Test light, a hail's flicker) holds nothing off any more (review 2
    # M2): its task keeps only lvlight's helpers and its own small play(), measured with a
    # full state in the heap runs.
    # A stalled phone (review 3 MAJOR-1): every stream write waits at most lvweb.DRAIN_MS
    # (15 s), then the request fails, its socket is closed and the finally below clears
    # state_busy. As a backstop, state_busy is the ticks_ms the stream began (0: none) and a
    # mark older than BUSY_MS is ignored, so nothing can hold every phone off for longer.
    web.state_busy = 0
    web.ota_busy = 0
    web.radio_hold = False

    def held():
        t = web.state_busy
        return t and lvship.ticks_diff(lvship.ticks_ms(), t) < 20000

    async def ota_route(req, w):
        if req.path.startswith("/api/"):
            heavy = req.method == "GET" and req.path in ("/api/state", "/api/live")
            if held() or (heavy and web.ota_busy):
                return await lvweb.send(w, 503, '{"err":"busy, try again"}', extra="Retry-After: 1\r\n")
            if heavy:
                ble = getattr(web.ship, "ble", None)
                if ble is not None and ble.state != "idle":
                    # Never prepare a snapshot inside an existing radio turn.
                    # Its proof/terminal maintenance can still need the full
                    # three-game box, even without a previously deferred trailer.
                    return await lvweb.send(w, 503, '{"err":"busy, try again"}', extra="Retry-After: 1\r\n")
                web.radio_pending = False
            if heavy:
                # Include failed preparation/imports, not only completed streams.
                web.radio_turn = True
            if heavy and req.path == "/api/state":
                web.state_busy = lvship.ticks_ms() or 1
                web.radio_hold = True
                link = getattr(web.ship, "live", None)
                deferred = link.n["held"] if link is not None else 0
                try:
                    return await route(req, w)
                finally:
                    web.radio_hold = False
                    web.state_busy = 0
                    if link is not None and link.n["held"] > deferred:
                        web.radio_retry = link.n["in"]
        if req.path == "/api/reset":
            # "Reset this ship" (board/lvcode.py reset, web/settings.js). Loaded per request,
            # like lvota (0.3.0: out of main.py's resident code).
            import lvcode
            try:
                if await lvcode.reset(lvweb, web, req, w, reboot):
                    print("reset: player progress clears in 1 s, then a restart")
                return
            finally:
                lvship.drop("lvcode")
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
            # the light play 10 s of blinks and breaths, on or off. Loaded per request.
            if req.method != "POST":
                return await lvweb.send_json(w, 404, {"err": "no such thing"})
            # Don't load a second copy of the playback module while its task owns
            # the pin (the first copy remains alive through that task's globals).
            if web.get_phone().who(req) is None:
                return await lvweb.send_json(w, 401, {"err": "signed out"})
            t = getattr(web.ship, "ledtest", None)
            if t is not None:
                left = 10000 - lvship.ticks_diff(lvship.ticks_ms(), t)
                if left > -5000:
                    # a hail's flicker owns the light (review 3 m2): the page says so
                    hail = t == getattr(web.ship, "ledhail", None)
                    return await lvweb.send_json(w, 429, {"err": "The light is showing a hail." if hail else "The light is already testing.",
                                                          "ms": max(0, left), "kind": "hail" if hail else "test"})
            import lvledtest
            try:
                s, j = lvledtest.start(web, req)
            finally:
                lvship.drop("lvledtest")
                lvship.drop("lvlight")
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
            j = {"v": sh.v, "bat": b[:3] if b else None}
            L = getattr(sh, "live", None)
            if L is not None:
                # lv: the ship-to-ship state's version (a hail or its receipt came in: the
                # page asks /api/live).
                j["lv"] = L.v
            return await lvweb.send_json(w, 200, j)
        if req.path == "/api/hello" and req.method == "GET":
            # The home-screen funnel (board/lvfunnel.py, web/funnel.js): has the ship seen
            # this phone open the game from its icon? Loaded per request, like lvota.
            import lvfunnel
            try:
                return await lvweb.send_json(w, 200, lvfunnel.api(web, req))
            finally:
                lvship.drop("lvfunnel")
        if req.path == "/api/live/duel":
            # A duel POST needs neither the Hail API nor its response encoder.
            import lvduelaction
            try:
                s, j = lvduelaction.api(web, req)
            finally:
                lvship.drop("lvduelaction")
                lvduelaction = None
                lvship.drop("lvlivein")
            return await lvweb.send_json(w, s, j)
        if req.path.startswith("/api/live") or req.path.startswith("/api/coex"):
            # Ship-to-ship (board/lvliveapi.py, web/live.js): Hail, the Settings switches, the
            # radio check and its test's probe (streamed). Loaded per request, like lvota.
            maintained = False
            snapshot = None
            if req.path == "/api/live" and req.method == "GET" and web.get_phone().who(req) is not None:
                # Apply recovery before loading the HTTP encoder: its code need not
                # coexist with the rules and the parsed three-game durable box.
                sh = web.ship
                if sh.clock.learn_headers(req.header):
                    sh.day_check()
                if sh.live is not None:
                    import lvlivein
                    try:
                        lvlivein.duel_maintain(sh.live)
                    finally:
                        lvship.drop("lvlivein")
                        lvlivein = None
                maintained = True
                # Hail persistence is synchronous: finish it before importing
                # the encoder, then keep only the immutable phone-visible slice
                # and the private duel box for the separate view-building phase.
                lvship.free()
                import lvliveops
                try:
                    snapshot = lvliveops._prep(sh, True)
                finally:
                    lvship.drop("lvliveops")
                    lvliveops = None
                    lvship.drop("lvlivein")
            # Recovery's parsed box and released rules must be reclaimed before
            # admitting the HTTP encoder, not at some later allocation failure.
            lvship.free()
            import lvliveapi
            try:
                if req.path == "/api/coex/ping":
                    return await lvliveapi.ping(lvweb, web, req, w)
                if req.path == "/api/live" and req.method == "GET":
                    web.state_busy = lvship.ticks_ms() or 1
                    # Do not overlap receive/reveal rules and a phone snapshot.
                    # Unacknowledged trailers retry after this bounded stream.
                    web.radio_hold = True
                    link = getattr(web.ship, "live", None)
                    deferred = link.n["held"] if link is not None else 0
                    try:
                        return await lvliveapi.live(lvweb, web, req, w, maintained, snapshot)
                    finally:
                        web.radio_hold = False
                        web.state_busy = 0
                        if link is not None and link.n["held"] > deferred:
                            web.radio_retry = link.n["in"]
                s, j = lvliveapi.api(web, req)
            finally:
                lvship.drop("lvliveapi")
                lvliveapi = None
                lvship.drop("lvlivein")
            return await lvweb.send_json(w, s, j)
        if req.path.startswith("/api/ota"):
            if req.method != "GET" and web.get_phone().who(req) is not None:
                # An update coming in from a signed-in phone: Hail holds its dials and takes
                # no items (lvlive.OTA_MS). Signed-out POSTs can't hold Hail off (0.3.0 R3 m2).
                web.ship.ota_t = lvship.ticks_ms() or 1
            if req.path == "/api/ota/put":
                # The upload itself (board/lvotap.py, 0.3.0): ~3 KB of code, with lvota loaded
                # only for the envelope and dropped through its signature check. It waits for
                # a quiet moment first (lvotaq.py, ~0.5 KB) before lvotap is even loaded.
                web.ota_busy += 1
                try:
                    if req.method == "POST" and web.get_phone().who(req) is not None:
                        import lvotaq
                        try:
                            # Do not occupy the single HTTP owner while a light
                            # plays: its next tap must reach the 429 check now,
                            # not start another playback after this wait ends.
                            light_busy = lvotaq.lit(web.ship, lvship)
                            if not light_busy:
                                await lvotaq.quiet(web, req.q, req.body or b"")
                        finally:
                            lvotaq = None
                            lvship.drop("lvotaq")
                        if light_busy:
                            return await lvweb.send(w, 503, '{"err":"busy, try again"}', extra="Retry-After: 1\r\n")
                    import lvotap
                    try:
                        return await lvotap.api(web, req, w, True)
                    finally:
                        lvship.drop("lvotap")
                        lvship.drop("lvota")
                finally:
                    web.ota_busy -= 1
            import lvota
            try:
                return await lvota.api(web, req, w)
            finally:
                lvship.drop("lvota")
        return await route(req, w)
    web.route = ota_route


class _Hdr:
    # (a request's header getter, as lvphone.Phone.who wants a request)
    def __init__(self, get):
        self.header = get


def clock_gate(web):
    # Every phone request carries its clock (lvweb.route). Once the ship knows the time,
    # only a signed-in phone may move it (FIXREVIEW3 f2: a stranger's phone on the hotspot
    # set a day ahead can't turn the ship's day); the first one is anyone's.
    c = getattr(getattr(web, "ship", None), "clock", None)
    learn = getattr(c, "learn_headers", None)
    if learn is None or not hasattr(c, "known"):
        return

    def learned(get):
        if c.known():
            # (the phone list made if need be: a crewmate signed in before a restart, whose
            # token is kept, before any API request made it)
            if not get("x-crew-token"):
                return False
            gp = getattr(web, "get_phone", None)
            ph = gp() if gp is not None else getattr(web, "phone", None)
            if ph is None or ph.who(_Hdr(get)) is None:
                return False
        return learn(get)
    c.learn_headers = learned


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


# serves()'s requests and the status each must get: the page, the crew list and the update
# status (2xx), and an update write with no sign-in (lvotap's 401: put, not apply or cancel,
# so a sign-in check gone wrong still can't act on anything). The put carries a whole piece
# (lvota.CHUNK, 1024 B: lvweb.MAX_BODY must take it) and is the last probe, PUT: it is sent
# even when a phone has had a 2xx already, so the upload's route, its body limit and lvotap
# itself are shown to work before a trial is kept (0.3.0 fix review FR1 m1).
PROBES = (("GET", "/", b"2"), ("GET", "/api/crew", b"2"), ("GET", "/api/ota", b"2"),
          ("POST", "/api/ota/put", b"401"))
PUT = PROBES[3:]


def Sink(req):
    import lvcheck
    try:
        return lvcheck.Sink(req)
    finally:
        lvship.drop("lvcheck")


async def serves(web, probes=PROBES):
    import lvcheck
    try:
        return await lvcheck.serves(web, probes)
    finally:
        lvship.drop("lvcheck")


async def ota_ok(web=None, want=False):
    # Keep the update: OTA_OK_MS up and (with the phone game) one 2xx answer to a phone, or
    # the ship's own check that it serves the page (serves()), every 5 s until one says so.
    # want: the phone game should be running (the hotspot is on and phone_game asks for it
    # on a firmware with a core): with no web server then (a core shadowed by an lv/
    # directory, say) the update isn't kept, since only the phone game serves /api/ota.
    # Until then lvboot's deadline (USB-only, TRIAL_MS) restarts the ship and counts the
    # boot; past SELF_MS of failing checks main.py restarts it itself (a soft-reset trial
    # on ota-hwfix's lvboot has no deadline), a real reset that lvboot counts.
    await lvship.sleep_ms(OTA_OK_MS)
    t = lvship.ticks_ms()
    while (web is None and want) or web is not None and not await serves(web, PUT if web.ok2xx else PROBES) \
            or not await kept(web):
        if lvship.ticks_diff(lvship.ticks_ms(), t) > SELF_MS:
            print("ota: the update can't show it serves a phone: restarting (a counted boot)")
            return restart()
        await lvship.sleep_ms(5000)


async def kept(web):
    # Then, whatever served it, the update path itself (board/lvotak.py, 0.3.0 review R1
    # M2: its modules import and lvsig checks a known signature) before lvota.good() keeps
    # it: a set that can't take the next update is never kept. Failing: False, tried again.
    try:
        import lvotak
        return await lvotak.keep(web, FAULT, FAULT_LAST)
    except Exception as e:
        print("ota: self-check %r" % (e,))
        return False
    finally:
        lvship.drop("lvotak")


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
    # Only the exception's words are kept, and whether its traceback ran through Hail's own
    # modules (fault.json "live": 0.3.0 review R2 M3). Then say it, note it (not on an update's trial:
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
    tb = ""
    try:
        import io
        tb = io.StringIO()
        sys.print_exception(e, tb)
        tb = tb.getvalue()
        print(tb, end="")
    except Exception:
        print("crash: %s" % why)
    e = None
    gc.collect()
    trial = flag("ota/state.json")
    try:
        import lvsafe
        # live: Hail's own code was in it (lvlivex turns Hail off for that crash only),
        # not the core's sync code going on through Hail's hooks (lvlive.CORE: FIXREVIEW2 J2)
        lvsafe.crashed(why, trial, time.ticks_diff(time.ticks_ms(), t0),
                       live=("lvlive" in tb or "lvflick" in tb or "lvduel" in tb) and not getattr(sys.modules.get("lvlive"), "CORE", 0))
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
    # lvsafe.HEALTHY_MS of play: the crash count is set aside (fault.last.json keeps its
    # notes: the last crash, what the boot check did). Inline (no import, no heap at
    # minute 10 under a busy game: review #2 M6); the backups are refreshed at each boot.
    await lvship.sleep_ms(600000)
    try:
        os.rename(FAULT, FAULT_LAST)
    except OSError:
        pass


def safe_mode(cfg, why):
    # Safe mode or "off": lvsafe.start (its code lives there, loaded only for this).
    print("safe: " + why)
    import lvsafe
    lvsafe.start(cfg, why, globals())


def wanted(cfg):
    import lvsetup
    try:
        return lvsetup.wanted(cfg)
    finally:
        lvship.drop("lvsetup")


def config(got):
    import lvsetup
    try:
        return lvsetup.config(got, lvship)
    finally:
        lvship.drop("lvsetup")


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

def no_setup(e, waited=False):
    # lvsetup.mpy (0.3.0: the boot steps moved out of main.py) damaged or missing, outside an
    # update's trial (a trial's lvboot count rolls back by itself): safe mode, the way a
    # damaged game module gets there, rather than a crash loop with no hotspot that only
    # USB could end (0.3.0 review 2 m1). Also when it imports but its boot() raises
    # (review 3 nit-4: a missing name, say), before lvsafe.check could choose safe mode.
    # Still the boot window first (waited: boot() began with it), and /data/safe.
    print("safe: no boot code %r" % (e,))
    lvship.drop("lvsetup")
    if not waited:
        time.sleep_ms(BOOT_WINDOW_MS)
    if flag("/data/safe"):
        print("safe: /data/safe found, not starting (remove it to play)")
        return
    safe_mode(lvship.load_config(), "boot code damaged (lvsetup: %s)" % type(e).__name__)


def main():
    try:
        import lvsetup
    except Exception as e:
        return no_setup(e)
    bad = None
    try:
        setup = lvsetup.boot(BOOT_WINDOW_MS, flag, safe_mode)
    except Exception as e:          # imports, but its boot() fails: as a failed import
        bad, setup = e, None
    finally:
        lvsetup = None
        lvship.drop("lvsetup")
    if bad is not None:
        return no_setup(bad, True)
    if setup is None:
        return
    if setup[0] is None:            # safe mode: lvsafe.check's reason, lvsetup dropped first
        return safe_mode(setup[1], setup[2])
    cfg, trial = setup
    try:
        import lvsetup
        ship, ap, ip, game = lvsetup.prepare(cfg)
    finally:
        lvsetup = None
        lvship.drop("lvsetup")
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
        if ship.ble is not None:
            # Ship-to-ship items (Hail: board/lvlive.py) over the sync link: on unless
            # switched off, off by itself after a fault or crash.
            try:
                import lvlive
                ship.trial = trial          # (a crash from before an update: lvlivex.install)
                lvlive.install(ship, getattr(ship, "data", "/data"))
            except Exception as e:
                # (the type only: the page shows live_why, never an exception's text)
                ship.live, ship.live_why = None, "didn't start: " + type(e).__name__
                print("live: " + ship.live_why)
                try:                        # crewmates' pages: paused, not "needs the update"
                    lvlive.pause(ship.node)
                    ship.ble.adv = None
                except Exception:
                    pass
        if trial:
            asyncio.create_task(ota_ok(web, cfg["hotspot"] and wanted(cfg)))
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
