# Safe mode, the fault notes and ship.json written whole (0.2.7).
#   board/lvledcfg.py save/toggle: the Ship light switch writes ship.json as temp file +
#     read back + rename; a failure at any step (simulated) leaves ship.json byte-for-byte
#     and no stray file; an unreadable ship.json is never replaced (by {} or anything else).
#   board/lvsafe.py: check() at boot (play / safe / off), crashed() counting (not on an
#     update's trial), healthy() forgetting the count and backing ship.json up, retry(),
#     ship.json put back from the backup, and the safe-mode server: the page, sign-in,
#     /api/state 503 {safe}, /api/ota (lvota), /status, Try the game again.
#   board/main.py: ota_ok keeps an update only after OTA_OK_MS and one 2xx answer to a
#     phone (net_hooks counts them), crashed() notes and restarts.
# Runs on CPython and MicroPython (stock and the game firmware's unix build):
#   python3 tests/test_safe.py && micropython tests/test_safe.py        (from game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE)
sys.path.insert(0, HERE + "/board")
import lvweb  # noqa: E402
import lvsafe  # noqa: E402
import lvledcfg  # noqa: E402
from lv import codes as K  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


ROOT = HERE + "/build/safe-test"
D = ROOT + "/data"


def rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rm(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass


def fresh():
    rm(ROOT)
    for p in (ROOT, D):
        try:
            os.mkdir(p)
        except OSError:
            pass


def put(p, t):
    with open(p, "w") as f:
        f.write(t)


def get(p):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None


def files():
    return sorted(os.listdir(D))


SHIP = '{"ship_id": 5, "ship_name": "Test", "hotspot_password": "not-a-real-one", "led_notify": false}'


# ---- lvledcfg: ship.json written whole ------------------------------------------------
class FakeShip:
    def __init__(self):
        self.v = 0
        self.said = []
        self.on = False

    def led_on(self, on):
        self.on = on
        return on

    def say(self, s):
        self.said.append(s)


class FakePhone:
    def __init__(self):
        self.ship = FakeShip()
        self.data = D


fresh()
P = D + "/ship.json"
put(P, SHIP)
ph = FakePhone()
check("toggle on", lvledcfg.toggle(ph, True) is True)
c = json.loads(get(P))
check("led_notify saved", c["led_notify"] is True)
check("the rest kept", c["ship_id"] == 5 and c["hotspot_password"] == "not-a-real-one" and c["ship_name"] == "Test")
check("no stray files", files() == ["ship.json"], files())
for where in ("write", "read", "rename2"):
    before = get(P)

    def boom(w, where=where):
        if w == where or (where == "rename2" and w == "rename"):
            raise OSError("simulated " + w)
    lvledcfg.fail = boom
    lvledcfg.toggle(ph, where != "write")
    lvledcfg.fail = None
    check("fail at %s: ship.json as it was" % where, get(P) == before)
    check("fail at %s: no stray files" % where, files() == ["ship.json"], files())
    check("fail at %s: said so" % where, ph.ship.said[-2] == "led: setting not saved", ph.ship.said[-2:])


def nofrename(w):          # a filesystem that won't rename onto a file: the .old route
    if w == "rename":
        raise OSError("exists")


lvledcfg.fail = nofrename
lvledcfg.toggle(ph, False)
lvledcfg.fail = None
check("rename via .old", json.loads(get(P))["led_notify"] is False and files() == ["ship.json"], files())
put(P, '{"ship_id": 5, "hotspot_pass')            # a half-written file (what 0.2.6 could leave)
lvledcfg.toggle(ph, True)
check("unreadable ship.json left alone", get(P) == '{"ship_id": 5, "hotspot_pass')
check("unreadable: said", "not readable" in ph.ship.said[-2], ph.ship.said[-2:])
rm(P)
lvledcfg.toggle(ph, True)
check("no ship.json: written", json.loads(get(P)) == {"led_notify": True})
check("the password never in what the ship says", not any("not-a-real-one" in s for s in ph.ship.said))

# ---- lvsafe.check / crashed / healthy / retry ------------------------------------------
fresh()
said = []
check("nothing: play", lvsafe.check(False, D, said.append) is None)
put(P, SHIP)
check("ship.json fine: play", lvsafe.check(False, D, said.append) is None)
lvsafe.crashed("ValueError('x')", False, 1234, D)
check("one crash: play", lvsafe.faults(D) == 1 and lvsafe.check(False, D) is None)
lvsafe.crashed("ValueError('y')", True, 1234, D)
check("a trial crash isn't counted", lvsafe.faults(D) == 1)
lvsafe.crashed("MemoryError()", False, 99, D)
w = lvsafe.check(False, D)
check("two in a row: safe mode", w is not None and w.startswith("safe: 2 crashes") and "MemoryError" in w, w)
check("on trial: play (lvboot decides)", lvsafe.check(True, D) is None)
lvsafe.retry(D)
check("try again: one more go", lvsafe.faults(D) == 1 and lvsafe.check(False, D) is None)
lvsafe.healthy(D, said.append)
check("healthy: count gone", lvsafe.faults(D) == 0 and not lvsafe.exists(D + "/fault.json"))
check("healthy: ship.json backed up", json.loads(get(P + ".bak")) == json.loads(SHIP))
n = len(said)
lvsafe.healthy(D, said.append)
check("healthy again: no rewrite when the same", len(said) == n)
put(P, '{"ship_id": 5, "hots')
check("broken ship.json + backup: put back, play", lvsafe.check(False, D, said.append) is None
      and json.loads(get(P)) == json.loads(SHIP))
put(P, "[1, 2]")
check("not an object counts as broken", lvsafe.check(False, D, said.append) is None and json.loads(get(P))["ship_id"] == 5)
rm(P + ".bak")
put(P, "{bad")
w = lvsafe.check(False, D)
check("broken, no backup: off", w is not None and w.startswith("off:"), w)
check("off even on trial", (lvsafe.check(True, D) or "").startswith("off:"))
check("no stray .new", [f for f in files() if f.endswith(".new")] == [], files())
put(P, SHIP)
lvsafe.fail = lambda wh: (_ for _ in ()).throw(OSError("x")) if wh == "rename" else None
check("save fails cleanly", lvsafe.save(D + "/fault.json", "{}") is False and not lvsafe.exists(D + "/fault.json.new"))
lvsafe.fail = None


# ---- the safe-mode server --------------------------------------------------------------
class W:
    def __init__(self):
        self.b = b""

    def write(self, d):
        self.b += bytes(d)

    async def drain(self):
        pass


def req(method, path, body=b"", tok=None):
    r = lvweb.Req()
    r.method = method
    path, _, q = path.partition("?")
    r.path = path
    r.q = lvweb.parse_query(q)
    r.hdr = {"user-agent": "t"}
    if tok:
        r.hdr["x-crew-token"] = tok
    r.body = body
    r.peer = "192.168.4.2"
    return r


def call(web, *a, **k):
    w = W()
    asyncio.run(web.route(req(*a, **k), w))
    head, _, body = w.b.partition(b"\r\n\r\n")
    code = int(head.split(b" ")[1])
    try:
        return code, json.loads(body)
    except ValueError:
        return code, body


fresh()
os.chdir(ROOT)
# a crew.json as the updater writes it (lv/codes.py), crew 0 with code 1234
put(D + "/crew.json", json.dumps(K.make_config(["1234"] + [None] * 7, b"safe-test-salt16")))
os.mkdir("www")
put("www/app.html.gz", "page")
boots = []
cfg = {"ship_id": 5, "http_port": 80, "captive_dns": True}
web, sh = lvsafe.server(lvweb, cfg, "2 crashes in a row (MemoryError())", "192.168.4.1", lambda: boots.append(1),
                        D, ROOT + "/")
code, b = call(web, "GET", "/")
check("safe: the page", code == 200 and b == b"page", (code, b))
code, b = call(web, "GET", "/status")
check("safe: status says so", code == 200 and b.startswith(b"SAFE 2 crashes"), b)
code, b = call(web, "GET", "/api/crew")
check("safe: crew + why", code == 200 and b["set"][0] is True and b["set"][1] is False and "MemoryError" in b["safe"], b)
code, b = call(web, "GET", "/api/state")
check("safe: state signed out", code == 401)
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "0000"}')
check("safe: wrong code", code == 403 and b["left"] >= 1, (code, b))
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "1234"}')
check("safe: sign in", code == 200 and b["crew"] == 0, (code, b))
tok = b["token"]
code, b = call(web, "GET", "/api/state", tok=tok)
check("safe: state 503 {safe}", code == 503 and "MemoryError" in b["safe"], (code, b))
code, b = call(web, "POST", "/api/act", b"{}", tok=tok)
check("safe: no game", code == 503)
code, b = call(web, "GET", "/api/ota")
check("safe: the update status", code == 200 and b.get("ota") == 1, (code, b))
check("lvota dropped", "lvota" not in sys.modules)
code, b = call(web, "POST", "/api/ota/cancel")
check("safe: update writes need sign-in", code == 401)
code, b = call(web, "POST", "/api/safe/retry")
check("safe: retry needs sign-in", code == 401)
code, b = call(web, "GET", "/hotspot-detect.html")
check("safe: captive probe to the page", code == 302)


