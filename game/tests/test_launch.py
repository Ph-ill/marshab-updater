# The launch light at power-on (0.3.4, earlier since 0.3.5, a flame and a Wi-Fi
# indication since 0.3.9, board/lvlaunch.py): started by board/main.py's
# start_launch() as soon as ship.json names rgb_pins, on a machine.Timer, so the
# flame plays through the 2 s boot window and the hotspot; after the flame a blue
# breath waits for the hotspot, then a short green flash. run()'s launch() is the
# fallback if that Timer never began, and must not start a second play if the
# Timer play already ended and the module was dropped (0.3.9: LAUNCH_DONE).
# On fake PWMs and the virtual clock test_ledtest.py uses: flame colour bounds
# (red/orange/yellow, builds then dies, flickers), the Wi-Fi pulse / green flash /
# timeout, once per boot including after the module is dropped, and the usual
# give-way, skip, and Timer path. Runs on CPython and MicroPython:
#   python3 tests/test_launch.py && micropython tests/test_launch.py  (from game/)
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
ENV = lvlaunch.envelope
AFTER = lvlaunch.after


def rgb(t):
    return (L(t, 0), L(t, 1), L(t, 2))


# -- 1. the flame itself
check("flame is 5-6 s", 5000 <= MS <= 6000, MS)
check("never out of range", all(0 <= L(t, k) <= 255 for t in range(0, MS, 3) for k in range(3)))
check("over at the end of the flame", L(MS - 1, 0) >= 0 and rgb(MS) == (-1, -1, -1) and L(MS + 500, 2) == -1 and L(-1, 0) == -1)
check("envelope: a dim ember at the start, 0 at the end", 8 <= ENV(0) <= 40 and ENV(MS - 1) >= 0 and ENV(MS) == -1)
# builds up, then dies down
es = [ENV(t) for t in range(0, MS, 20)]
peak_i = max(range(len(es)), key=lambda i: es[i])
check("envelope: builds, then dies", peak_i > 10 and peak_i < len(es) - 10 and es[peak_i] >= 200 and es[0] < es[peak_i] // 3 and es[-1] < es[peak_i] // 4, (peak_i, es[peak_i], es[-1]))
# red/orange/yellow family: red leads, blue is a spark only
samples = [rgb(t) for t in range(400, 5000, 40)]
check("flame: red leads, blue is a spark", all(r >= g and r >= b and b <= 40 for (r, g, b) in samples if r + g + b > 20), samples[::20])
check("flame: orange/yellow in the middle (green is up)", max(g for (r, g, b) in samples) >= 80)
# flicker: many levels, steps both ways, around a 40 ms step
mid = [rgb(t)[0] for t in range(2000, 3600, 20)]
check("flame: flickers (many red levels, steps both ways)",
      len(set(mid)) >= 8 and any(mid[i + 1] > mid[i] for i in range(len(mid) - 1)) and any(mid[i + 1] < mid[i] for i in range(len(mid) - 1)))
check("jitter 180-255", all(180 <= lvlaunch.jitter(t) <= 255 for t in range(0, 9000, 7)))
check("same 40 ms step, same jitter", lvlaunch.jitter(80) == lvlaunch.jitter(119))
# early is dimmer than the peak, late is dying
check("flame: early is dim, peak is bright, late is dying",
      sum(rgb(200)) < sum(rgb(3200)) and rgb(3200)[0] >= 150 and sum(rgb(5200)) < sum(rgb(3200)))
# Wi-Fi after-phase, as a pure function
check("after: no hotspot configured is already over", AFTER(0, 2) is None)
g0 = AFTER(0, 1)
g1 = AFTER(200, 1)
g2 = AFTER(300, 1)
check("after: two green flashes, dark between, then over",
      g0 == (0, 220, 40) and AFTER(150, 1) == (0, 0, 0) and g2 == (0, 220, 40) and AFTER(400, 1) is None, (g0, g1, g2))
b0 = AFTER(0, 0, 800)
b1 = AFTER(500, 0, 800)
check("after: blue breath (blue leads, not dark at the top)",
      b0[2] >= b0[1] >= b0[0] == 0 and b1[2] > b0[2] and b1[2] >= 200, (b0, b1))
check("after: timeout is two dim amber blinks, then over",
      AFTER(800, 0, 800) == (160, 40, 0) and AFTER(920, 0, 800) == (0, 0, 0) and AFTER(1040, 0, 800) == (160, 40, 0) and AFTER(1120, 0, 800) is None)
check("WIFI_WAIT is 30 s", lvlaunch.WIFI_WAIT == 30000)
# the Test light's curve, exactly, in small ints (the original v*v*sc*257 product, which
# CPython can compute, and both duty() functions since 0.3.5 split so it stays under 2**30)
def ref_duty(v, sc):
    if v <= 0:
        return 0
    d = v * v * sc * 257 // 25500
    return 65535 if d > 65535 else d
check("duty: lvrgb.duty's curve", all(D(v, s) == lvrgb.duty(v, s) == ref_duty(v, s) for v in range(-1, 256) for s in (1, 7, 40, 70, 99, 100)))
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
exec(src[src.index("# ---- the launch light"):src.index("\ndef no_setup")], g)
check("main.py: the launch starts from a peek before the boot window",
      0 < src.index("start_launch(peek_rgb())") < src.index("lvsetup.boot("))
check("main.py: ... and again before the hotspot if the peek missed it",
      0 < src.index("start_launch(cfg)") < src.index("lvsetup.prepare("))
check("main.py: the running play is attached to the ship before the event loop",
      0 < src.index("attach_launch(ship)") < src.index("asyncio.run(run())"))
check("main.py: run() still starts it before the web server if it hasn't yet",
      0 < src.index("launch(ship)  ") < src.index("web = lvweb.Server(ship"))
check("main.py: safe mode stops a play that had already begun",
      "stop_launch()\n        return safe_mode" in src)
check("main.py: a skipped boot (/data/safe or /data/maint) stops it too",
      "if setup is None:" in src[src.index("def main():"):] and
      "stop_launch()" in src[src.index("if setup is None:"):src.index("if setup[0] is None:")])
check("main.py: /data/safe and /data/maint never start it",
      'flag("/data/safe") or flag("/data/maint")' in src)
check("main.py: LAUNCH_DONE survives dropping the module", "LAUNCH_DONE" in src and "global LAUNCH_DONE" in src)
check("main.py: logs reset_cause at the start of main()",
      0 < src.index("_log_reset_cause()") < src.index("start_launch(peek_rgb())"))
check("main.py: tells the play when the hotspot is up, before the event loop",
      0 < src.index("tell_wifi(") < src.index("asyncio.run(run())") and "lvlaunch.wifi_up()" in src)
check("main.py: a soft reset of the same power cycle does not replay",
      "_is_soft()" in src and "LAUNCH_DONE = True" in src)
src = None
launch = g["launch"]
peek_rgb = g["peek_rgb"]
start_launch = g["start_launch"]
attach_launch = g["attach_launch"]
stop_launch = g["stop_launch"]


def fresh_boot():
    """A new process as far as the launch is concerned (tests, not a real reset)."""
    g["LAUNCH_DONE"] = False
    g["WIFI_HINT"] = 0


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
    # wifi_none(): just the flame, so settle() is ~5.6 s not a 30 s blue wait
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
    gaps = [0, 0, True]                 # the longest gap between ticker turns; running

    async def ticker():
        last = now()
        while gaps[2]:
            await lvship.sleep_ms(5)
            gaps[0] = max(gaps[0], diff(now(), last))
            last = now()
            gaps[1] += 1
    tt = asyncio.create_task(ticker())
    T0[0] = now()
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
    check("over in about 5.6 s", LMS - 20 <= end <= LMS + 100, end)
    check("ends dark: every duty 0, every PWM deinit'd", all_off(sh))
    check("the loop kept turning (no gap over 30 ms)", gaps[0] <= 30 and gaps[1] > 1000, gaps)
    for at in (80, 400, 1500, 2800, 3200, 4500, 5300):
        # the task's t is a frame or so behind T0: compare where the level holds still
        want = tuple(DU(LV(at, k), 100) for k in range(3))
        got = (held(r, at + 25), held(gr, at + 25), held(b, at + 25))
        ok_ = all(abs(got[k] - want[k]) <= max(8000, want[k] // 2 + 1) for k in range(3))
        check("held colour at %d ms" % at, ok_, (got, want))
    check("flame flickers: many red duty writes 2-4 s", len([1 for (t, d) in r if 2000 <= t < 4000]) >= 20)
    check("no error reached the loop", ERRS == [], ERRS)

    # a Test light tap meanwhile: never 429, it takes over; the launch's PWMs off first
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
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
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
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
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
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
    fresh_boot()
    launch(sh)
    await lvship.sleep_ms(200)
    check("update busy at the start: nothing made", sh.made == {})

    # a hail's flicker (or any playback mark) during the launch: gives way, mark untouched
    sh = Ship([16, 17, 18])
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
    launch(sh)
    await lvship.sleep_ms(1500)
    m = sh.ledtest = now()
    await lvship.sleep_ms(60)
    check("a playback mark stops it, all off, the mark left alone", all_off(sh) and sh.ledtest == m)
    sh = Ship([16, 17, 18])
    sh.ledtest = now()
    fresh_boot()
    launch(sh)
    await lvship.sleep_ms(200)
    check("a playback already running: no launch, nothing made", sh.made == {})

    # a PWM that fails mid-launch: ends, all off, said, nothing escapes
    sh = Ship([16, 17, 18])
    sh.fail_at = 15
    del SAID[:]
    fresh_boot()
    import lvlaunch as _L
    _L.wifi_none()
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
    fresh_boot()
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
    fresh_boot()
    launch(sh)
    check("broken module: launch() returns, said, dropped", any("no launch light" in x for x in SAID) and dropped(), SAID)
    sh = Ship([16, 17, 18])
    sh.cfg = None
    fresh_boot()
    launch(sh)
    check("launch(): a ship with no cfg returns quietly", sh.made == {})
    await lvship.sleep_ms(100)
    check("nothing ever reached the loop's error handler", ERRS == [], ERRS)



def reset_ll(LL):
    LL.stop()
    LL._played = False
    LL._pw = None
    LL._host = None
    LL._timer = None
    LL._was = None
    LL._sc = None
    LL._busy = False
    LL._END[:] = []
    LL._t0 = 0
    LL._wifi = 0
    LL._up_t = 0
    LL._tw = 0
    fresh_boot()
    # launch() / forget() drop the name; put this same module back so the next begin()
    # (and start_launch's import) is still the one with FakeTimer, not a fresh copy.
    sys.modules["lvlaunch"] = LL
    LL._make_timer = lambda: FakeTimer()


class FakeTimer:
    PERIODIC = 1

    def __init__(self, n=-1):
        self.cb = None
        self.dead = False
        self.period = None
        TIMERS.append(self)

    def init(self, mode=None, period=None, callback=None):
        self.mode, self.period, self.cb = mode, period, callback

    def deinit(self):
        self.dead = True
        self.cb = None

    def pulse(self):
        if self.cb:
            self.cb(self)


TIMERS = []


async def pump(ms):
    end = now() + max(0, int(ms))
    while now() < end:
        for tm in list(TIMERS):
            if tm.cb and not tm.dead:
                tm.pulse()
        await lvship.sleep_ms(20)


async def timer_case():
    # The 0.3.5 Timer path: begin() lights at once, plays on a pumped FakeTimer against
    # the same virtual clock, attach() hands the LED to the real ship, give-way and stop()
    # release the pins, and a second begin() this boot does not restart it.
    asyncio.get_event_loop().set_exception_handler(lambda loop, ctx: ERRS.append(ctx))
    import lvlaunch as LL
    del TIMERS[:]
    LL._make_timer = lambda: FakeTimer()
    reset_ll(LL)

    # no Timer: begin() is False, nothing made, start() can still schedule a play
    def no_tm():
        raise ImportError("no Timer")
    LL._make_timer = no_tm
    sh = Ship([16, 17, 18])
    r = LL.begin(sh.cfg, say=sh.say, host=sh)
    check("begin(): no Timer is False, nothing made, not played",
          r is False and sh.made == {} and LL.played() is False and LL.busy() is False)
    LL._make_timer = lambda: FakeTimer()

    # peek_rgb: only rgb_pins and rgb_scale, never the rest of the file
    path = HERE + "/tests/.launch-peek.json"
    with open(path, "w") as f:
        f.write('{"ship_id": 5, "rgb_pins": [16, 17, 18], "rgb_scale": [70, 80, 90],'
                ' "hotspot_password": "not-the-real-password", "fleet_key": "not-the-real-key"}')
    got = peek_rgb(path)
    check("peek_rgb: pins and scale only",
          got == {"rgb_pins": [16, 17, 18], "rgb_scale": [70, 80, 90]}, got)
    check("peek_rgb: the rest of the file is not in what it returns",
          "hotspot_password" not in got and "fleet_key" not in got and "not-the-real" not in str(got))
    check("peek_rgb: missing file is None", peek_rgb(path + ".gone") is None)
    with open(path, "w") as f:
        f.write("{")
    check("peek_rgb: damaged file is None", peek_rgb(path) is None)
    with open(path, "w") as f:
        f.write('{"ship_id": 5}')
    check("peek_rgb: no rgb_pins is None", peek_rgb(path) is None)
    try:
        os.remove(path)
    except OSError:
        pass

    # refused pins, already held, a playback already running
    sh = Ship([4, 5, 6])
    del SAID[:]
    check("begin(): refused pins is False, said why",
          LL.begin(sh.cfg, say=sh.say, host=sh) is False and sh.made == {} and any("rgb_pins" in x for x in SAID), SAID)
    sh = Ship([16, 17, 18])
    sh.rgb = object()
    check("begin(): rgb already held is False, nothing made",
          LL.begin(sh.cfg, say=sh.say, host=sh) is False and sh.made == {})
    sh = Ship([16, 17, 18])
    sh.ledtest = 1
    check("begin(): a playback already running is False, nothing made",
          LL.begin(sh.cfg, say=sh.say, host=sh) is False and sh.made == {})

    # the whole flame on the Timer, first frame at once, over at 5.6 s (no Wi-Fi wait)
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    T0[0] = now()
    r = LL.begin(sh.cfg, say=sh.say, host=sh)
    LL.wifi_none()
    check("begin(): True, busy, first frame already on the pins",
          r is True and LL.busy() and LL.played() and len(sh.made) == 3 and sh.made[16].duty > 0, (r, sh.made))
    check("begin(): never marks the light busy", sh.ledtest is None)
    check("begin(): the timer is 20 ms periodic", TIMERS and TIMERS[0].period == 20 and not TIMERS[0].dead)
    await pump(MS + 200)
    end = diff(now(), T0[0])
    check("Timer: over in about 5.6 s", MS - 20 <= end <= MS + 200, end)
    check("Timer: ends dark, every PWM deinit'd, timer deinit'd", all_off(sh) and TIMERS[0].dead)
    check("Timer: not busy, but played this boot", LL.busy() is False and LL.played() is True)
    r, gr, b = sh.made[16].log, sh.made[17].log, sh.made[18].log
    LV, DU = LL.level, LL.duty
    for at in (80, 400, 1500, 2800, 3200, 4500, 5300):
        want = tuple(DU(LV(at, k), 100) for k in range(3))
        got = (held(r, at + 25), held(gr, at + 25), held(b, at + 25))
        ok_ = all(abs(got[k] - want[k]) <= max(8000, want[k] // 2 + 1) for k in range(3))
        check("Timer: held colour at %d ms" % at, ok_, (got, want))
    check("Timer: no error reached the loop", ERRS == [], ERRS)

    # once a boot: a second begin() is False, launch() does not start an asyncio play
    sh2 = Ship([16, 17, 18])
    check("begin(): already played this boot is False", LL.begin(sh2.cfg, say=sh2.say, host=sh2) is False and sh2.made == {})
    launch(sh2)
    await lvship.sleep_ms(200)
    check("launch(): after a Timer play this boot, does not start again", sh2.made == {} and getattr(sh2, "rgb", None) is None)

    # attach: begin on a stub host, then the real ship holds sh.rgb
    reset_ll(LL)
    del TIMERS[:]
    stub_cfg = {"rgb_pins": [16, 17, 18]}
    # begin() without a host uses _Host; pins are made via cfg, but _pwm needs a factory.
    # Pass the ship as host first, then attach to the same ship (no-op), and to a new one.
    sh = Ship([16, 17, 18])
    T0[0] = now()
    check("begin() on the ship: True", LL.begin(sh.cfg, say=sh.say, host=sh) is True)
    check("attach() to the same ship is True", LL.attach(sh) is True and getattr(sh, "rgb", None) is not None)
    sh2 = Ship([16, 17, 18])
    sh2.rgb_pwm = sh.rgb_pwm
    check("attach() to a new ship moves sh.rgb",
          LL.attach(sh2) is True and getattr(sh, "rgb", None) is None and getattr(sh2, "rgb", None) is not None)
    await pump(100)
    check("after attach: still lit on the same PWMs", sh.made[16].duty > 0 and sh2.made == {})

    # give way after attach: a hail mark, then an update
    m = sh2.ledtest = now()
    await pump(40)
    check("Timer after attach: a playback mark stops it, all off, the mark left alone",
          all_off(sh) and sh2.ledtest == m and LL.busy() is False)

    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    start_launch(sh.cfg, say=sh.say, host=sh)
    check("start_launch(): busy, first frame on, module kept (attach still needs it)",
          LL.busy() and len(sh.made) == 3 and sh.made[16].duty > 0 and "lvlaunch" in sys.modules)
    attach_launch(sh)
    await pump(2000)
    check("start_launch + attach: still lit, never busy-marked", sh.made[16].duty > 0 and sh.ledtest is None)
    del SAID[:]
    srv.ota_busy = 1
    await pump(40)
    check("Timer after attach: an update stops it, every pin off", all_off(sh))
    check("... and said so", any("gave way" in x for x in SAID), SAID)

    # Test light takeover after attach (sh.rgb handover), test then plays
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    T0[0] = now()
    LL.begin(sh.cfg, say=sh.say, host=sh)
    LL.attach(sh)
    await pump(1500)
    old = dict(sh.made)
    check("Timer before the tap: lit", old[18].duty > 0)
    sh.made.clear()
    s, j = await ask(srv, Req("POST", "/api/led/test", "tok"))
    check("Test light during a Timer play: 200, the 18 s colour fade", s == 200 and j.get("rgb") is True, (s, j))
    await pump(40)
    # the test's task also needs the event loop; pump only fires FakeTimer, so give the
    # loop a few turns for the test to open its PWMs
    await lvship.sleep_ms(100)
    check("Timer takeover: the launch's PWMs off and deinit'd", all(p.dead and p.duty == 0 for p in old.values()))
    check("Timer takeover: the test plays on fresh PWMs", len(sh.made) == 3 and sh.made[16].duty > 0 and sh.made[16] is not old[16])
    check("Timer takeover: the launch is no longer busy (it did not switch the test off)",
          LL.busy() is False and not any(p.dead for p in sh.made.values()))
    t0 = now()
    while sh.ledtest is not None and diff(now(), t0) < 20000:
        await lvship.sleep_ms(20)
    w = diff(now(), t0)
    check("Timer takeover: the test runs its full 18 s", 17500 <= w <= 18200, w)
    check("Timer takeover: then all off", all_off(sh))

    # stop() releases pins mid-play; start_launch + stop_launch do the same
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    LL.begin(sh.cfg, say=sh.say, host=sh)
    await pump(500)
    check("stop() mid-play: all off, timer deinit'd, not busy", (LL.stop() or True) and all_off(sh) and TIMERS[0].dead and not LL.busy())
    # played stays True after stop of a begun play — once a boot
    check("stop(): still played this boot", LL.played() is True)
    reset_ll(LL)
    del TIMERS[:]
    g["LAUNCH_STOP"][:] = []
    sh = Ship([16, 17, 18])
    start_launch(sh.cfg, say=sh.say, host=sh)
    check("start_launch: LAUNCH_STOP holds a hook", len(g["LAUNCH_STOP"]) == 1, g["LAUNCH_STOP"])
    stop_launch()
    check("stop_launch(): all off, hooks cleared, modules dropped",
          all_off(sh) and g["LAUNCH_STOP"] == [] and dropped())

    # attach() with nothing playing is False; stop() with nothing playing does not raise
    check("attach(): nothing playing is False", LL.attach(sh) is False)
    LL.stop()
    check("stop(): nothing playing is fine", True)

    # Wi-Fi already up before the flame ends: green flashes, then dark, no blue wait
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    T0[0] = now()
    LL.begin(sh.cfg, say=sh.say, host=sh)
    LL.wifi_up()
    await pump(MS + 50)
    check("wifi already up: still in the flame just before it ends", LL.busy() and sh.made[16].duty >= 0)
    await pump(500)
    end = diff(now(), T0[0])
    check("wifi already up: over after the green flashes",
          not LL.busy() and all_off(sh) and MS + 350 <= end <= MS + 600, end)
    # a green duty was written after the flame
    greens = [d for (tt, d) in sh.made[17].log if tt >= MS]
    blues = [d for (tt, d) in sh.made[18].log if tt >= MS]
    check("wifi already up: a green flash, not a blue breath",
          greens and max(greens) > 0 and (not blues or max(greens) > max(blues)), (greens[:5], blues[:5]))

    # Wi-Fi comes up during the blue wait: pulse first, then green, then dark
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    T0[0] = now()
    LL.begin(sh.cfg, say=sh.say, host=sh)
    await pump(MS + 400)
    check("wifi wait: still busy after the flame, a blue breath",
          LL.busy() and sh.made[18].duty > sh.made[16].duty, (sh.made[16].duty, sh.made[18].duty))
    LL.wifi_up()
    await pump(500)
    check("wifi wait: green then dark once the hotspot is up", not LL.busy() and all_off(sh))
    after_b = [d for (tt, d) in sh.made[18].log if MS <= tt < MS + 400]
    check("wifi wait: it was pulsing blue before wifi_up", after_b and max(after_b) > 0, after_b[:8])

    # Hotspot never comes: 30 s is shortened for the test; two amber blinks, then dark
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    T0[0] = now()
    hold, LL.WIFI_WAIT = LL.WIFI_WAIT, 800
    try:
        LL.begin(sh.cfg, say=sh.say, host=sh)
        await pump(MS + 800 + 400)
        check("wifi timeout: ended after the wait and the amber blinks", not LL.busy() and all_off(sh))
        end = diff(now(), T0[0])
        check("wifi timeout: about the flame plus the wait", MS + 800 + 250 <= end <= MS + 800 + 500, end)
        ambers = [d for (tt, d) in sh.made[16].log if tt >= MS + 800]
        check("wifi timeout: a dim amber blink (red leads)", ambers and max(ambers) > 0, ambers[:6])
    finally:
        LL.WIFI_WAIT = hold

    # Regression (0.3.9): when the Timer play ends, start_launch's on_end drops
    # lvlaunch from sys.modules. run()'s launch() used to import a fresh module
    # with _played False and start the sequence again. LAUNCH_DONE must stop that.
    reset_ll(LL)
    del TIMERS[:]
    g["LAUNCH_STOP"][:] = []
    sh = Ship([16, 17, 18])
    T0[0] = now()
    start_launch(sh.cfg, say=sh.say, host=sh)
    LL.wifi_none()
    check("regression setup: Timer play running, module kept",
          LL.busy() and "lvlaunch" in sys.modules and g["LAUNCH_DONE"] is True)
    await pump(MS + 200)
    check("regression: play ended and start_launch dropped the module",
          dropped() and not LL.busy() and g["LAUNCH_DONE"] is True, (dropped(), LL.busy(), g["LAUNCH_DONE"]))
    sh2 = Ship([16, 17, 18])
    launch(sh2)
    await lvship.sleep_ms(200)
    check("regression: launch() after a dropped Timer play does not start again",
          sh2.made == {} and getattr(sh2, "rgb", None) is None)
    # and start_launch must not begin a new Timer play either
    start_launch(sh2.cfg, say=sh2.say, host=sh2)
    check("regression: start_launch after a dropped play does not begin again", sh2.made == {})

    # a soft reset of a chip already running: no play (same power cycle)
    fresh_boot()
    real_soft = g["_is_soft"]
    g["_is_soft"] = lambda: True
    try:
        sh = Ship([16, 17, 18])
        start_launch(sh.cfg, say=sh.say, host=sh)
        check("soft reset: start_launch does not begin, marks the boot done",
              sh.made == {} and g["LAUNCH_DONE"] is True)
        launch(sh)
        await lvship.sleep_ms(200)
        check("soft reset: launch() does not fall back to a second play", sh.made == {})
    finally:
        g["_is_soft"] = real_soft

    # a failing PWM on the Timer path: ended, said, nothing escapes
    reset_ll(LL)
    del TIMERS[:]
    sh = Ship([16, 17, 18])
    sh.fail_at = 2
    del SAID[:]
    LL.begin(sh.cfg, say=sh.say, host=sh)
    await pump(200)
    check("Timer failing PWM: ended, every PWM deinit'd", getattr(sh, "rgb", None) is None and all(p.dead for p in sh.made.values()))
    check("Timer failing PWM: said so", any("launch light stopped" in x for x in SAID), SAID)
    check("still no error reached the loop", ERRS == [], ERRS)

    LL = None
    sys.modules.pop("lvlaunch", None)
    sys.modules.pop("lvrgb", None)
    sys.modules.pop("lvlight", None)
    check("nothing ever reached the loop's error handler", ERRS == [], ERRS)


asyncio.run(on_vclock(ship_case))
asyncio.run(on_vclock(timer_case))
print("launch light test: %d checks ok" % ok[0])
