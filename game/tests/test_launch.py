# The launch light at power-on (0.3.4, board/lvlaunch.py, started by board/main.py's launch()
# at the top of run()), on fake PWMs and the virtual clock test_ledtest.py uses: the colour
# at key times in each phase (power-on blue flickers, the tanking breath, the orange ignition
# and its stutter, the jittering orange-yellow thrust, white at liftoff, the blue fade), dark
# and over at 8 s with every PWM off and deinit'd; skipped (lvlaunch never loaded) without
# rgb_pins or with refused ones; never marks the light busy (a Test light tap is never 429);
# a Test light tap takes over (the launch's PWMs off, the test plays its 18 s); an update
# starting (web.ota_busy) or a hail's mark (sh.ledtest) stops it, all off; a failing or
# unmakeable PWM, a cancel, a broken module and a full heap at create_task never escape and
# leave nothing driven; the event loop keeps turning meanwhile. Runs on CPython and
# MicroPython:  python3 tests/test_launch.py && micropython tests/test_launch.py  (from game/)
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
import lvlaunch  # noqa: E402
import lvrgb  # noqa: E402
from lv.led import Notifier  # noqa: E402
from lv.clock import Clock  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


L, D, MS = lvlaunch.level, lvlaunch.duty, lvlaunch.LAUNCH_MS


def rgb(t):
    return (L(t, 0), L(t, 1), L(t, 2))