async def retry():
    w = W()
    await web.route(req("POST", "/api/safe/retry", b"{}", tok), w)
    await asyncio.sleep(1.2)
    return w.b


b = asyncio.run(retry())
check("safe: retry 200 then restart", b.startswith(b"HTTP/1.0 200") and boots == [1], (b[:20], boots))
check("safe: retry left one more go", lvsafe.faults(D) == 1)
os.chdir(HERE)

# ---- main.py: the keep rule, the 2xx count, crashed() -----------------------------------
src = open("board/main.py").read()
src = src[:src.index("\nT0 = time.ticks_ms()")]
g = {"__name__": "main_test"}
exec(src, g)


class T:
    # the time functions main.py uses (CPython has none of them)
    @staticmethod
    def ticks_ms():
        return 1000

    @staticmethod
    def ticks_diff(a, b):
        return a - b


g["time"] = T
web = lvweb.Server(sh, ip="192.168.4.1", say=lambda s: None)
g["net_hooks"](lvweb, web)
asyncio.run(lvweb.send(W(), 404, "x"))
check("404 not counted", web.ok2xx == 0)
asyncio.run(lvweb.send_json(W(), 200, {}))
check("200 counted", web.ok2xx == 1)
web.ok2xx = 0


class FakeOta:
    n = 0

    @staticmethod
    def good():
        FakeOta.n += 1
        return True


