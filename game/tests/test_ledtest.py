# "Test light" on the ship (board/lvledtest.py, POST /api/led/test from board/main.py's
# ota_route), in real time on a fake pin: refused without a signed-in session (401) or as a
# GET (404); the pattern (three full blinks, a dark gap, three software-PWM breaths that swell
# and fade, 10 s in all, dark at the end); one at a time (a tap while it plays is 429 with the
# ms left, and plays nothing more); it plays with the Ship light off (lv/led.py's dark
# Notifier) and on (lvled.Led: held dark, off the pin, for the test, then back to what it
# was doing, its gift still waiting); the breath as a plain blink while the radio or a
# request is busy; the event loop free throughout (a 100 ms ticker, and main.py's own
# charger_watch catching the charger plugged in mid-test); no light to drive (no
# machine.Pin) is a 500 that leaves nothing running; a pin that fails mid-pattern ends the
# test cleanly; the module dropped after each request. Runs on CPython and MicroPython
# (stock and the game firmware's unix build):
#   python3 tests/test_ledtest.py && micropython tests/test_ledtest.py        (from game/)
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
import lvship  # noqa: E402
import lvweb  # noqa: E402
import lvled  # noqa: E402
import lvledcfg  # noqa: E402
import lvledtest  # noqa: E402
from lv.led import Notifier  # noqa: E402
from lv.clock import Clock  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


now = lvship.ticks_ms
diff = lvship.ticks_diff
MS = lvledtest.TEST_MS
check("10 s (0.3.0: was 4 s)", MS == 10000, MS)

# -- the pattern itself (level: 0-100 at t ms, -1 when over)
L = lvledtest.level
check("blink 1, 2, 3 full on", L(0) == 100 and L(249) == 100 and L(500) == 100 and L(1000) == 100 and L(1249) == 100)
check("dark between blinks", L(250) == 0 and L(499) == 0 and L(750) == 0 and L(1499) == 0)
check("dark gap before the breath", all(L(t) == 0 for t in range(1500, 1800, 10)))
for k in range(3):                # three breaths, 2.7 s each: 1.2 s up, 1.5 s down
    b0 = 1800 + k * 2700
    up = [L(t) for t in range(b0, b0 + 1200, 10)]
    dn = [L(t) for t in range(b0 + 1200, b0 + 2700, 10)]
    check("breath %d swells 0 to ~100" % (k + 1), up[0] == 0 and up == sorted(up) and up[-1] >= 98, (up[0], up[-1]))
    check("breath %d fades back to ~0" % (k + 1), dn[0] == 100 and dn == sorted(dn, reverse=True) and dn[-1] <= 1, (dn[0], dn[-1]))
check("dark after the third breath, to the end", all(L(t) == 0 for t in range(9900, MS, 5)))
check("over at TEST_MS", L(MS - 1) >= 0 and L(MS) == -1 and L(MS + 500) == -1)
check("never out of range", all(0 <= L(t) <= 100 for t in range(0, MS, 7)))
del up, dn


class Pin:
    def __init__(self, name="pin", fail_at=None):
        self.log = []           # (ms since T0, value)
        self.name = name
        self.fail_at = fail_at

    def value(self, v):
        if self.fail_at is not None and len(self.log) >= self.fail_at:
            raise OSError(5)
        self.log.append((diff(now(), T0[0]), 1 if v else 0))


T0 = [0]
SAID = []


class Ship:
    def __init__(self, led):
        self.led = led
        self.ble = None
        self.web = None
        self.cfg = {"ship_id": 5}
        self.ledtest = None

    def say(self, s):
        SAID.append(s)


class Busy:
    def __init__(self):
        self.on = False

    def busy(self):
        return self.on


class Phone:
    def who(self, req):
        return 3 if req.header("x-crew-token") == "tok" else None


class Server:
    routed = []

    def __init__(self, ship):
        self.ship = ship
        ship.web = self
        self.busy = 0

    def get_phone(self):
        return Phone()

    async def route(self, req, w):
        Server.routed.append(req.path)


class FakeLvweb:
    MAX_BODY = 512
    STATIC = {}
    send_json = staticmethod(lvweb.send_json)
    dns_answer = staticmethod(lambda q, ip: None)


