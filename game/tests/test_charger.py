# The charging bolt at once (board/main.py charger_watch, Debounce, charger; GET /api/bat):
# the charger pin read every CHG_EVERY_MS, a new level taken once it has held CHG_STEADY_MS
# (a plug wiggling in its socket doesn't flicker the bolt), ship.bat[2] set at once and a
# gauge read asked for CHG_GAUGE_MS later (and not more often otherwise). Then the pin set
# up with no pull by default (bat_chg_pull "none", in main.py and lvbatt.py alike: on ship 5
# the RP2040's pull-down masked the UPS-Lite's signal, docs/BATTERY.md), and /api/bat
# (the page's 5 s poll: {v, bat}, learning the phone's clock as every phone request does).
# Runs on CPython and MicroPython:  python3 tests/test_charger.py   (from game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE + "/board")
sys.path.insert(0, HERE)

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


class Clock:
    t = 1000


class FakeLvship:
    """What main.py takes from lvship: ticks and sleep_ms, on a clock the test moves."""

    @staticmethod
    def ticks_ms():
        return Clock.t

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    async def sleep_ms(ms):
        Clock.t += ms
        await asyncio.sleep(0)


src = open(HERE + "/board/main.py").read()
part = src[src.index("# ---- the charger line"):src.index("\ndef main():")]
g = {"lvship": FakeLvship, "asyncio": asyncio}
exec(part, g)
D, STEADY, EVERY, GAUGE = g["Debounce"], g["CHG_STEADY_MS"], g["CHG_EVERY_MS"], g["CHG_GAUGE_MS"]
check("about 300 ms steady, looks every 100 ms, gauge 2 s after", STEADY == 300 and EVERY == 100 and GAUGE == 2000)

