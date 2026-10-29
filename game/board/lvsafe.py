# Safe mode and the ship's fault notes (board/main.py). Loaded at boot, when something
# crashes and once the ship has run healthily for HEALTHY_MS; dropped after each (lvship.drop),
# so a ship that is fine never carries it. Shipped over the air as lvsafe.mpy: boot.py and
# lvboot.py (the rollback of an update on trial) are USB-only and stay exactly as they are.
#
# Files, all in /data and each written whole (temp file, read back, rename: save()), so a
# power cut mid-write leaves the old copy or the new one, never half of either:
#   fault.json      {"n": crashes in a row, "why": the last one ("Class: text", short),
#                   "up": ms it ran, "tries": times safe mode tried the game again on its own}
#                   n goes up by one for each crash main.py catches (the game, or a task it
#                   can't do without), and the file goes once the game has run HEALTHY_MS.
#   ship.json.bak   the last /data/ship.json that was a whole identity (lvledcfg.valid),
#   crew.json.bak   and the last crew.json with a salt and 8 codes. Refreshed at every boot
#                   and after HEALTHY_MS, each only when it differs (no write otherwise).
# What a boot does (check()), in this order:
#   * ship.json and crew.json: one that is missing, won't parse, or (ship.json) isn't a whole
#     identity is put back from the first good one of .new (a write that got as far as its
#     read-back), .old (0.2.5/0.2.6's crew.json route), .bak. A ship.json that can't be put
#     back: missing on a bench board that never had one, play (the bench's defaults); missing
#     with traces of an old one, or broken: "off". A read error that isn't "no such file"
#     (twice, with a gc in between) is "off" too, and never overwritten: the next boot looks
#     again. "off" puts nothing on the air (the defaults would open the public placeholder
#     hotspot as ship 1) and restarts after OFF_MS, so a passing error passes.
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
fail = None             # tests: called at "write", "read", "rename", "open" to simulate a failure


def _hit(where):
    if fail:
        fail(where)


def exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def save(path, text):
    """Write text to path whole: path.new, read back, rename over path. True, or False
    (path as it was). Rename onto an existing file is one step on littlefs and POSIX."""
    tmp = path + ".new"
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
    from lvledcfg import valid
    return valid(c)


def crew_ok(c):
    s, k = c.get("salt"), c.get("codes")
    return isinstance(s, str) and len(s) >= 16 and isinstance(k, list) and len(k) == 8


def backup(p, c):
    """p.bak := c (already checked good), only when it differs."""
    t = json.dumps(c)
    b = load(p + ".bak")
    return (b is not None and json.dumps(b) == t) or save(p + ".bak", t)


def guard(p, ok, say=print):
    """Keep p good: -> None, or why it can't be (start nothing). See the top of the file."""
    name = p[p.rfind("/") + 1:]
    j = read(p)
    if isinstance(j, dict) and ok(j):
        if not backup(p, j):
            say("safe: %s.bak not written" % name)
        return None
    if j == UNKNOWN:
        return "off: %s can't be read just now; looking again in %d min" % (name, OFF_MS // 60000)
    traces = False
    for x in (".new", ".old", ".bak"):
        c = load(p + x)
        traces = traces or exists(p + x)
        if c is not None and ok(c) and save(p, json.dumps(c)):
            say("safe: %s %s, put back from %s%s" % (name, "missing" if j == MISSING else "not usable", name, x))
            if x == ".old":
                try:
                    os.remove(p + x)
                except OSError:
                    pass
            backup(p, c)
            return None
    if isinstance(j, dict) or (j == MISSING and not traces):
        return None             # as before 0.2.7: a bench board's own (or no) settings
    return "off: %s %s and nothing to put back (the updater over USB)" % (name, j)


def faults(d=D):
    """fault.json's {n, why, up, tries}, {} if there's none (or it's unreadable)."""
    return load(d + "/fault.json") or {}


def count(j):
    try:
        return int(j.get("n", 0))
    except (TypeError, ValueError):
        return 0


def check(trial, d=D, say=print):
    """-> None (play), "safe: <why>" (safe mode) or "off: <why>" (start nothing)."""
    w = guard(d + "/ship.json", ship_ok, say)
    guard(d + "/crew.json", crew_ok, say)        # never "off": safe mode signs in from it
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


def healthy(d=D, say=print):
    """HEALTHY_MS without a crash: forget the count, refresh the backups."""
    if exists(d + "/fault.json"):
        try:
            os.remove(d + "/fault.json")
        except OSError:
            pass
    for f, ok in (("/ship.json", ship_ok), ("/crew.json", crew_ok)):
        c = load(d + f)
        if c is not None and ok(c) and not backup(d + f, c):
            say("safe: %s.bak not written" % f[1:])


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
