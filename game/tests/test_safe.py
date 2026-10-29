# Safe mode, the fault notes and ship.json written whole (0.2.7, with review #1's fixes).
#   board/lvledcfg.py valid/save/toggle: the Ship light switch writes ship.json as temp file
#     + read back + rename, and only over a whole identity (valid); a failure at any step
#     (simulated) leaves ship.json byte-for-byte and no stray file. Review #1 M1: a read
#     error (EIO, no heap) or a missing ship.json is never replaced by {"led_notify": ...}.
#   board/lvsafe.py: check() at boot (play / safe / off), ship.json and crew.json put back
#     from .new/.old/.bak (M2: a missing ship.json after 0.2.6's .old route), a read error
#     that isn't "no such file" never overwritten (m3), crashed() counting (not on an
#     update's trial; nothing written past SAFE_CAP: m1), healthy(), retry()/rest(), the
#     game tried again on its own (M5), and the safe-mode server: the page, sign-in, /api/me
#     (m10), /api/state 503 {safe, detail} signed in only (m8), /api/ota (lvota), /status,
#     Try the game again.
#   board/main.py: ota_ok keeps an update after OTA_OK_MS and a 2xx to a phone or the ship's
#     own check that it serves the page (m7), crashed() notes (the short way when lvsafe
#     can't: M3) and restarts, task_error() stops the game only for the web server's accept
#     loop (M4), keep() restarts a task, safe mode "off" waits and restarts.
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


# ---- lvledcfg: ship.json written whole, only over a whole identity ----------------------
V = lvledcfg.valid
check("valid: a ship", V(json.loads(SHIP)))
check("valid: ship_id as text", V({"ship_id": "3", "hotspot_password": "12345678"}))
check("valid: open hotspot", V({"ship_id": 2, "hotspot_open": True}))
check("valid: the updater's firmware-default password (none written)", V({"schema": 2, "ship_id": 3, "hotspot_open": False}))
for bad in (None, [1], {}, {"led_notify": True}, {"hotspot_password": "12345678"}, {"ship_id": True, "hotspot_password": "12345678"},
            {"ship_id": 9, "hotspot_password": "12345678"}, {"ship_id": 0, "hotspot_password": "12345678"},
            {"ship_id": 3, "hotspot_password": "short"}, {"ship_id": 3, "hotspot_password": 12345678},
            {"ship_id": "x", "hotspot_password": "12345678"}):
    check("not valid: %r" % (bad,), not V(bad))


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


def raiser(where, e):
    def f(w):
        if w == where:
            raise e
    return f


fresh()
P = D + "/ship.json"
put(P, SHIP)
ph = FakePhone()
check("toggle on", lvledcfg.toggle(ph, True) is True)
c = json.loads(get(P))
check("led_notify saved", c["led_notify"] is True)
check("the rest kept", c["ship_id"] == 5 and c["hotspot_password"] == "not-a-real-one" and c["ship_name"] == "Test")
check("no stray files", files() == ["ship.json"], files())
for where in ("write", "read", "rename"):
    before = get(P)
    lvledcfg.fail = raiser(where, OSError("simulated " + where))
    lvledcfg.toggle(ph, where != "write")
    lvledcfg.fail = None
    check("fail at %s: ship.json as it was" % where, get(P) == before)
    check("fail at %s: no stray files" % where, files() == ["ship.json"], files())
    check("fail at %s: said so" % where, ph.ship.said[-2] == "led: setting not saved", ph.ship.said[-2:])
# Review #1 M1: a read of ship.json that fails for a reason other than "no such file" (a
# damaged block: EIO; no heap: MemoryError) used to be taken as "no ship.json" and the file
# replaced by {"led_notify": ...}: the next boot was ship 1 on the public placeholder hotspot.
for e in (OSError(5, "EIO"), MemoryError()):
    before = get(P)
    lvledcfg.fail = raiser("open", e)
    check("M1 %r: the switch still switches" % (e,), lvledcfg.toggle(ph, True) is True and ph.ship.on is True)
    lvledcfg.fail = None
    check("M1 %r: ship.json byte-for-byte" % (e,), get(P) == before and json.loads(get(P))["hotspot_password"] == "not-a-real-one")
    check("M1 %r: no stray files" % (e,), files() == ["ship.json"], files())
    check("M1 %r: said so" % (e,), "not whole" in ph.ship.said[-2], ph.ship.said[-2:])
