# Safe mode and the ship's fault notes (board/main.py). Loaded at boot (check()), when
# something crashes (crashed()) and for safe mode itself (start()); dropped after the boot
# check (lvship.drop), so a ship that is fine never carries it. HEALTHY_MS is main.py's own
# timer: it sets fault.json aside with no import (no heap needed at minute 10). Shipped over
# the air as lvsafe.mpy: boot.py and lvboot.py (the rollback of an update on trial) are
# USB-only and stay exactly as they are.
#
# Files, all in /data and each written whole (temp file, read back, rename: save()), so a
# power cut mid-write leaves the old copy or the new one, never half of either:
#   fault.json      {"n": crashes in a row, "why": the last one ("Class: text", short),
#                   "up": ms it ran, "tries": times safe mode tried the game again on its own}
#                   n goes up by one for each crash main.py catches (the game, or a task it
#                   can't do without), and the file is set aside (fault.last.json) once the
#                   game has run HEALTHY_MS, so the count starts again from nothing.
#                   "boot": the last thing the boot check had to do or report: a file put
#                   back, a ship.json that plays but isn't whole, or why it stayed off.
#                   Written only when it changes (an "off" ship looks again every OFF_MS
#                   and says the same thing: no new write).
#   fault.last.json fault.json as it was when the game had run HEALTHY_MS or an update was
#                   kept (main.py renames it: no import, no heap), so a note survives.
#   ship.json.bak   the last /data/ship.json that was a whole identity (lvledcfg.valid),
#   crew.json.bak   and the last crew.json that lv/codes.py would load (crew_ok). Refreshed
#                   at every boot, only when its content differs (compared as objects: a
#                   MicroPython dict's key order isn't the file's, so text never matches),
#                   and by Change your code (lvcode) the moment a code changes, so an old
#                   code never comes back from it.
#                   (Not again at HEALTHY_MS: the writes in between are whole and checked.)
# What a boot does (check()), in this order:
#   * ship.json plays whenever it has a usable ship number (ship_use: 1-8, as an int, a
#     whole float or digits), exactly as 0.2.6 would play it: a missing, empty or odd
#     hotspot password falls back to lvwifi's own rule (the placeholder), as before.
#     Being a whole identity (lvledcfg.valid: the number plus no password or one of 8-63
#     characters) only decides whether it may be written (the Ship light) and become the
#     .bak; one that plays but isn't whole is noted ("boot") and never backed up.
#   * ship.json and crew.json, when usable (or once put back): any leftover .new/.old (a
#     write cut short, which its caller never confirmed; 0.2.6's crew.json route) and any
#     .bak.new (a backup cut short) is removed, so it can't come back later ahead of the
#     fresher .bak.
#   * one that is missing, won't parse, or (ship.json) has no usable ship number is put back
#     from the first usable one of .new (a write that got as far as its read-back), .bak
#     (the last good one this ship booted with), .old. .new and .old are renamed into
#     place (nothing is rewritten, so a failed restore can't destroy them); .bak is copied
#     through its own temp file (ship.json.bak.new), never through ship.json.new.
#   * a read error that isn't "no such file" (an I/O error that stays: littlefs gives a
#     damaged block the same error on every read; no heap) is looked at again after a
#     pause, then put back the same way (the .bak is at most this boot's changes behind).
#   * a ship.json that can't be put back: on a board never set up (no crew.json in any
#     form, no ship.json.bak/.new/.old), play as 0.2.6 did (the bench's defaults). On a
#     ship that was set up: "off". That is only a ship with no usable ship number at all
#     (missing, broken, unreadable, or 0.2.6's toggle damage {"led_notify": ...}) and
#     nothing to put back: the defaults would open the public placeholder hotspot as a
#     fake ship 1, which 0.2.6 itself would do on such a file. "off" puts nothing on the
#     air, says why in fault.json "boot", and restarts after OFF_MS, so a passing error
#     passes. On an update's trial lvboot's deadline restarts it sooner and rolls the update
#     back to the old software, which plays that same file as a fake ship 1 (it has no
#     off rule): such a ship needs its identity written again over USB (the updater), and
#     fault.json "boot" says so.
#   * an update on trial (ota/state.json): play as normal. A crash then just restarts, so
#     lvboot counts the boot and rolls the update back after MAX_BOOTS (its own rule); the
#     crash isn't counted here, so the version it goes back to doesn't start in safe mode.
#   * n >= SAFE_CAP (safe mode itself kept stopping): "off" for OFF_MS, then safe mode once more.
#   * n >= SAFE_AFTER: safe mode: the ship's own hotspot and the update page only (the phone
#     page, sign-in, Settings > Ship software, /api/ota*, /status). No Bluetooth, no story.
#     It tries the game again on its own after RETRY_MS[tries] (30 min, 2 h, 6 h, then every
#     12 h), or at once from "Try the game again"; an installed update leaves it too.
import json
import os