# -- Debounce on its own
d = D(False)
check("same level: no change", not d.step(False, 0) and d.v is False)
check("a new level: not yet", not d.step(True, 0) and d.v is False)
check("held 200 ms: not yet", not d.step(True, 200) and d.v is False)
check("held 300 ms: taken", d.step(True, 300) and d.v is True)
check("taken once", not d.step(True, 400) and d.v is True)
d = D(False)
d.step(True, 0)
d.step(False, 100)                   # a bounce back resets it
check("bounce: start over", not d.step(True, 200) and not d.step(True, 400) and d.step(True, 500))
d = D(False)
for t in range(0, 3000, 100):        # a loose plug: flips every look, never held
    changed = d.step(t // 100 % 2 == 1, t)
    check("flicker %d: never taken" % t, not changed and d.v is False)
d = D(None)                          # lvbatt couldn't read the pin: the first real level is taken
check("from unknown", not d.step(True, 0) and d.step(True, 300) and d.v is True)
d = D(True)
check("a failed look (None) changes nothing", not d.step(None, 0) and not d.step(None, 1000) and d.v is True)


# -- charger_watch on a ship
class Ship:
    def __init__(self, chg=False):
        self.cfg = {}
        self.bat = [72, 3950, chg, 72 * 256, 3950, 0, 0, 60000, 50]
        self.clock = PhoneClock()
        self.days = 0

    def day_check(self):
        self.days += 1


class PhoneClock:
    def learn_headers(self, hd):
        return hd("x-phone-time") is not None


class Pin:
    def __init__(self, v=False):
        self.v = v
        self.reads = 0
        self.fail = False

    def __call__(self):
        self.reads += 1
        if self.fail:
            raise OSError(5)
        return self.v


def run(ship, rd, ms, script=()):
    """Run the watch for ms of fake time; script: [(at_ms, fn)] done as the clock passes."""
    t0 = Clock.t
    todo = list(script)

    def stop():
        while todo and Clock.t - t0 >= todo[0][0]:
            todo.pop(0)[1]()
        return Clock.t - t0 >= ms
    asyncio.run(g["charger_watch"](ship, rd, stop=stop))


s, p = Ship(False), Pin(False)
run(s, p, 2000)
check("unplugged, steady: nothing changes", s.bat[2] is False and s.bat[7] == 60000, s.bat)
check("looks about every 100 ms", 19 <= p.reads <= 21, p.reads)
seen = []
t0 = Clock.t
run(s, p, 3000, [(500, lambda: setattr(p, "v", True))] + [(500 + k * 10, lambda: seen.append((Clock.t - t0, s.bat[2]))) for k in range(1, 80)])
took = [t for t, v in seen if v][:1]
check("plugged in: bat[2] True", s.bat[2] is True, s.bat)
check("plugged in: within 300-500 ms of the cable", took and 300 <= took[0] - 500 <= 500, took)
check("plugged in: the gauge read asked for 2 s on", s.bat[7] == GAUGE and Clock.t - s.bat[6] < 3000, s.bat)
check("the percent untouched by the watch (that's the gauge's)", s.bat[0] == 72 and s.bat[1] == 3950)
s.bat[6], s.bat[7] = Clock.t, 60000  # lvship's loop read the gauge
run(s, p, 2000)
check("still plugged in: no more gauge reads asked for", s.bat[7] == 60000)
# a loose plug: flips every 100-200 ms for 2 s, then out
flips = [(k * 150, (lambda v: lambda: setattr(p, "v", v))(k % 2 == 1)) for k in range(14)]
run(s, p, 4000, flips + [(2100, lambda: setattr(p, "v", False))])
check("a loose plug, then out: unplugged once it held", s.bat[2] is False and s.bat[7] == GAUGE, s.bat)
# lvbatt's own minute reading moved bat[2]: the watch follows it, no flip of its own
s, p = Ship(False), Pin(True)
s.bat[2] = True
run(s, p, 1000)
check("lvbatt's reading taken as the level", s.bat[2] is True and s.bat[7] == 60000, s.bat)
# a pin that errors: nothing changes, no crash
s, p = Ship(True), Pin(False)
p.fail = True
run(s, p, 1000)
check("pin errors: nothing changes", s.bat[2] is True and s.bat[7] == 60000)
# the battery goes (ship.bat None): the watch ends
s, p = Ship(False), Pin(False)
run(s, p, 500, [(200, lambda: setattr(s, "bat", None))])
check("no battery: ends", s.bat is None)
s = Ship(False)
s.bat = None
check("no battery: doesn't start", asyncio.run(g["charger_watch"](s, Pin())) is None)
s = Ship(False)
s.cfg = {"bat_chg": -1}
check("no charger pin (bat_chg -1): no reader", g["charger"](s) is None)
s.cfg = {"bat_chg": None}
check("no charger pin (null): no reader", g["charger"](s) is None)


# -- the pin's pull: "none" by default, in main.py and lvbatt.py. The fake models ship 5:
# the UPS-Lite's line reads 1 plugged in with no pull, 0 with the pull-down on.
class FakeMachine:
    pulls = []
    plugged = True
    I2C = None                  # (lvbatt imports it; not used here)

    class Pin:
        IN = 0
        PULL_UP = 1
        PULL_DOWN = 2

        def __init__(self, n, mode=None, pull=None):
            self.n, self.pull = n, pull
            FakeMachine.pulls.append((n, pull))

        def value(self):
            return 1 if FakeMachine.plugged and self.pull != FakeMachine.Pin.PULL_DOWN else 0


sys.modules["machine"] = FakeMachine
s = Ship(False)
rd = g["charger"](s)
check("main: pin 6, no pull by default", FakeMachine.pulls[-1] == (6, None), FakeMachine.pulls)
check("main: plugged in reads True", rd() is True)
FakeMachine.plugged = False
check("main: unplugged reads False", rd() is False)
FakeMachine.plugged = True
s.cfg = {"bat_chg_pull": "down"}
check("main: pull-down when asked (and it masks it, as on ship 5)", g["charger"](s)() is False and FakeMachine.pulls[-1] == (6, 2))
s.cfg = {"bat_chg_pull": "up", "bat_chg": 7}
g["charger"](s)
check("main: pull-up and another pin when asked", FakeMachine.pulls[-1] == (7, 1))
import lvbatt  # noqa: E402
s = Ship(False)
check("lvbatt: plugged in reads True by default", lvbatt._hw(s)[1]() is True and FakeMachine.pulls[-1] == (6, None), FakeMachine.pulls)
s.cfg = {"bat_chg_pull": "down"}
check("lvbatt: pull-down when asked", lvbatt._hw(s)[1]() is False and FakeMachine.pulls[-1] == (6, 2))
del sys.modules["machine"]

# -- GET /api/bat (main.py ota_route)
import lvweb  # noqa: E402
hooks = src[src.index("def ota_hooks"):src.index("\nasync def ota_ok")]
h = {"lvship": None, "asyncio": asyncio}
exec(hooks, h)


class FakeLvweb:
    MAX_BODY = 512
    send_json = staticmethod(lvweb.send_json)
    dns_answer = staticmethod(lambda q, ip: None)


class Server:
    ship = Ship(True)
    ship.v = 7
    routed = []

    async def route(self, req, w):
        Server.routed.append(req.path)


class Req:
    def __init__(self, method, path):
        self.method, self.path, self.q, self.body, self.hdr = method, path, {}, b"", {}

    def header(self, k):
        return self.hdr.get(k)


class Wr:
    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


srv = Server()
h["ota_hooks"](FakeLvweb, srv)


def http(req):
    w = Wr()
    asyncio.run(srv.route(req, w))
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)


c, j = http(Req("GET", "/api/bat"))
check("/api/bat: the version, and percent, mV, charging", c == 200 and j == {"v": 7, "bat": [72, 3950, True]}, (c, j))
check("/api/bat: no phone clock, no day check", srv.ship.days == 0, srv.ship.days)
r = Req("GET", "/api/bat")
r.hdr["x-phone-time"] = "1"
http(r)
check("/api/bat: the phone's clock learnt, the flight day checked (06:00)", srv.ship.days == 1, srv.ship.days)
srv.ship.bat = None
c, j = http(Req("GET", "/api/bat"))
check("/api/bat: null without a battery", c == 200 and j == {"v": 7, "bat": None}, (c, j))
asyncio.run(srv.route(Req("POST", "/api/bat"), Wr()))
check("/api/bat: POST goes on to the game (404 there)", Server.routed == ["/api/bat"], Server.routed)

print("charger: %d checks ok" % ok[0])