# -- 1. the sequence itself
check("8 s", MS == 8000)
check("never out of range", all(0 <= L(t, k) <= 255 for t in range(0, MS, 3) for k in range(3)))
check("over at 8 s", L(MS - 1, 0) >= 0 and rgb(MS) == (-1, -1, -1) and L(MS + 500, 2) == -1 and L(-1, 0) == -1)
# power on: faint cool blue (blue most, no red), on/off flickers
B = rgb(0)
check("power on: faint cool blue", B[0] == 0 and 0 < B[1] < B[2] <= 140, B)
check("power on: flicker 1 on", rgb(60) == B and rgb(119) == B)
check("power on: dark between flickers", rgb(120) == (0, 0, 0) and rgb(300) == (0, 0, 0) and rgb(449) == (0, 0, 0) and rgb(600) == (0, 0, 0) and rgb(899) == (0, 0, 0))
check("power on: flicker 2 and 3", rgb(450) == B and rgb(599) == B and rgb(900) == B and rgb(1499) == B)
on = [t for t in range(1, 1600) if L(t, 2) > 0 and L(t - 1, 2) == 0]
check("power on: 2 more onsets, never more than 3 in any second", on == [450, 900], on)
# tanking: a breath up to pale white-blue and back
P = rgb(2250)
check("tanking: pale white-blue at the top", P[2] >= P[1] >= P[0] >= 100 and P[2] >= 200, P)
up = [L(t, 0) for t in range(1500, 2251, 10)]
dn = [L(t, 0) for t in range(2250, 3000, 10)]
check("tanking: swells, then settles back", up == sorted(up) and dn == sorted(dn, reverse=True) and rgb(2999)[0] < 10)
# ignition: a sudden deep orange, stuttering
O = rgb(3000)
check("ignition: sudden deep orange", O[0] == 255 and 20 <= O[1] <= 80 and O[2] == 0 and rgb(2999)[2] > 0, (O, rgb(2999)))
check("ignition: stutters (dims twice)", rgb(3050) == O and rgb(3140)[0] < 128 and rgb(3200) == O and rgb(3330)[0] < 128 and rgb(3500) == O)
# full thrust: orange-yellow, jittering
th = [rgb(t) for t in range(4400, 6000, 20)]
check("thrust: orange-yellow, no blue", all(r >= g > 0 and b == 0 for (r, g, b) in th), th[:3])
rs = [r for (r, g, b) in th]
check("thrust: bright (at least 60 % of full red)", min(rs) >= 150 and max(rs) >= 240, (min(rs), max(rs)))
check("thrust: flickers (many levels, steps both ways)", len(set(rs)) >= 15 and any(rs[i + 1] > rs[i] for i in range(len(rs) - 1)) and any(rs[i + 1] < rs[i] for i in range(len(rs) - 1)))
check("thrust: same 60 ms step, same level", rgb(4980) == rgb(5039))
check("jitter 160-255", all(160 <= lvlaunch.jitter(t) <= 255 for t in range(0, 9000, 7)))
check("thrust ramps from orange to yellow", rgb(4400)[1] * 255 // max(1, rgb(4400)[0]) > rgb(3600)[1] * 255 // max(1, rgb(3600)[0]))
# liftoff: white, then a dimming blue, then dark
W = rgb(7000)
check("liftoff: white", min(W) >= 200, W)
m = rgb(6500)
check("liftoff: on the way from yellow to white", m[0] >= 200 and 0 < m[2] < W[2], m)
Bl = rgb(7500)
check("liftoff: then blue", Bl[2] > Bl[1] > Bl[0] == 0, Bl)
fade = [sum(rgb(t)) for t in range(7500, 8000, 10)]
check("liftoff: fades to dark", fade == sorted(fade, reverse=True) and rgb(7999) == (0, 0, 0))
# the Test light's curve, exactly, in small ints
check("duty: lvrgb.duty's curve", all(D(v, s) == lvrgb.duty(v, s) for v in range(-1, 256) for s in (1, 7, 40, 70, 99, 100)))
check("duty: products stay small ints", 255 * 255 * 100 < 1 << 30 and 25499 * 257 < 1 << 30)
sys.modules.pop("lvlaunch", None)
sys.modules.pop("lvrgb", None)
sys.modules.pop("lvlight", None)
del lvlaunch, lvrgb


# -- 2. on the ship: fakes, main.py's own launch() and Test light route, the virtual clock
T0 = [0]
SAID = []
ERRS = []


def now():
    return lvship.ticks_ms()


diff = lvship.ticks_diff


class PWM:
    def __init__(self, n, fail_at=None):
        self.n, self.log, self.dead, self.fail_at = n, [], False, fail_at
        self.duty = 0

    def duty_u16(self, d):
        if self.dead:
            raise ValueError("deinit")
        if self.fail_at is not None and len(self.log) >= self.fail_at:
            raise OSError(5)
        check("duty in 0-65535", 0 <= d <= 65535, d)
        self.duty = d
        self.log.append((diff(now(), T0[0]), d))

    def deinit(self):
        self.dead = True


class Pin:
    def __init__(self):
        self.log = []

    def value(self, v):
        self.log.append(v)


class Ship:
    def __init__(self, pins, **cfg):
        self.led = Notifier(Clock(), False)
        self.ble = None
        self.web = None
        self.cfg = {"ship_id": 5}
        if pins != "absent":
            self.cfg["rgb_pins"] = pins
        self.cfg.update(cfg)
        self.ledtest = None
        self.made = {}
        self.fail_at = None
        self.pin = Pin()
        self.led_pin = lambda: self.pin

        def mk(n):
            self.made[n] = PWM(n, self.fail_at)
            return self.made[n]
        self.rgb_pwm = mk

    def say(self, s):
        SAID.append(s)


class Phone:
    def who(self, req):
        return 3 if req.header("x-crew-token") == "tok" else None


class Server:
    def __init__(self, ship):
        self.ship = ship
        ship.web = self
        self.busy = 0

    def get_phone(self):
        return Phone()

    async def route(self, req, w):
        pass


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
g = {"lvship": lvship, "asyncio": asyncio, "print": lambda *a: SAID.append(" ".join([str(x) for x in a]))}
exec(src[src.index("def http_admission"):src.index("\nasync def ota_ok")], g)
exec(src[src.index("def launch(ship):"):src.index("\ndef no_setup")], g)
check("main.py: run() starts the launch before the web server", 0 < src.index("launch(ship)  ") < src.index("web = lvweb.Server(ship"))
src = None
launch = g["launch"]


def hook(ship):
    srv = Server(ship)
    g["ota_hooks"](FakeLvweb, srv)
    return srv


async def ask(srv, req):
    w = Wr()
    await srv.route(req, w)
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)


def held(log, at):
    v = 0
    for (tt, d) in log:
        if tt <= at:
            v = d
        else:
            break
    return v


def all_off(sh, n=3):
    return len(sh.made) == n and all(p.dead and p.duty == 0 for p in sh.made.values()) and getattr(sh, "rgb", None) is None


def dropped():
    return not any(m in sys.modules for m in ("lvlaunch", "lvrgb", "lvlight"))


class VClock:                           # as test_ledtest.py: time moves 1 ms a loop round
    def __init__(self):
        self.t = 1000
        self.real = (lvship.ticks_ms, lvship.sleep_ms)
        self.stop = False

    def ticks_ms(self):
        return self.t

    async def sleep_ms(self, ms):
        end = self.t + max(0, int(ms))
        sleep0 = self.real[1]
        while self.t < end:
            await sleep0(0)

    async def tick(self):
        sleep0 = self.real[1]
        while not self.stop:
            await sleep0(0)
            self.t += 1


async def on_vclock(case):
    vc = VClock()
    lvship.ticks_ms, lvship.sleep_ms = vc.ticks_ms, vc.sleep_ms
    tk = asyncio.create_task(vc.tick())
    try:
        await case()
    finally:
        vc.stop = True
        await tk
        lvship.ticks_ms, lvship.sleep_ms = vc.real