put(P, '{"ship_id": 5, "hotspot_pass')            # a half-written file (what 0.2.6 could leave)
lvledcfg.toggle(ph, True)
check("unreadable ship.json left alone", get(P) == '{"ship_id": 5, "hotspot_pass')
check("unreadable: said", "not whole" in ph.ship.said[-2], ph.ship.said[-2:])
for t in ('{"led_notify": false}', '{"ship_name": "x"}', '{"ship_id": 3, "hotspot_password": ""}', "[1, 2]"):
    put(P, t)
    lvledcfg.toggle(ph, True)
    check("not an identity left alone: " + t, get(P) == t and files() == ["ship.json"], files())
rm(P)
lvledcfg.toggle(ph, True)
check("M1: no ship.json: none written", files() == [], files())
check("the password never in what the ship says", not any("not-a-real-one" in s for s in ph.ship.said))
check("lvledcfg dropped after the switch", "lvledcfg" not in sys.modules)
import lvledcfg  # noqa: E402,F811

# ---- lvsafe.check / crashed / healthy / retry ------------------------------------------
fresh()
said = []
n_ = lambda: lvsafe.count(lvsafe.faults(D))   # noqa: E731
check("nothing: play", lvsafe.check(False, D, said.append) is None)
check("nothing: nothing written", files() == [], files())
put(P, SHIP)
check("ship.json fine: play", lvsafe.check(False, D, said.append) is None)
check("ship.json fine: backed up at boot (m5)", json.loads(get(P + ".bak")) == json.loads(SHIP))
t = get(P + ".bak")
lvsafe.fail = raiser("write", OSError("no writes please"))
check("same again: play, no write", lvsafe.check(False, D, said.append) is None and get(P + ".bak") == t)
lvsafe.fail = None
lvsafe.crashed("ValueError: x", False, 1234, D)
check("one crash: play", n_() == 1 and lvsafe.check(False, D) is None)
lvsafe.crashed("ValueError: y", True, 1234, D)
check("a trial crash isn't counted", n_() == 1)
lvsafe.crashed("MemoryError: memory allocation failed, allocating 4096 bytes", False, 99, D)
w = lvsafe.check(False, D)
check("two in a row: safe mode, the kind only", w == "safe: 2 crashes in a row (MemoryError)", w)
check("the why kept short", len(lvsafe.faults(D)["why"]) <= 64)
check("on trial: play (lvboot decides)", lvsafe.check(True, D) is None)
lvsafe.retry(D)
check("try again: one more go", n_() == 1 and lvsafe.check(False, D) is None)
check("by hand: no auto try counted", lvsafe.faults(D).get("tries") == 0 and lvsafe.retry_ms(D) == lvsafe.RETRY_MS[0])
lvsafe.crashed("TypeError: z", False, 5, D)
lvsafe.retry(D, True)
check("on its own: tries counted, the next wait longer", lvsafe.faults(D)["tries"] == 1 and lvsafe.retry_ms(D) == lvsafe.RETRY_MS[1])
for _ in range(9):
    lvsafe.retry(D, True)
check("the wait stops growing", lvsafe.retry_ms(D) == lvsafe.RETRY_MS[-1])
# m1: a safe mode that keeps stopping is counted up to SAFE_CAP, then "off", and no more writes
lvsafe.rest(D)
check("rest: safe mode", n_() == lvsafe.SAFE_AFTER and (lvsafe.check(False, D) or "").startswith("safe:"))
for i in range(lvsafe.SAFE_CAP + 3):
    lvsafe.crashed("RuntimeError: loop", False, 1, D)
