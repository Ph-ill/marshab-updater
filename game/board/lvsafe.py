# Safe mode and the ship's fault notes (board/main.py). Loaded at boot, when something
# crashes and once the ship has run healthily for HEALTHY_MS; dropped after each (lvship.drop),
# so a ship that is fine never carries it. Shipped over the air as lvsafe.mpy: boot.py and
# lvboot.py (the rollback of an update on trial) are USB-only and stay exactly as they are.
#
# Files, all in /data and each written whole (temp file, read back, rename: save()), so a
# power cut mid-write leaves the old copy or the new one, never half of either:
#   fault.json      {"n": crashes in a row, "why": the last one, short; "up": ms it ran}
#                   n goes up by one for each crash main.py catches (the game, one of its
#                   tasks), and the file goes once the ship has run HEALTHY_MS without one.
#   ship.json.bak   the last /data/ship.json that read back as a JSON object (refreshed
#                   once a boot has stayed healthy, only when it differs). If ship.json
#                   can't be read, it is put back from here before anything else starts.
#   live.json       the ship-to-ship switches (lvlive.py): never part of ship.json, so a
#                   switch flipped from a phone can't damage the ship's identity file.
# What a boot does (check()):
#   * an update on trial (ota/state.json): play as normal. A crash then just restarts, so
#     lvboot counts the boot and rolls the update back after MAX_BOOTS (its own rule); the
#     crash isn't counted here, so the version it goes back to doesn't start in safe mode.
#   * ship.json there but not readable: put back from ship.json.bak and play; with no
#     backup, start nothing at all (no hotspot: the defaults would open a public network
#     with another ship's name). That ship needs the updater over USB (docs/OTA.md).
#   * n >= SAFE_AFTER: safe mode: the ship's own hotspot and the update page only (the
#     phone page, sign-in, Settings > Ship software, /api/ota*, /status). No Bluetooth, no
#     story. "Try the game again" (POST /api/safe/retry) or an installed update leaves it.
import json
import os

SAFE_AFTER = 2
HEALTHY_MS = 600000
D = "/data"
fail = None             # tests: called at "write", "read", "rename" to simulate a failure


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


def load(path):
    """A JSON object from path, or None (missing, unreadable, or not an object)."""
    try:
        with open(path) as f:
            j = json.load(f)
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def faults(d=D):
    j = load(d + "/fault.json")
    try:
        return int(j["n"]) if j else 0
    except Exception:
        return 0


def check(trial, d=D, say=print):
    """-> None (play), "safe: <why>" (safe mode) or "off: <why>" (start nothing)."""
    p = d + "/ship.json"
    if exists(p) and load(p) is None:
        b = load(p + ".bak")
        if b is not None and save(p, json.dumps(b)):
            say("safe: ship.json couldn't be read, put back from ship.json.bak")
        else:
            return "off: ship.json can't be read and there's no backup (reinstall with the updater over USB)"
    if trial:
        return None
    n = faults(d)
    if n >= SAFE_AFTER:
        j = load(d + "/fault.json") or {}
        return "safe: %d crashes in a row (%s)" % (n, str(j.get("why", "?"))[:80])
    return None


def crashed(why, trial, up=0, d=D):
    """main.py caught a crash: count it (not on an update's trial) before the restart."""
    if trial:
        return
    n = faults(d) + 1
    save(d + "/fault.json", json.dumps({"n": n, "why": str(why)[:120], "up": up}))


def healthy(d=D, say=print):
    """HEALTHY_MS without a crash: forget the count, refresh ship.json.bak."""
    if exists(d + "/fault.json"):
        try:
            os.remove(d + "/fault.json")
        except OSError:
            pass
    p = d + "/ship.json"
    c = load(p)
    if c is None:
        return
    t = json.dumps(c)
    b = load(p + ".bak")
    if b is None or json.dumps(b) != t:
        if save(p + ".bak", t):
            say("safe: ship.json backed up")


def retry(d=D):
    """Safe mode's Try the game again: one more go (the next crash brings safe mode back)."""
    save(d + "/fault.json", json.dumps({"n": SAFE_AFTER - 1, "why": "tried again"}))


# ---- the safe-mode server: the phone page, sign-in and the update, nothing else ---------
class Ship:
    # What lvweb.Server and lvota need of a ship.
    def __init__(self, cfg, why, data=D, say=print):
        from lv.clock import Clock
        self.cfg = cfg
        self.why = why
        self.data = data
        self.say = say
        self.clock = Clock()
        self.http_hits = 0
        self.v = 0
        self.web = None


class Phone:
    # Sign-in from crew.json (lv/codes.py, as lvphone) and a 503 {safe} for the story.
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

    def api(self, req):
        from lv.clock import ticks_ms
        p = req.path
        K = self.K
        if p == "/api/crew":
            return 200, {"set": [self.book.is_set(c) for c in range(8)], "day": 1, "safe": self.ship.why}
        if p == "/api/v":
            return 200, {"v": 0}
        if p == "/api/state" or p == "/api/me":
            if p == "/api/me" or self.who(req) is None:
                return 401, {"err": "signed out"}
            return 503, {"err": "Your ship is in safe mode.", "safe": self.ship.why}
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
                from binascii import hexlify
                t = str(hexlify(os.urandom(8)), "ascii")
                self.tokens = (self.tokens + [[t, c]])[-8:]
                return 200, {"token": t, "crew": c, "first": False}
            if st == K.WRONG:
                return 403, {"err": "That code doesn't match.", "left": v}
            if st == K.LOCKED:
                return 429, {"err": "Too many tries.", "wait": v}
            return 409, {"err": "No code set up for this name yet."}
        if p == "/api/logout":
            t = req.header("x-crew-token")
            self.tokens = [x for x in self.tokens if x[0] != t]
            return 200, {"ok": True}
        if p == "/api/safe/retry":
            if self.who(req) is None:
                return 401, {"err": "signed out"}
            retry(self.data)
            return 200, {"ok": True, "restart_ms": 1500}
        return 503, {"err": "Your ship is in safe mode.", "safe": self.ship.why}


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