sys.modules["lvota"] = FakeOta
g["OTA_OK_MS"] = 10


async def keep():
    t = asyncio.create_task(g["ota_ok"](web))
    await asyncio.sleep(0.8)
    before = FakeOta.n
    web.ok2xx = 1
    await asyncio.sleep(0.8)
    return before, FakeOta.n


a, b2 = asyncio.run(keep())
check("keep: not without a 2xx", a == 0)
check("keep: after the first 2xx", b2 == 1)
check("lvota dropped after", "lvota" not in sys.modules)
boots = []
noted = []
g["reboot"] = lambda: boots.append(1)
real = lvsafe.crashed
lvsafe.crashed = lambda why, trial, up: noted.append((why, trial, up))
try:
    g["crashed"](ValueError("boom"), False, 0)
    lvsafe.crashed = lambda *a: 1 / 0          # even a failing note still restarts
    g["crashed"](ValueError("again"), True, 0)
except Exception as e:
    check("crashed never raises", False, repr(e))
lvsafe.crashed = real
check("crashed: noted", len(noted) == 1 and noted[0][0].startswith("ValueError('boom'") and noted[0][1:] == (False, 1000), noted)
check("crashed: restart", boots == [1, 1])
print("test_safe: %d checks ok (%s)" % (ok[0], sys.implementation.name))