check("m1: counted up to SAFE_CAP", n_() == lvsafe.SAFE_CAP)
w = lvsafe.check(False, D)
check("m1: then off", w == "off: safe mode stopped 3 times in a row", w)
hits = []
lvsafe.fail = hits.append
lvsafe.crashed("RuntimeError: loop", False, 1, D)
lvsafe.fail = None
check("m1: past the cap nothing written", "write" not in hits and n_() == lvsafe.SAFE_CAP, hits)
lvsafe.rest(D)
check("m1: after off, safe mode once more", (lvsafe.check(False, D) or "").startswith("safe: 2 crashes"))
# m2: a failed note is tried once more
rm(D + "/fault.json")
first = [1]


def once(w):
    if w == "rename" and first:
        first.pop()
        raise OSError("once")


lvsafe.fail = once
lvsafe.crashed("ValueError: q", False, 1, D)
lvsafe.fail = None
check("m2: the note is tried again", n_() == 1)
lvsafe.healthy(D, said.append)
check("healthy: count gone", n_() == 0 and not lvsafe.exists(D + "/fault.json"))
check("healthy: ship.json backed up", json.loads(get(P + ".bak")) == json.loads(SHIP))
n = len(said)
lvsafe.healthy(D, said.append)
check("healthy again: no rewrite when the same", len(said) == n)
put(P, '{"ship_id": 5, "hots')
check("broken ship.json + backup: put back, play", lvsafe.check(False, D, said.append) is None
      and json.loads(get(P)) == json.loads(SHIP))
check("said where from", said[-1] == "safe: ship.json not usable, put back from ship.json.bak", said[-1:])
put(P, "[1, 2]")
check("not an object counts as broken", lvsafe.check(False, D, said.append) is None and json.loads(get(P))["ship_id"] == 5)
put(P, '{"led_notify": true}')
check("not a whole identity (what 0.2.6's toggle could leave) + backup: put back",
      lvsafe.check(False, D, said.append) is None and json.loads(get(P)) == json.loads(SHIP))
# Review #1 M2: 0.2.6's crew.json-style route (move ship.json to .old, rename .new in) cut
# between its two renames leaves no ship.json at all: the ship came up as ship 1 on the
# public placeholder hotspot. Now it is put back from .old (or .new, or .bak).
SHIP2 = SHIP.replace('"Test"', '"Two"')
for have in ((".old",), (".new",), (".new", ".old"), (".bak",)):
    fresh()
    for x in have:
        put(P + x, SHIP2 if x != ".bak" else SHIP)
    if have == (".new", ".old"):
        put(P + ".new", '{"ship_id": 5, "ho')           # the .new cut short: .old it is
    check("M2 missing, %s: play" % "+".join(have), lvsafe.check(False, D, said.append) is None, said[-1:])
    want = SHIP if have == (".bak",) else SHIP2
    check("M2 missing, %s: put back" % "+".join(have), json.loads(get(P)) == json.loads(want), get(P))
    check("M2 missing, %s: said" % "+".join(have), said[-1].startswith("safe: ship.json missing, put back from"), said[-1:])
    check("M2 missing, %s: .old gone, .bak made" % "+".join(have), not lvsafe.exists(P + ".old") and lvsafe.exists(P + ".bak"), files())
fresh()
put(P + ".new", '{"ship_id": 5, "ho')
w = lvsafe.check(False, D)
check("missing, only a broken trace: off", (w or "").startswith("off: ship.json missing"), w)
fresh()
put(P, '{"ship_name": "x"}')
check("a bench board's own (not whole) settings, nothing to put back: play, left alone",
      lvsafe.check(False, D) is None and get(P) == '{"ship_name": "x"}')
put(P, "{bad")
w = lvsafe.check(False, D)
check("broken, no backup: off", w is not None and w.startswith("off:"), w)
check("off even on trial", (lvsafe.check(True, D) or "").startswith("off:"))
check("no stray .new", [f for f in files() if f.endswith(".new")] == [], files())
# m3: a read error that isn't "no such file" is "off" for now, never written over
put(P, SHIP)
lvsafe.check(False, D)
put(P + ".bak", SHIP2)                  # a backup that would differ: must not be used
for e in (OSError(5, "EIO"), MemoryError()):
    lvsafe.fail = raiser("open", e)
    w = lvsafe.check(False, D, said.append)
    lvsafe.fail = None
    check("m3 %r: off, looking again" % (e,), (w or "").startswith("off: ship.json can't be read just now"), w)
    check("m3 %r: ship.json untouched" % (e,), get(P) == SHIP and get(P + ".bak") == SHIP2)