class Req:
    def __init__(self, method, path, tok=None):
        self.method, self.path, self.q, self.body = method, path, {}, b"{}"
        self.hdr = {"x-crew-token": tok} if tok else {}

    def header(self, k):
        return self.hdr.get(k)


class Wr:
    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


src = open(HERE + "/board/main.py").read()
g = {"lvship": lvship, "asyncio": asyncio}
exec(src[src.index("def ota_hooks"):src.index("\nasync def ota_ok")], g)
exec(src[src.index("# ---- the charger line"):src.index("\ndef main():")], g)
src = None


def hook(ship):
    srv = Server(ship)
    g["ota_hooks"](FakeLvweb, srv)
    return srv


async def ask(srv, req):
    w = Wr()
    await srv.route(req, w)
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)


def lit_ms(log, a, b):
    """ms the pin was on between a and b (ms since T0), from its write log."""
    t, v, on = a, 0, 0
    for (tt, vv) in log:
        if tt <= a:
            v = vv
            continue
        if tt >= b:
            break
        if v:
            on += tt - t
        t, v = tt, vv
    if v:
        on += b - t
    return on


def writes(log, a, b):
    return len([1 for (t, _) in log if a <= t < b])


# -- 1. the light off (lv/led.py's dark Notifier): refusals, then the whole pattern
async def off_case():
    pin = Pin()
    sh = Ship(Notifier(Clock(), False))
    sh.led_pin = lambda: pin
    srv = hook(sh)
    for name, req, want in (("GET", Req("GET", "/api/led/test", "tok"), 404),
                            ("no session", Req("POST", "/api/led/test"), 401),
                            ("a session nobody has", Req("POST", "/api/led/test", "old"), 401)):
        s, j = await ask(srv, req)
        check("refused, %s: %d" % (name, want), s == want, (s, j))
    check("refused: nothing played", pin.log == [] and sh.ledtest is None)
    check("refused: never reached the game", Server.routed == [])
    gaps = []
    bat = [50, 3900, False, 0, 0, 0, now(), 999999]
    sh.bat = bat
    flips = [False]
    stop = [False]

    async def ticker():          # anything else on the loop: wakes every 100 ms
        t = now()
        while not stop[0]:
            await lvship.sleep_ms(100)
            n = now()
            gaps.append(diff(n, t))
            t = n
    tk = asyncio.create_task(ticker())
    cw = asyncio.create_task(g["charger_watch"](sh, rd=lambda: flips[0], stop=lambda: stop[0]))
    T0[0] = now()
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("started: 200 {ok, ms}", s == 200 and j.get("ok") is True and j.get("ms") == MS, (s, j))
    check("started: dropped from sys.modules", "lvledtest" not in sys.modules)
    check("started: running", sh.ledtest is not None)
    await lvship.sleep_ms(600)
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("second tap while playing: 429 with the ms left", s == 429 and MS - 2000 <= j.get("ms", 0) <= MS - 400, (s, j))
    check("R3 m2: a Test light's own 429 is kind test", j.get("kind") == "test", j)
    flips[0] = True               # the charger plugged in mid-test
    t_plug = diff(now(), T0[0])
    while sh.ledtest is not None and diff(now(), T0[0]) < MS + 2000:
        await lvship.sleep_ms(20)
    end = diff(now(), T0[0])
    stop[0] = True
    await lvship.sleep_ms(250)
    check("over in about TEST_MS", MS - 50 <= end <= MS + 400, end)
    log = pin.log
    check("ends dark", log and log[-1][1] == 0, log[-3:])
    for i in range(3):
        a = i * 500
        on = lit_ms(log, a, a + 500)
        check("blink %d: ~250 ms fully on" % (i + 1), 200 <= on <= 300, on)
        check("blink %d: one on, one off" % (i + 1), writes(log, a, a + 500) <= 3, writes(log, a, a + 500))
    check("dark gap", lit_ms(log, 1540, 1780) == 0)
    for b in range(3):
        b0 = 1800 + b * 2700
        rise = [lit_ms(log, b0 + k * 240, b0 + 240 + k * 240) for k in range(5)]
        fall = [lit_ms(log, b0 + 1200 + k * 300, b0 + 1500 + k * 300) for k in range(5)]
        check("breath %d: dim, then brighter, then full near the top" % (b + 1), rise[0] < 20 and rise[0] < rise[2] < rise[4] and rise[4] >= 140, rise)
        check("breath %d: then fades" % (b + 1), fall[0] > fall[2] > fall[4] and fall[4] < 20, fall)
        check("breath %d: software PWM (many short pulses, not one long on)" % (b + 1), writes(log, b0 + 200, b0 + 1800) >= 100, writes(log, b0 + 200, b0 + 1800))
    check("dark for the last 100 ms", lit_ms(log, 9920, MS) == 0, lit_ms(log, 9920, MS))
    check("one test only (the 429 played nothing)", lit_ms(log, MS + 100, end + 250) == 0)
    check("event loop free: the 100 ms ticker never late by more than 60 ms", gaps and max(gaps) < 160, max(gaps) if gaps else None)
    check("charger_watch saw the plug mid-test", bat[2] is True and t_plug < MS, (bat[2], t_plug))
    await tk
    await cw
    T0[0] = now()
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("after it ends: a new test starts", s == 200)
    await lvship.sleep_ms(MS + 300)
    check("after it ends: done again", sh.ledtest is None and pin.log[-1][1] == 0)