async def settle(sh, cap=MS + 1000):
    t = now()
    while (getattr(sh, "rgb", None) is not None or not sh.made) and diff(now(), t) < cap:
        await lvship.sleep_ms(20)


async def ship_case():
    asyncio.get_event_loop().set_exception_handler(lambda loop, ctx: ERRS.append(ctx))
    import lvlaunch as LL
    LMS = LL.LAUNCH_MS
    LV, DU = LL.level, LL.duty
    LL = None
    sys.modules.pop("lvlaunch", None)
    sys.modules.pop("lvrgb", None)
    sys.modules.pop("lvlight", None)

    # no rgb_pins (absent or null): nothing loaded, nothing made, nothing said
    for v in ("absent", None):
        sh = Ship(v)
        del SAID[:]
        launch(sh)
        await lvship.sleep_ms(200)
        check("no rgb_pins %r: lvlaunch never loaded" % (v,), dropped() and sh.made == {} and SAID == [] and getattr(sh, "rgb", None) is None, (SAID, sh.made))
    # refused pins: said, nothing made, the boot goes on
    sh = Ship([4, 5, 6])
    launch(sh)
    await lvship.sleep_ms(200)
    check("refused pins: nothing made, said why, modules dropped", sh.made == {} and any("rgb_pins" in x for x in SAID) and dropped(), SAID)

    # the whole launch, started by main.py's launch(), the loop free meanwhile
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    gaps = [0, 0, True]                 # the longest gap between ticker turns; running

    async def ticker():
        last = now()
        while gaps[2]:
            await lvship.sleep_ms(5)
            gaps[0] = max(gaps[0], diff(now(), last))
            last = now()
            gaps[1] += 1
    tt = asyncio.create_task(ticker())
    launch(sh)
    check("launch(): returns at once, modules dropped (the task keeps its code)", dropped() and sh.made == {})
    check("launch(): never marks the light busy", sh.ledtest is None)
    await lvship.sleep_ms(1000)
    s, j = 0, None
    check("plays on the RGB pins, onboard LED untouched", len(sh.made) == 3 and sh.pin.log == [] and sh.ledtest is None)
    await settle(sh)
    end = diff(now(), T0[0])
    gaps[2] = False
    await tt
    r, gr, b = sh.made[16].log, sh.made[17].log, sh.made[18].log
    check("over in about 8 s", LMS - 20 <= end <= LMS + 100, end)
    check("ends dark: every duty 0, every PWM deinit'd", all_off(sh))
    check("the loop kept turning (no gap over 30 ms)", gaps[0] <= 30 and gaps[1] > 1000, gaps)
    for at in (60, 300, 460, 2250, 3050, 3140, 5000, 7000, 7500):
        # the task's t is a frame or so behind T0: compare where the level holds still
        want = tuple(DU(LV(at, k), 100) for k in range(3))
        got = (held(r, at + 25), held(gr, at + 25), held(b, at + 25))
        if at in (2250, 5000, 7000, 7500):
            ok_ = all(abs(got[k] - want[k]) <= max(2500, want[k] // 6) for k in range(3))
        else:
            ok_ = got == want
        check("held colour at %d ms" % at, ok_, (got, want))
    check("power on is dark between flickers", held(b, 300) == 0 and held(b, 700) == 0)
    check("thrust flickers: many red duty writes 3.6-6 s", len([1 for (t, d) in r if 3700 <= t < 6000]) >= 25)
    check("no error reached the loop", ERRS == [], ERRS)

    # a Test light tap meanwhile: never 429, it takes over; the launch's PWMs off first
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    launch(sh)
    await lvship.sleep_ms(2000)
    old = dict(sh.made)
    check("before the tap: lit", old[18].duty > 0)
    sh.made.clear()
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("Test light during the launch: 200, the 18 s colour fade", s == 200 and j.get("rgb") is True, (s, j))
    await lvship.sleep_ms(100)
    check("takeover: the launch's PWMs off and deinit'd", all(p.dead and p.duty == 0 for p in old.values()))
    check("takeover: the test plays on fresh PWMs", len(sh.made) == 3 and sh.made[16].duty > 0 and sh.made[16] is not old[16])
    t0 = now()
    while sh.ledtest is not None and diff(now(), t0) < 20000:
        await lvship.sleep_ms(20)
    w = diff(now(), t0)
    check("takeover: the test runs its full 18 s (the launch didn't end it)", 17500 <= w <= 18200, w)
    check("takeover: then all off", all_off(sh))

    # the same takeover when the test's task runs before the launch next looks (on the board
    # the launch is asleep in its 20 ms frame): only sh.rgb changes hands, no mark yet
    import lvrgb as RG
    sh = Ship([16, 17, 18])
    launch(sh)
    await lvship.sleep_ms(1000)
    old = dict(sh.made)
    sh.made.clear()
    tt = asyncio.create_task(RG.play(sh, (16, 17, 18), (100, 100, 100)))
    RG = None
    sys.modules.pop("lvrgb", None)
    await lvship.sleep_ms(200)
    mine = getattr(sh, "rgb", None)
    check("rgb handover: the launch's PWMs off, the test owns the LED", all(p.dead for p in old.values()) and mine is not None and len(sh.made) == 3 and sh.made[16].duty > 0)
    await lvship.sleep_ms(9000)
    check("rgb handover: the launch's end left the test's LED alone", getattr(sh, "rgb", None) is mine and not any(p.dead for p in sh.made.values()))
    await tt
    check("rgb handover: the test ends all off", all_off(sh))

    # an update starting: dark at once, said
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    launch(sh)
    await lvship.sleep_ms(4000)
    check("lit in thrust", sh.made[16].duty > 0)
    del SAID[:]
    srv.ota_busy = 1
    await lvship.sleep_ms(60)
    check("an update stops it, every pin off", all_off(sh), [(p.dead, p.duty) for p in sh.made.values()])
    check("... and said so", any("gave way" in x for x in SAID), SAID)
    # an update already uploading at boot: never lights
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    srv.ota_busy = 1
    launch(sh)
    await lvship.sleep_ms(200)
    check("update busy at the start: nothing made", sh.made == {})

    # a hail's flicker (or any playback mark) during the launch: gives way, mark untouched
    sh = Ship([16, 17, 18])
    launch(sh)
    await lvship.sleep_ms(1500)
    m = sh.ledtest = now()
    await lvship.sleep_ms(60)
    check("a playback mark stops it, all off, the mark left alone", all_off(sh) and sh.ledtest == m)
    sh = Ship([16, 17, 18])
    sh.ledtest = now()
    launch(sh)
    await lvship.sleep_ms(200)
    check("a playback already running: no launch, nothing made", sh.made == {})

    # a PWM that fails mid-launch: ends, all off, said, nothing escapes
    sh = Ship([16, 17, 18])
    sh.fail_at = 15
    del SAID[:]
    launch(sh)
    await lvship.sleep_ms(3000)
    check("failing PWM: ended, every PWM deinit'd", getattr(sh, "rgb", None) is None and all(p.dead for p in sh.made.values()))
    check("failing PWM: said so", any("launch light stopped" in x for x in SAID), SAID)
    # a PWM that can't be made: the others off
    sh = Ship([16, 17, 18])

    def bad(n):
        if n == 18:
            raise OSError("no PWM")
        sh.made[n] = PWM(n)
        return sh.made[n]
    sh.rgb_pwm = bad
    launch(sh)
    await lvship.sleep_ms(200)
    check("unmakeable PWM: the others off, nothing held", all_off(sh, 2))
    check("still no error reached the loop", ERRS == [], ERRS)

    # cancelled (the run ending, a restart): all off
    import lvlaunch as LL
    sh = Ship([16, 17, 18])
    t = asyncio.create_task(LL.play(sh, (16, 17, 18), (100, 100, 100)))
    await lvship.sleep_ms(500)
    t.cancel()
    try:
        await t
    except BaseException:
        pass
    check("cancelled: every pin off", all_off(sh))

    # create_task failing (a full heap): False, nothing made, nothing raised
    class NoTask:
        @staticmethod
        def create_task(c):
            c.close()
            raise MemoryError("full")
    real = LL.asyncio
    LL.asyncio = NoTask
    sh = Ship([16, 17, 18])
    r_ = LL.start(sh)
    LL.asyncio = real
    await lvship.sleep_ms(100)
    check("create_task failing: start() is False, nothing made", r_ is False and sh.made == {})
    # a ship with no cfg at all, a cfg that isn't a dict
    check("start(): no cfg is False", LL.start(object()) is False)
    sh = Ship([16, 17, 18])
    sh.cfg = ["x"]
    check("start(): a broken cfg is False", LL.start(sh) is False)
    LL = None
    sys.modules.pop("lvlaunch", None)

    # main.py's launch() when lvlaunch itself is broken (a damaged .mpy): said, boot goes on
    class Broken:
        pass
    sys.modules["lvlaunch"] = Broken()
    sh = Ship([16, 17, 18])
    del SAID[:]
    launch(sh)
    check("broken module: launch() returns, said, dropped", any("no launch light" in x for x in SAID) and dropped(), SAID)
    sh = Ship([16, 17, 18])
    sh.cfg = None
    launch(sh)
    check("launch(): a ship with no cfg returns quietly", sh.made == {})
    await lvship.sleep_ms(100)
    check("nothing ever reached the loop's error handler", ERRS == [], ERRS)


asyncio.run(on_vclock(ship_case))
print("launch light test: %d checks ok" % ok[0])