flaky = [1]


def flake(w):
    if w == "open" and flaky:
        flaky.pop()
        raise OSError(5, "EIO")


lvsafe.fail = flake
check("m3: an error that passes on the second look: play", lvsafe.check(False, D) is None and get(P) == SHIP)
lvsafe.fail = None
# m4: crew.json put back too (never "off": safe mode signs in from it)
C = D + "/crew.json"
CREW = json.dumps(K.make_config(["1234"] + [None] * 7, b"safe-test-salt16"))
put(C, CREW)
lvsafe.check(False, D)
check("m4: crew.json backed up", json.loads(get(C + ".bak")) == json.loads(CREW))
put(C, '{"salt": "ab')
check("m4: broken crew.json put back", lvsafe.check(False, D, said.append) is None and json.loads(get(C)) == json.loads(CREW))
rm(C)
rm(C + ".bak")
put(C + ".old", CREW)
check("m4: missing crew.json from 0.2.6's .old", lvsafe.check(False, D) is None and json.loads(get(C)) == json.loads(CREW)
      and not lvsafe.exists(C + ".old"))
rm(C + ".bak")
put(C, "{bad")
check("m4: broken crew.json, nothing to put back: still play", lvsafe.check(False, D) is None)
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
put(D + "/crew.json", CREW)
put(D + "/fault.json", '{"n": 2, "why": "MemoryError: allocating 4096 bytes in lvphone"}')
os.mkdir("www")
put("www/app.html.gz", "page")
boots = []
cfg = {"ship_id": 5, "http_port": 80, "captive_dns": True}
web, sh = lvsafe.server(lvweb, cfg, "2 crashes in a row (MemoryError)", "192.168.4.1", lambda: boots.append(1),
                        D, ROOT + "/")
code, b = call(web, "GET", "/")
check("safe: the page", code == 200 and b == b"page", (code, b))
code, b = call(web, "GET", "/status")
check("safe: status says so", code == 200 and b.startswith(b"SAFE 2 crashes"), b)
check("m8: status has the kind only", b"4096" not in b and b"lvphone" not in b, b)
code, b = call(web, "GET", "/api/crew")
check("safe: crew + why", code == 200 and b["set"][0] is True and b["set"][1] is False and "MemoryError" in b["safe"], b)
check("m8: crew has the kind only", "4096" not in json.dumps(b) and "detail" not in b, b)
check("M5: no retry time before it is set", b["retry_s"] is None, b)
code, b = call(web, "GET", "/api/state")
check("safe: state signed out", code == 401)
code, b = call(web, "GET", "/api/me")
check("m10: /api/me signed out", code == 401)
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "0000"}')
check("safe: wrong code", code == 403 and b["left"] >= 1, (code, b))
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "1234"}')
check("safe: sign in", code == 200 and b["crew"] == 0, (code, b))
tok = b["token"]
code, b = call(web, "GET", "/api/me")
check("m10: a reload stays signed in (/api/me)", code == 200 and b["crew"] == 0 and b["token"] == tok, (code, b))
code, b = call(web, "GET", "/api/state", tok=tok)
check("safe: state 503 {safe}", code == 503 and "MemoryError" in b["safe"], (code, b))
check("m8: signed in, the crash's own words", b.get("detail") == "MemoryError: allocating 4096 bytes in lvphone", b)
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
code, b = call(web, "POST", "/api/logout", b"{}", tok=tok)
code2, b2 = call(web, "GET", "/api/me")
check("m10: signed out after Sign out", code == 200 and code2 == 401, (code, code2))
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "1234"}')
tok = b["token"]
from lv.clock import ticks_ms  # noqa: E402
sh.retry = (ticks_ms(), 60000)
code, b = call(web, "GET", "/api/crew")
check("M5: when the game is tried again", 58 <= b["retry_s"] <= 60, b)
code, b = call(web, "GET", "/api/state", tok=tok)
check("M5: in the signed-in 503 too", 58 <= b["retry_s"] <= 60, b)