# -- 2. the light on (lvled.Led, a gift waiting): held dark for the test, then back
async def on_case():
    tp, lp = Pin("test"), Pin("led")
    led = lvledcfg.make(Clock(), {"led_quiet": "", "led_unknown_time": True}, say=SAID.append, pin=lambda: lp)
    led.set_enabled(True)
    led.note("gift")
    sh = Ship(led)
    sh.led_pin = lambda: tp
    srv = hook(sh)
    T0[0] = now()
    task = asyncio.create_task(led.run(sh, lvship.sleep_ms))
    await lvship.sleep_ms(1500)
    check("light on: the gift pulses before the test", writes(lp.log, 0, 1500) > 10, len(lp.log))
    t1 = diff(now(), T0[0])
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("light on: started", s == 200)
    while sh.ledtest is not None:
        await lvship.sleep_ms(20)
    t2 = diff(now(), T0[0])
    check("light on: the notifier never wrote during the test", writes(lp.log, t1 + 20, t2) == 0,
          [x for x in lp.log if t1 + 20 <= x[0] < t2][:5])
    check("light on: the test pattern played", writes(tp.log, t1, t2) >= 100 and tp.log[-1][1] == 0)
    await lvship.sleep_ms(4500)
    check("light on: back to the gift pulses after", writes(lp.log, t2, t2 + 4500) > 10, writes(lp.log, t2, t2 + 4500))
    check("light on: still on, the gift still waiting", led.enabled and led.gifts == 1 and led.state == "gift", (led.enabled, led.gifts, led.state))
    led.set_enabled(False)
    await task

# -- 3. busy radio: the breath as a plain blink
async def busy_case(http=False):
    pin = Pin()
    sh = Ship(Notifier(Clock(), False))
    sh.ble = Busy()
    sh.led_pin = lambda: pin
    srv = hook(sh)
    said = len(SAID)
    T0[0] = now()
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("busy: started for the full duration (including after module reload)",
          s == 200 and j.get("ms") == MS, (s, j))
    if http:
        srv.busy = 1
    else:
        sh.ble.on = True
    while sh.ledtest is not None:
        await lvship.sleep_ms(20)
    elapsed = diff(now(), T0[0])
    check("busy: no playback exception", not any("test stopped" in s for s in SAID[said:]), SAID[said:])
    check("busy: plays for TEST_MS, not just an advertised duration", MS - 50 <= elapsed <= MS + 400,
          (elapsed, pin.log, SAID[said:]))
    check("busy: the breaths plain (a couple of writes each, not PWM)", writes(pin.log, 1800, MS) <= 12, writes(pin.log, 1800, MS))
    check("busy: still lit through each one's middle", all(lit_ms(pin.log, 1800 + k * 2700, 4500 + k * 2700) >= 500 for k in range(3)),
          [lit_ms(pin.log, 1800 + k * 2700, 4500 + k * 2700) for k in range(3)])
    for k in range(3):
        b0 = 1800 + k * 2700
        # Integrate writes, don't sample a software-PWM pin at one instant. The bright
        # middle (level >= 50) must stay on even when BLE or HTTP suppresses PWM.
        middle = lit_ms(pin.log, b0 + 800, b0 + 1600)
        check("busy: breath %d has a solid bright middle" % (k + 1), middle >= 700, middle)
    check("busy: blinks unchanged", 200 <= lit_ms(pin.log, 0, 500) <= 300)