SAFE_AFTER = 2
SAFE_CAP = SAFE_AFTER + 3
HEALTHY_MS = 600000
OFF_MS = 900000
RETRY_MS = (1800000, 7200000, 21600000, 43200000)
D = "/data"
MISSING, BROKEN, UNKNOWN = "missing", "broken", "unknown"
fail = None             # tests: called at "write", "read", "rename", "open", "restore" to simulate a failure


def _hit(where):
    if fail:
        fail(where)


def exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def save(path, text, tmp=None):
    """Write text to path whole: tmp (path.new), read back, rename over path. True, or
    False (path as it was). Rename onto an existing file is one step on littlefs and POSIX."""
    tmp = tmp or path + ".new"
    try:
        _hit("write")
        with open(tmp, "w") as f:
            f.write(text)
        _hit("read")
        with open(tmp) as f:
            if f.read() != text:
                raise OSError("read back wrong")
        _hit("rename")
        os.rename(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def read(path):
    """The JSON object in path, else MISSING (no such file), BROKEN (there, but not a JSON
    object) or UNKNOWN (couldn't be read: an I/O error or no heap, twice, a gc between)."""
    import gc
    for _ in range(2):
        try:
            _hit("open")
            with open(path) as f:
                j = json.load(f)
            return j if isinstance(j, dict) else BROKEN
        except OSError as e:
            if e.args and e.args[0] == 2:       # ENOENT
                return MISSING
        except MemoryError:
            pass
        except Exception:                       # ValueError and kin: the text isn't JSON
            return BROKEN
        gc.collect()
    return UNKNOWN


def load(path):
    """A JSON object from path, or None (missing, unreadable, or not an object)."""
    j = read(path)
    return j if isinstance(j, dict) else None


def ship_ok(c):
    """A whole identity (lvledcfg.valid): may be written and become ship.json.bak."""
    from lvledcfg import valid
    return valid(c)


def ship_use(c):
    """Does ship.json say which ship this is? A ship_id 1-8: an int, a float with nothing
    after the point (1.0) or a string of digits, what lvship.load_config's int() turns
    into that same number. Anything else (missing, 0, 9, "x", true, 2.5) would play as the
    default ship 1 or a clamped ship 8: another ship's name on the air."""
    i = c.get("ship_id")
    if isinstance(i, bool):
        return False
    try:
        if isinstance(i, float):
            if i != int(i):
                return False
        elif not (isinstance(i, int) or isinstance(i, str) and i.isdigit()):
            return False
        return 1 <= int(i) <= 8
    except (ValueError, OverflowError):
        return False


def crew_ok(c):
    """A crew.json lv/codes.py load() signs in from as it is: a hex salt of 8+ bytes and a
    list of codes (missing: none), of which the first 8 (the crew; any more are ignored,
    fewer mean the rest have none) are each None or a 64-character digest. A broken salt or
    digest and codes.load gives nobody a code, so that one never becomes the .bak. One with
    every code cleared does: clearing a code must not bring it back."""
    s, k = c.get("salt"), c.get("codes")
    if k is None:
        k = []
    if not (isinstance(s, str) and len(s) >= 16 and isinstance(k, list)):
        return False
    try:
        from binascii import unhexlify
        unhexlify(s)
    except Exception:
        return False
    for x in k[:8]:
        if not (x is None or isinstance(x, str) and len(x) == 64):
            return False
    return True


def backup(p, c):
    """p.bak := c (already checked good), only when it differs. Compared as objects: dict
    equality ignores key order (MicroPython's json.dumps order isn't the file's)."""
    return load(p + ".bak") == c or save(p + ".bak", json.dumps(c))


def gone(p):
    try:
        os.remove(p)
    except OSError:
        pass


def crewed(d):
    """Was this /data ever set up for a crew? Files a restore of ship.json never deletes:
    crew.json (the updater and the bench write it with ship.json), its backup and leftovers."""
    for x in ("", ".bak", ".new", ".old"):
        if exists(d + "/crew.json" + x):
            return True
    return False


def guard(p, ok, say=print, got=None, bench=True, keep=None, notes=None):
    """Keep p usable: -> None, or why it can't be (start nothing). See the top of the file.
    ok: usable (plays, may be put back). keep: whole (may become the .bak; default ok).
    got: a list the usable object (or a bench board's own settings) is appended to, so the
    caller never reads the file a second time. bench: a p that can't be put back may play
    on a board never set up (no crew.json in any form, no backups of p). notes: a list
    that gets what was done or seen (for fault.json "boot")."""
    keep = keep or ok
    notes = [] if notes is None else notes
    name = p[p.rfind("/") + 1:]
    j = read(p)
    if j == UNKNOWN:
        import gc
        import time
        gc.collect()
        time.sleep_ms(200) if hasattr(time, "sleep_ms") else time.sleep(0.2)
        j = read(p)
    if isinstance(j, dict) and ok(j):
        for x in (".new", ".old", ".bak.new"):
            if exists(p + x):
                gone(p + x)
                say("safe: a leftover %s%s removed" % (name, x))
        if not keep(j):
            m = "%s plays as it is, but isn't whole (no backup made)" % name
            say("safe: " + m)
            notes.append(m)
        elif not backup(p, j):
            say("safe: %s.bak not written" % name)
        if got is not None:
            got.append(j)
        return None
    how = "missing" if j == MISSING else "unreadable" if j == UNKNOWN else "not usable"
    traces = False
    for x in (".new", ".bak", ".old"):
        c = load(p + x)
        traces = traces or exists(p + x)
        if c is None or not ok(c):
            continue
        try:
            if x == ".bak":
                if not save(p, json.dumps(c), p + ".bak.new"):
                    continue
            else:
                _hit("restore")
                os.rename(p + x, p)
        except OSError:
            continue
        m = "%s %s, put back from %s%s" % (name, how, name, x)
        say("safe: " + m)
        notes.append(m)
        for y in (".new", ".old", ".bak.new"):  # the others: older, or cut short
            gone(p + y)
        if keep(c):
            backup(p, c)
        if got is not None:
            got.append(c)
        return None
    if bench and not traces and not crewed(p[:p.rfind("/")]):
        if got is not None and isinstance(j, dict):
            got.append(j)
        return None             # as 0.2.6: a bench board's own settings, or the defaults
    return "off: %s %s and nothing to put back (the updater over USB); looking again in %d min" % (
        name, how, OFF_MS // 60000)


def mark(d, note):
    """fault.json "boot" := note (what the boot check did, or why it is off), only when it
    differs, the other keys kept. Never raises: the boot goes on either way."""
    try:
        j = faults(d)
        if j.get("boot") != note:
            j["boot"] = note
            save(d + "/fault.json", json.dumps(j))
    except Exception:
        pass


def faults(d=D):
    """fault.json's {n, why, up, tries}, {} if there's none (or it's unreadable)."""
    return load(d + "/fault.json") or {}


def count(j):
    try:
        return int(j.get("n", 0))
    except (TypeError, ValueError):
        return 0


def check(trial, d=D, say=print, got=None):
    """-> None (play), "safe: <why>" (safe mode) or "off: <why>" (start nothing). got: a
    list that receives ship.json's settings as checked (main.py builds cfg from them)."""
    notes = []
    w = guard(d + "/ship.json", ship_use, say, got, keep=ship_ok, notes=notes)
    guard(d + "/crew.json", crew_ok, say, bench=False, notes=notes)  # never "off": safe mode signs in from it
    if w:
        notes.append(w)
    if notes:
        mark(d, "; ".join(notes)[:200])
    if w:
        return w
    if trial:
        return None
    j = faults(d)
    n = count(j)
    if n >= SAFE_CAP:
        return "off: safe mode stopped %d times in a row" % (n - SAFE_AFTER)
    if n >= SAFE_AFTER:
        why = str(j.get("why", "?"))
        return "safe: %d crashes in a row (%s)" % (n, why[:why.find(":")] if ":" in why else why[:24])
    return None


def crashed(why, trial, up=0, d=D):
    """main.py caught a crash: count it (not on an update's trial) before the restart. Past
    SAFE_CAP nothing more is written (a loop of them would only wear the flash)."""
    if trial:
        return
    j = faults(d)
    n = count(j) + 1
    if n > SAFE_CAP:
        return
    j["n"], j["why"], j["up"] = n, str(why)[:64], up
    t = json.dumps(j)
    if not save(d + "/fault.json", t):
        save(d + "/fault.json", t)      # (save() has removed its .new: one more go)


def retry(d=D, auto=False, n=SAFE_AFTER - 1):
    """Safe mode's Try the game again (one more go: the next crash brings safe mode back),
    by hand or on its own (auto: the next wait is longer). rest(): safe mode once more."""
    j = faults(d)
    j["n"], j["why"] = n, "tried again" if n < SAFE_AFTER else j.get("why", "?")
    j["tries"] = int(j.get("tries", 0)) + (1 if auto else 0)
    save(d + "/fault.json", json.dumps(j))


def rest(d=D):
    retry(d, n=SAFE_AFTER)


def retry_ms(d=D):
    try:
        return RETRY_MS[min(int(faults(d).get("tries", 0)), len(RETRY_MS) - 1)]
    except (TypeError, ValueError):
        return RETRY_MS[0]


async def auto_retry(sh, ms, reboot=None):
    """Safe mode tries the game again on its own after ms (RETRY_MS: longer each time)."""
    from lv.clock import ticks_ms
    import asyncio
    sh.retry = (ticks_ms(), ms)
    await asyncio.sleep_ms(ms) if hasattr(asyncio, "sleep_ms") else await asyncio.sleep(ms / 1000)
    retry(sh.data, True)
    print("safe: trying the game again (on its own)")
    if reboot:
        return reboot()
    import machine
    machine.reset()


def start(cfg, why, m):
    """main.py's safe mode (moved here from main.py so its code isn't resident while the
    game plays). m: main.py's globals (time, restart, reboot, home_screen, net_hooks, keep).
    Hotspot + the phone page, sign-in and Settings > Ship software (server()), and the game
    tried again on its own after retry_ms(). "off": nothing on the air for OFF_MS, then a
    restart (after safe mode itself kept stopping: safe mode once more), so a ship that is
    off looks again rather than staying dark for good."""
    if why.startswith("off:"):
        m["time"].sleep_ms(OFF_MS)
        if count(faults()) >= SAFE_CAP:
            rest()
        return m["restart"]()
    import lvwifi
    import lvweb
    import asyncio
    ap = lvwifi.hotspot(cfg)
    ip = "192.168.4.1"
    try:
        a = ap.ifconfig()[0]
        if a and a != "0.0.0.0":
            ip = a
    except Exception:
        pass

    async def run():
        web, sh = server(lvweb, cfg, why[6:], ip, m["reboot"])
        m["home_screen"](lvweb)
        m["net_hooks"](lvweb, web)
        await asyncio.start_server(web.handle, "0.0.0.0", cfg["http_port"])
        if cfg["captive_dns"]:
            asyncio.create_task(m["keep"]("dns", lambda: lvweb.dns(ip)))
        print("safe: update page on http://%s/" % ip)
        await auto_retry(sh, retry_ms(), m["reboot"])
    asyncio.run(run())


# ---- the safe-mode server: the phone page, sign-in and the update, nothing else ---------
class Ship:
    # What lvweb.Server and lvota need of a ship. why: what anyone on the hotspot may see
    # ("2 crashes in a row (MemoryError)": the count and the kind); detail: the last crash's
    # own words (fault.json "why"), for a signed-in crew member only.
    def __init__(self, cfg, why, data=D, say=print):
        from lv.clock import Clock
        self.cfg = cfg
        self.why = why
        self.detail = str(faults(data).get("why", ""))
        self.data = data
        self.say = say
        self.clock = Clock()
        self.http_hits = 0
        self.v = 0
        self.web = None
        self.retry = None       # (ticks_ms when set, ms): auto_retry's wait

    def retry_s(self):
        if not self.retry:
            return None
        from lv.clock import ticks_ms, ticks_diff
        return max(0, self.retry[1] - ticks_diff(ticks_ms(), self.retry[0])) // 1000


class Phone:
    # Sign-in from crew.json (lv/codes.py, as lvphone, which also remembers a phone for the
    # day so a reload stays signed in: /api/me) and a 503 {safe} for the story.
    def __init__(self, ship):
        from lv import codes as K
        self.K = K
        self.ship = ship
        self.data = ship.data
        self.book = K.load(ship.data + "/crew.json")
        self.tokens = []

    def who(self, req):
        t = req.header("x-crew-token")
        for k, c in self.tokens:
            if t and k == t:
                return c
        return None

    def token(self, c):
        for k, x in self.tokens:
            if x == c:
                return k
        from binascii import hexlify
        t = str(hexlify(os.urandom(8)), "ascii")
        self.tokens = (self.tokens + [[t, c]])[-8:]
        return t

    def api(self, req):
        from lv.clock import ticks_ms
        p = req.path
        K = self.K
        sh = self.ship
        if p == "/api/crew":
            return 200, {"set": [self.book.is_set(c) for c in range(8)], "day": 1, "safe": sh.why,
                         "retry_s": sh.retry_s()}
        if p == "/api/v":
            return 200, {"v": 0}
        if p == "/api/me":
            c = self.book.recall(req.phone(), 1)
            if c is None:
                return 401, {"err": "signed out"}
            return 200, {"token": self.token(c), "crew": c, "first": False}
        if p == "/api/state":
            if self.who(req) is None:
                return 401, {"err": "signed out"}
            return 503, {"err": "Your ship is in safe mode.", "safe": sh.why, "detail": sh.detail,
                         "retry_s": sh.retry_s()}
        if req.method != "POST":
            return 404, {"err": "no such thing"}
        try:
            b = json.loads(req.body or b"{}")
        except ValueError:
            b = {}
        if p == "/api/login":
            try:
                c, pin = int(b.get("crew")), str(b.get("pin", ""))
            except (TypeError, ValueError, AttributeError):
                return 400, {"err": "bad request"}
            st, v = self.book.check(c, pin, ticks_ms())
            if st == K.OK:
                self.book.remember(req.phone(), c, 1)
                return 200, {"token": self.token(c), "crew": c, "first": False}
            if st == K.WRONG:
                return 403, {"err": "That code doesn't match.", "left": v}
            if st == K.LOCKED:
                return 429, {"err": "Too many tries.", "wait": v}
            return 409, {"err": "No code set up for this name yet."}
        if p == "/api/logout":
            t = req.header("x-crew-token")
            self.tokens = [x for x in self.tokens if x[0] != t]
            self.book.forget(req.phone())
            return 200, {"ok": True}
        if p == "/api/safe/retry":
            if self.who(req) is None:
                return 401, {"err": "signed out"}
            retry(self.data)
            return 200, {"ok": True, "restart_ms": 1500}
        return 503, {"err": "Your ship is in safe mode.", "safe": sh.why}


def server(lvweb, cfg, why, ip, reboot=None, data=D, root=""):
    """-> (lvweb.Server, the safe ship). main.py starts it on the hotspot."""
    sh = Ship(cfg, why, data)
    web = lvweb.Server(sh, root=root, ip=ip, say=sh.say)
    web.phone = Phone(sh)

    async def route(req, w):
        p = req.path
        sh.clock.learn_headers(req.header)
        if req.method == "GET":
            s = lvweb.STATIC.get(p)
            if s:
                return await lvweb.send_file(w, web.root + s[0], s[1])
            if p == "/status":
                return await lvweb.send(w, 200, "SAFE %s\n" % why, "text/plain")
        if p == "/api/ota/put":
            try:
                import lvotap           # the upload (0.3.0): lvota only for the envelope
            except ImportError as e:    # damaged: lvota.api answers (R1 M2), never silence
                sh.say("safe: upload code %r" % (e,))
                lvotap = None
            try:
                if lvotap is not None:
                    return await lvotap.api(web, req, w)
            finally:
                lvotap = None
                import sys
                sys.modules.pop("lvotap", None)
                sys.modules.pop("lvota", None)
        if p.startswith("/api/ota"):
            import lvota
            try:
                return await lvota.api(web, req, w)
            finally:
                import sys
                sys.modules.pop("lvota", None)
        if p.startswith("/api/"):
            code, obj = web.phone.api(req)
            await lvweb.send_json(w, code, obj)
            if p == "/api/safe/retry" and code == 200:
                import asyncio

                async def later():
                    await asyncio.sleep(1)
                    if reboot:
                        return reboot()
                    import machine
                    machine.reset()
                asyncio.create_task(later())
            return
        return await lvweb.send(w, 302, "", "text/plain", "Location: http://%s/\r\n" % ip)
    web.route = route
    return web, sh