async def retry():
    w = W()
    await web.route(req("POST", "/api/safe/retry", b"{}", tok), w)
    await asyncio.sleep(1.2)
    return w.b


b = asyncio.run(retry())
check("safe: retry 200 then restart", b.startswith(b"HTTP/1.0 200") and boots == [1], (b[:20], boots))
check("safe: retry left one more go", lvsafe.count(lvsafe.faults(D)) == 1)
lvsafe.rest(D)
boots = []
asyncio.run(lvsafe.auto_retry(sh, 50, lambda: boots.append(1)))
j = lvsafe.faults(D)
check("M5: on its own: restarts with one more go", boots == [1] and lvsafe.count(j) == 1 and j["tries"] == 1, (boots, j))
check("M5: and the next wait is longer", lvsafe.retry_ms(D) == lvsafe.RETRY_MS[1])
# m7: the ship's own check that it serves the page (main.serves), against the safe server
src = open(HERE + "/board/main.py").read()
src = src[:src.index("\nT0 = time.ticks_ms()")]
g = {"__name__": "main_test"}
exec(src, g)
web.ok2xx = 7
check("m7: the safe server serves the page", asyncio.run(g["serves"](web)) is True)
check("m7: the 2xx count left as it was", web.ok2xx == 7)
os.rename("www/app.html.gz", "www/gone")
check("m7: no page, no keep", asyncio.run(g["serves"](web)) is False)
os.chdir(HERE)

# ---- main.py: the keep rule, crashes, tasks, safe mode off -------------------------------
src = open("board/main.py").read()
src = src[:src.index("\nT0 = time.ticks_ms()")]
g = {"__name__": "main_test"}
exec(src, g)


class T:
    # the time functions main.py uses (CPython has none of them)
    slept = []

    @staticmethod
    def ticks_ms():
        return 1000

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    def sleep_ms(ms):
        T.slept.append(ms)


class Quick:
    # lvship as main.py uses it, with every wait cut to a moment
    @staticmethod
    def sleep_ms(ms):
        return asyncio.sleep(min(ms, 20) / 1000)

    @staticmethod
    def drop(name):
        sys.modules.pop(name, None)


g["time"] = T
g["lvship"] = Quick
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


class FakeWeb:
    # a set that serves the page (or doesn't: up) and counts no 2xx of its own
    def __init__(self):
        self.ok2xx = 0
        self.up = False

    async def route(self, r, w):
        w.write(b"HTTP/1.0 200 OK\r\n" if self.up else b"HTTP/1.0 500 Oops\r\n")
        if self.up:
            self.ok2xx += 1


sys.modules["lvota"] = FakeOta
g["OTA_OK_MS"] = 10


async def keeps(fw, how):
    t = asyncio.create_task(g["ota_ok"](fw))
    await asyncio.sleep(0.2)
    before = FakeOta.n
    how(fw)
    await asyncio.sleep(0.2)
    return before, FakeOta.n


fw = FakeWeb()
a, b2 = asyncio.run(keeps(fw, lambda f: setattr(f, "ok2xx", 1)))
check("keep: not without a 2xx", a == 0)
check("keep: after the first 2xx", b2 == 1)
check("lvota dropped after", "lvota" not in sys.modules)
sys.modules["lvota"] = FakeOta
FakeOta.n = 0
fw = FakeWeb()
a, b2 = asyncio.run(keeps(fw, lambda f: setattr(f, "up", True)))
check("m7: not while the ship's own check fails", a == 0)
check("m7: kept once it serves the page, no phone needed", b2 == 1 and fw.ok2xx == 0, (b2, fw.ok2xx))