# -- 4. no light to drive, and a pin that fails mid-pattern
async def fail_case():
    sh = Ship(Notifier(Clock(), False))
    srv = hook(sh)
    has_pin = False
    try:
        from machine import Pin as _P  # noqa: F401
        has_pin = True
    except ImportError:
        pass
    if not has_pin:
        del SAID[:]
        s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
        check("no machine.Pin: 500, nothing running", s == 500 and sh.ledtest is None and j.get("err"), (s, j))
        check("no machine.Pin: said why", any("no light" in x for x in SAID), SAID)
    pin = Pin(fail_at=4)
    sh.led_pin = lambda: pin
    del SAID[:]
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("failing pin: started", s == 200)
    await lvship.sleep_ms(1500)
    check("failing pin: the test ended, not stuck", sh.ledtest is None)
    check("failing pin: said so", any("test stopped" in x for x in SAID), SAID)
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("failing pin: a new tap is taken", s == 200)
    await lvship.sleep_ms(300)
    # other paths still go where they went
    Server.routed = []
    await srv.route(Req("POST", "/api/led", "tok"), Wr())
    await srv.route(Req("GET", "/api/state", "tok"), Wr())
    check("other paths (incl. /api/led) go to the game", Server.routed == ["/api/led", "/api/state"], Server.routed)


asyncio.run(off_case())
asyncio.run(on_case())
asyncio.run(busy_case())
asyncio.run(busy_case(http=True))
asyncio.run(fail_case())


# -- 5. (0.3.0 review 2 M3) the busy mark only once a task exists, and a stale mark cleared
class NoTask:
    @staticmethod
    def create_task(c):
        c.close()                       # (no "never awaited" warning on CPython)
        raise MemoryError("no heap for a task")


def no_task_case():
    import lvflick
    import lvotaq
    sh = Ship(Notifier(Clock(), True))
    sh.led_pin = lambda: Pin()
    srv = Server(sh)
    real = lvledtest.asyncio
    lvledtest.asyncio = NoTask
    try:
        lvledtest.start(srv, Req("POST", "/api/led/test", "tok"))
        check("M3: Test light with no task raises", False)
    except MemoryError:
        pass
    finally:
        lvledtest.asyncio = real
    check("M3: Test light with no task: not marked busy", sh.ledtest is None, sh.ledtest)
    real = lvflick.asyncio
    lvflick.asyncio = NoTask
    del SAID[:]
    try:
        r = lvflick.start(sh)
    finally:
        lvflick.asyncio = real
    check("M3: a hail's flicker with no task: False, not marked busy", r is False and sh.ledtest is None, (r, sh.ledtest))
    check("M3: ... and said so", any("no task" in x for x in SAID), SAID)
    sh.ledtest = lvship.ticks_ms()
    check("M3: a running mark is busy (flick, update pieces)", lvflick.led_busy(sh) and lvotaq.lit(sh, lvship))
    sh.ledtest = lvship.ticks_ms() - 16000
    check("M3: a mark past its end + 5 s is stale: flick clears it", not lvflick.led_busy(sh) and sh.ledtest is None)
    sh.ledtest = lvship.ticks_ms() - 16000
    check("M3: ... and so do update pieces", not lvotaq.lit(sh, lvship) and sh.ledtest is None)
    for m in ("lvflick", "lvotaq", "lvlight"):
        sys.modules.pop(m, None)


no_task_case()
print("led test: %d checks ok" % ok[0])