# crashed(): noted (by lvsafe, or the short way when it can't: M3), then a restart; the
# trial flag read at the crash (m9)
FD = D + "/fault.json"
fresh()
g["FAULT"] = FD
boots = []
noted = []
trial = [False]
g["reboot"] = lambda: boots.append(1)
g["flag"] = lambda p: trial[0]
real = lvsafe.crashed
lvsafe.crashed = lambda why, trial, up: noted.append((why, trial, up))
try:
    g["crashed"](ValueError("boom"), 0)
    trial[0] = True
    g["crashed"](ValueError("x" * 99), 0)
    trial[0] = False

    def oom(*a):
        raise MemoryError()
    lvsafe.crashed = oom
    g["crashed"](MemoryError(), 0)
    g["crashed"](MemoryError(), 0)
    trial[0] = True
    g["crashed"](MemoryError(), 0)
    trial[0] = False
except BaseException as e:
    check("crashed never raises", False, repr(e))
lvsafe.crashed = real
check("crashed: noted", noted[0] == ("ValueError: boom", False, 1000), noted)
check("m9: the trial read at the crash", noted[1][1] is True and len(noted[1][0]) < 64, noted)
j = json.loads(get(FD))
check("M3: no heap for lvsafe: noted the short way", j["n"] == 2 and j["why"] == "noted the short way", j)
check("M3: not on a trial either", files() == ["fault.json"], files())
check("crashed: restart every time", boots == [1] * 5, boots)
put(FD, '{"n": 5, "why": "x"}')
g["note"](False)
check("M3: the short way stops at the cap too", json.loads(get(FD))["n"] == 5)

# task_error(): only the web server's accept loop stops the game (M4)
class Tk:
    def __init__(self):
        self.off = 0

    def cancel(self):
        self.off += 1


m, srv_task, led_task = Tk(), Tk(), Tk()
g["MAIN"][:] = [m]
g["FATAL"][:] = [srv_task]
g["task_error"](None, {"exception": ValueError("led"), "future": led_task})
check("M4: a light task's error doesn't stop the game", m.off == 0 and g["CRASH"] == [])
e = OSError(23)
g["task_error"](None, {"exception": e, "future": srv_task})
check("M4: the accept loop's does", m.off == 1 and g["CRASH"] == [e])
del g["CRASH"][:]
if sys.implementation.name == "micropython":
    # the real thing: MicroPython calls the handler as the task dies
    async def run():
        g["MAIN"][:] = [asyncio.current_task()]
        asyncio.get_event_loop().set_exception_handler(g["task_error"])

        async def bad():
            raise ValueError("the light")
        asyncio.create_task(bad())
        await asyncio.sleep(0.05)
        t = asyncio.create_task(bad())
        g["FATAL"][:] = [t]
        await asyncio.sleep(0.05)
        return "still here"
    try:
        r = asyncio.run(run())
    except BaseException as e:
        r = e
    check("M4: the fatal task cancels run()", isinstance(r, asyncio.CancelledError) and repr(g["CRASH"][0]).startswith("ValueError"), (r, g["CRASH"]))
    asyncio.new_event_loop()
    del g["CRASH"][:]
    g["FATAL"][:] = []

# keep(): a task that stops is started again, with a growing pause
runs = []


async def flaky_task():
    runs.append(1)
    if len(runs) < 3:
        raise OSError("dns")
    return "done"
check("keep: started again until it runs", asyncio.run(g["keep"]("dns", flaky_task)) == "done" and len(runs) == 3)

# safe_mode "off": nothing on the air, a wait, then a restart (safe mode once more after the cap)
rested = []
real_f, real_r = lvsafe.faults, lvsafe.rest
lvsafe.faults = lambda d=None: {"n": lvsafe.SAFE_CAP}
lvsafe.rest = lambda d=None: rested.append(1)
boots = []
T.slept = []
g["safe_mode"]({}, "off: safe mode stopped 3 times in a row")
check("m1: off waits OFF_MS, rests, restarts", T.slept == [lvsafe.OFF_MS] and rested == [1] and boots == [1], (T.slept, rested, boots))
lvsafe.faults = lambda d=None: {}
g["safe_mode"]({}, "off: ship.json can't be read just now")
check("m3: off for a read error: no rest, restarts", rested == [1] and boots == [1, 1])
lvsafe.faults, lvsafe.rest = real_f, real_r
check("RESET clears fault.json (m11)", "fault.json" in g["RESET"])
print("test_safe: %d checks ok (%s)" % (ok[0], sys.implementation.name))
