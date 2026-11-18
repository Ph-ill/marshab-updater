# The charge light (0.3.6, board/lvcharge.py): a slow breath on the RGB LED while the
# UPS-Lite's charger is plugged in, started by board/main.py's charge_light() from the
# charger watch. On fake PWMs and the virtual clock test_launch.py uses: start/stop on
# plug and unplug, colour by level (amber at low, yellow, green near full, a soft
# cyan-blue when the percent is unknown, a slower shallower green breath at 100%), pin
# cleanup, yielding to Test light / an update's upload / a hail's mark / a launch that
# holds sh.rgb and resuming after, skipped without rgb_pins and with refused ones, never
# marks the light busy, safe mode never starts the charger watch, a flapping pin is the
# watch's debounce, the Pico's USB (no plug-detect) stays dark. Runs on CPython and
# MicroPython:  python3 tests/test_chargelight.py && micropython tests/test_chargelight.py
# (from game/)
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
import lvcharge  # noqa: E402
import lvrgb  # noqa: E402
from lv.led import Notifier  # noqa: E402
from lv.clock import Clock  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


C, E, L, D = lvcharge.colour, lvcharge.env, lvcharge.level, lvrgb.duty
P, PF, PEAK = lvcharge.PERIOD, lvcharge.PERIOD_FULL, lvcharge.PEAK


# -- 1. the sequence itself
check("3 s breath, 8 s when full", P == 3000 and PF == 8000)
check("0.3.7 peak a bit brighter (110-120)", 110 <= PEAK <= 120, PEAK)
check("env: dark at the ends, full at mid", E(0, P) == 0 and E(P, P) == 0 and E(P // 2, P) == 100)
check("env: squared (dim stays dim)", E(P // 8, P) < 10 and E(P // 4, P) <= 26 and E(3 * P // 8, P) > E(P // 4, P))
up = [E(t, P) for t in range(0, P // 2 + 1, 20)]
dn = [E(t, P) for t in range(P // 2, P, 20)]
check("env: swells, then settles", up == sorted(up) and dn == sorted(dn, reverse=True))
check("env: full-breath mid is also 100", E(0, PF) == 0 and E(PF // 2, PF) == 100)
check("never out of range", all(0 <= L(t, k, pct) <= 255
                                for t in range(0, PF, 17)
                                for k in range(3)
                                for pct in (None, 0, 15, 40, 70, 95, 100)))
# colours: amber/orange at low, through yellow, to green; unknown is cyan-blue
lo = (C(0, 0), C(0, 1), C(0, 2))
mid = (C(50, 0), C(50, 1), C(50, 2))
hi = (C(90, 0), C(90, 1), C(90, 2))
fullc = (C(100, 0), C(100, 1), C(100, 2))
unk = (C(None, 0), C(None, 1), C(None, 2))
check("low: amber/orange (red, some green, no blue)", lo[0] >= 200 and 40 <= lo[1] <= 140 and lo[2] == 0, lo)
check("mid: yellow (red and more green, no blue)", mid[0] >= 200 and mid[1] > lo[1] and mid[2] == 0, mid)
check("near full: green dominates", hi[1] > hi[0] and hi[1] > hi[2], hi)
check("full colour: green, little or no red", fullc[1] >= 150 and fullc[0] < 40, fullc)
check("unknown: soft cyan-blue, no red", unk[0] == 0 and unk[2] > unk[1] > 0, unk)
check("colour moves with the percent", C(10, 1) <= C(30, 1) <= C(60, 1))
# at mid-breath, a low percent is warmer than a high one; full is dimmer than charging
# at the same green
mid_lo = (L(P // 2, 0, 0), L(P // 2, 1, 0), L(P // 2, 2, 0))
mid_hi = (L(P // 2, 0, 90), L(P // 2, 1, 90), L(P // 2, 2, 90))
mid_full = (L(PF // 2, 0, 100), L(PF // 2, 1, 100), L(PF // 2, 2, 100))
mid_unk = (L(P // 2, 0, None), L(P // 2, 1, None), L(P // 2, 2, None))
check("charging peak uses the colour and stays under PEAK", mid_lo[0] == PEAK and mid_lo[2] == 0 and mid_lo[0] > mid_lo[1], mid_lo)
check("near-full peak is greener, still subtle", mid_hi[1] > mid_hi[0] and mid_hi[1] <= PEAK, mid_hi)
check("full peak is a dimmer green than charging", 0 < mid_full[1] < mid_hi[1] and mid_full[0] <= mid_full[2] <= mid_full[1], (mid_full, mid_hi))
check("unknown peak is cyan-blue, subtle", mid_unk[0] == 0 and mid_unk[2] > mid_unk[1] > 0 and mid_unk[2] <= PEAK, mid_unk)
check("full and charging envelopes differ in period", L(3000, 1, 80) == 0 and L(3000, 1, 100) > 0)
# duty: the Test/launch small-int split, products under 2**30
def ref_duty(v, sc):
    if v <= 0:
        return 0
    d = v * v * sc * 257 // 25500
    return 65535 if d > 65535 else d
check("duty: lvrgb.duty's curve", all(lvcharge.duty(v, s) == lvrgb.duty(v, s) == ref_duty(v, s)
                                      for v in range(-1, 256) for s in (1, 7, 40, 70, 99, 100)))
check("duty: products stay small ints", 255 * 255 * 100 < 1 << 30 and 25499 * 257 < 1 << 30)
check("level products stay small ints", 255 * PEAK * 100 < 1 << 30 and 255 * (lvcharge.FULL_BASE + lvcharge.FULL_SWING) < 1 << 30)
sys.modules.pop("lvcharge", None)
sys.modules.pop("lvrgb", None)
sys.modules.pop("lvlight", None)
del lvcharge, lvrgb


# -- 2. on the ship
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

    def value(self, v=None):
        if v is None:
            return 0
        self.log.append(v)


class Ship:
    def __init__(self, pins, chg=False, pct=40, **cfg):
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
        self.bat = [pct, 3900, chg, (pct or 0) * 256, 3900, 0, 0, 60000, 50]

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
        self.ota_busy = 0

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
# the charger slice now also defines charge_light(); the launch slice is between
# that and main(), and is not needed here except to prove safe mode never starts it
g = {"lvship": lvship, "asyncio": asyncio, "print": lambda *a: SAID.append(" ".join([str(x) for x in a]))}
exec(src[src.index("# ---- the charger line"):src.index("\ndef main():")], g)
exec(src[src.index("def http_admission"):src.index("\nasync def ota_ok")], g)
check("main.py: charge_light is only started from the charger watch",
      src.index("def charge_light") > src.index("# ---- the charger line") and
      src.index("charge_light(ship)") > src.index("async def charger_watch") and
      src.index("charge_light(ship, v)") > src.index("async def charger_watch") and
      src.count("charge_light(") == 5)  # comment, def, boot, unplug/none, flip
check("main.py: the charger watch (and so the light) starts only in run(), when the battery is present",
      "if ship.bat:" in src[src.index("async def run():"):] and
      "charger_watch(ship)" in src[src.index("if ship.bat:"):src.index("await ship.loop()")])
check("main.py: safe mode returns before run(), so the watch never starts",
      "return safe_mode" in src[src.index("def main():"):src.index("async def run():")] and
      src.index("async def run():") > src.index("return safe_mode(setup[1], setup[2])"))
check("main.py: /data/safe and /data/maint never reach run() either",
      "if setup is None:" in src[src.index("def main():"):] and
      "return" in src[src.index("if setup is None:"):src.index("if setup[0] is None:")])
src = None
charge_light = g["charge_light"]
charger_watch = g["charger_watch"]
Debounce, STEADY, EVERY, GAUGE = g["Debounce"], g["CHG_STEADY_MS"], g["CHG_EVERY_MS"], g["CHG_GAUGE_MS"]


def hook(ship):
    srv = Server(ship)
    g["ota_hooks"](FakeLvweb, srv)
    return srv


async def ask(srv, req):
    w = Wr()
    await srv.route(req, w)
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)


def all_off(sh, n=3):
    return len(sh.made) == n and all(p.dead and p.duty == 0 for p in sh.made.values()) and getattr(sh, "rgb", None) is None


def lit(sh):
    return any(not p.dead and p.duty > 0 for p in sh.made.values())


class VClock:
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


async def halt(sh=None):
    import lvcharge as LC
    LC.stop(sh, halt=True)
    t = now()
    while LC.busy() and diff(now(), t) < 500:
        await lvship.sleep_ms(10)
    check("halted", not LC.busy())


async def wait_lit(sh, cap=800):
    t = now()
    while not lit(sh) and diff(now(), t) < cap:
        await lvship.sleep_ms(10)
    return lit(sh)


async def wait_off(sh, cap=800):
    t = now()
    while not all_off(sh) and getattr(sh, "rgb", None) is not None and diff(now(), t) < cap:
        await lvship.sleep_ms(10)
    return all_off(sh) or getattr(sh, "rgb", None) is None and all(p.dead and p.duty == 0 for p in sh.made.values())


async def ship_case():
    asyncio.get_event_loop().set_exception_handler(lambda loop, ctx: ERRS.append(ctx))
    import lvcharge as LC
    import lvrgb as RGB
    LV = LC.level

    # no rgb_pins (absent or null): charge_light never loads the module, nothing made
    for v in ("absent", None):
        sys.modules.pop("lvcharge", None)
        sh = Ship(v, chg=True)
        del SAID[:]
        charge_light(sh)
        await lvship.sleep_ms(200)
        check("no rgb_pins %r: lvcharge never loaded" % (v,),
              "lvcharge" not in sys.modules and sh.made == {} and SAID == [] and getattr(sh, "rgb", None) is None,
              (SAID, sh.made, list(sys.modules)))

    # reimport after the pop
    import lvcharge as LC
    import lvrgb as RGB
    LV = LC.level

    # refused pins (the battery's): said, nothing made
    sh = Ship([4, 5, 6], chg=True)
    del SAID[:]
    check("refused pins: start is False", LC.start(sh) is False)
    await lvship.sleep_ms(200)
    check("refused pins: nothing made, said why", sh.made == {} and any("rgb_pins" in x for x in SAID), SAID)

    # not charging: start is False, nothing made
    sh = Ship([16, 17, 18], chg=False, pct=40)
    check("unplugged: start is False", LC.start(sh) is False and sh.made == {} and not LC.busy())

    # already plugged in: the boot path (charge_light with no `on`) starts a breath
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    T0[0] = now()
    check("plugged in: charge_light starts it", charge_light(sh) is None and LC.busy())
    check("never marks the light busy", sh.ledtest is None)
    check("came on", await wait_lit(sh), sh.made)
    # mid-breath (~1.5 s) should be amber-ish for 40%
    await lvship.sleep_ms(1500)
    check("still never busy-marked while playing", sh.ledtest is None)
    check("lit mid-breath at 40%", lit(sh) and sh.made[16].duty > 0, {n: sh.made[n].duty for n in sh.made})
    # red should outrank blue at 40% (amber/yellow)
    check("40% is warm (red duty > blue)", sh.made[16].duty > sh.made[18].duty, {n: sh.made[n].duty for n in sh.made})
    # the event loop keeps turning
    gaps = [0, 0, True]
    async def ticker():
        last = now()
        while gaps[2]:
            await lvship.sleep_ms(1)
            d = now() - last
            if d > gaps[0]:
                gaps[0] = d
            gaps[1] += 1
            last = now()
    tk = asyncio.create_task(ticker())
    await lvship.sleep_ms(200)
    gaps[2] = False
    await tk
    check("the loop keeps turning during a breath", gaps[1] >= 100 and gaps[0] <= 80, gaps)

    # unplug: goes dark, pins released; the task parks
    sh.bat[2] = False
    charge_light(sh, False)
    check("unplug: dark and pins released", await wait_off(sh), [(p.dead, p.duty) for p in sh.made.values()])
    check("unplug: not holding rgb", getattr(sh, "rgb", None) is None)
    parked = LC.busy()
    check("unplug: the task parks (still one task)", parked)
    # stay dark while unplugged
    await lvship.sleep_ms(400)
    check("stays dark while unplugged", all_off(sh) and sh.ledtest is None)

    # plug in again: same task resumes, a new breath from dark
    old = dict(sh.made)
    sh.bat[2] = True
    T0[0] = now()
    charge_light(sh, True)
    check("replug: came back", await wait_lit(sh))
    check("replug: fresh PWMs (old ones stayed off)", all(p.dead and p.duty == 0 for p in old.values()) and lit(sh))
    await halt(sh)
    check("halt: all off", all_off(sh))

    # percent None: cyan-blue; 100%: dimmer green, slower
    sh = Ship([16, 17, 18], chg=True, pct=None)
    sh.bat[0] = None
    T0[0] = now()
    LC.start(sh)
    check("unknown percent: came on", await wait_lit(sh))
    await lvship.sleep_ms(1500)
    check("unknown percent: blue outranks red", sh.made[18].duty > sh.made[16].duty, {n: sh.made[n].duty for n in sh.made})
    # climb to 100%
    sh.bat[0] = 100
    T0[0] = now()  # the play's t0 is from PWM open, not this; just wait a full-breath mid
    # give it a moment to take the new colour (same open, t continues)
    await lvship.sleep_ms(4000)  # mid of an 8 s full breath only if t0 was reset; it wasn't
    # so just check the level function mapping is what play would write: green dim
    # Force a resume (re-open, new t0) by parking and unparking
    sh.ledtest = now()
    t = now()
    while getattr(sh, "rgb", None) is not None and diff(now(), t) < 400:
        await lvship.sleep_ms(10)
    sh.ledtest = None
    T0[0] = now()
    check("full: resumed after a brief yield", await wait_lit(sh))
    await lvship.sleep_ms(4000)
    check("full: green is lit, red is off or nearly", sh.made[17].duty > 0 and sh.made[16].duty == 0,
          {n: sh.made[n].duty for n in sh.made})
    # shallower than a charging 90% mid-breath would be
    mid90 = RGB.duty(LV(1500, 1, 90), 100)
    check("full: dimmer than a charging near-full peak", sh.made[17].duty < mid90, (sh.made[17].duty, mid90))
    await halt(sh)

    # -- priority: Test light takes over, charge parks, then resumes
    sh = Ship([16, 17, 18], chg=True, pct=40)
    srv = hook(sh)
    T0[0] = now()
    LC.start(sh)
    check("before the tap: lit", await wait_lit(sh))
    old = dict(sh.made)
    # a signed-in Test light tap
    import lvledtest
    s, j = lvledtest.start(srv, Req("POST", "/api/led/test", tok="tok"))
    check("Test light starts (not 429)", s == 200 and j.get("rgb") is True, (s, j))
    # create_task only schedules play(); wait for _open to take the LED over
    t = now()
    while not (all(p.dead and p.duty == 0 for p in old.values()) and
               len(sh.made) == 3 and sh.made[16] not in old.values() and sh.made[16].duty > 0) and diff(now(), t) < 800:
        await lvship.sleep_ms(10)
    check("Test light: the charge light's PWMs off and deinit'd",
          all(p.dead and p.duty == 0 for p in old.values()), [(p.dead, p.duty) for p in old.values()])
    check("Test light plays on fresh PWMs", len(sh.made) == 3 and sh.made[16].duty > 0 and sh.made[16] not in old.values(),
          (len(sh.made), sh.made[16].duty if 16 in sh.made else None))
    check("charge light parked, not holding rgb", LC.busy() and getattr(sh, "rgb", None) is not old.get(16) and sh.ledtest is not None)
    # let the 18 s test finish (or clear the mark and cancel by setting ledtest over)
    # run long enough? 18 s on the virtual clock is a lot but test_launch does it.
    # Faster: jump the test to its end by advancing until ledtest clears, with a cap.
    t = now()
    while sh.ledtest is not None and diff(now(), t) < 20000:
        await lvship.sleep_ms(50)
    check("Test light ended", sh.ledtest is None, sh.ledtest)
    check("charge light resumes after Test light", await wait_lit(sh))
    check("resume: still not busy-marked", sh.ledtest is None)
    await halt(sh)

    # -- an update's upload: parks dark, then resumes
    sh = Ship([16, 17, 18], chg=True, pct=40)
    srv = hook(sh)
    T0[0] = now()
    LC.start(sh)
    check("before an update: lit", await wait_lit(sh))
    old = dict(sh.made)
    srv.ota_busy = 1
    check("an update parks it, every pin off", await wait_off(sh) or all(p.dead and p.duty == 0 for p in old.values()))
    check("ota: pins released", getattr(sh, "rgb", None) is None)
    await lvship.sleep_ms(200)
    check("ota: stays dark while the upload runs", getattr(sh, "rgb", None) is None)
    srv.ota_busy = 0
    check("resumes after the update", await wait_lit(sh))
    # 0.3.7: an update's glow (sh.otaled) also parks it, including between pieces
    # when ota_busy is 0, and it resumes when the glow ends
    sh.otaled = "recv"
    check("an update's glow parks it", await wait_off(sh) or (getattr(sh, "rgb", None) is None and all(p.dead and p.duty == 0 for p in sh.made.values())))
    sh.otaled = None
    check("resumes after the update's glow", await wait_lit(sh))
    await halt(sh)

    # -- a hail's mark (sh.ledtest) parks it, then resumes
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    T0[0] = now()
    LC.start(sh)
    check("before a hail: lit", await wait_lit(sh))
    sh.ledtest = now()
    sh.ledtest_ms = 10000
    sh.ledhail = sh.ledtest
    check("a hail parks it, pins off", await wait_off(sh) or (getattr(sh, "rgb", None) is None and all(p.dead and p.duty == 0 for p in sh.made.values())))
    sh.ledtest = None
    sh.ledhail = None
    check("resumes after the hail", await wait_lit(sh))
    await halt(sh)

    # -- a launch holding sh.rgb: charge light must not _open (would kill the launch)
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    # pretend a launch already holds the LED
    launch_pw = []
    for n in (16, 17, 18):
        p = sh.rgb_pwm(n)
        p.duty_u16(1000)
        launch_pw.append((n, p))
    sh.rgb = launch_pw
    held_ids = {id(p) for p in sh.made.values()}
    LC.start(sh)
    await lvship.sleep_ms(300)
    check("launch holds the LED: charge light does not take it",
          getattr(sh, "rgb", None) is launch_pw and all(id(p) in held_ids for p in sh.made.values())
          and all(not p.dead and p.duty == 1000 for p in sh.made.values()),
          [(p.dead, p.duty) for p in sh.made.values()])
    # launch ends
    for n, p in launch_pw:
        p.duty_u16(0)
        p.deinit()
    sh.rgb = None
    check("resumes after the launch", await wait_lit(sh))
    await halt(sh)

    # -- bat goes (None): goes dark
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    LC.start(sh)
    check("before bat None: lit", await wait_lit(sh))
    sh.bat = None
    charge_light(sh, False)
    check("bat None: dark", await wait_off(sh) or (getattr(sh, "rgb", None) is None and all(p.dead and p.duty == 0 for p in sh.made.values())))
    await halt(sh)

    # -- start twice: one task
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    check("start once", LC.start(sh) is True)
    t1 = LC._task
    check("start twice: still the same task", LC.start(sh) is True and LC._task is t1)
    await wait_lit(sh)
    await halt(sh)

    # -- a failing PWM: nothing escapes, pins released
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    sh.fail_at = 0  # first duty write fails; _open sets duty 0 first
    # fail_at 0 fails the first write, which is _open's duty_u16(0) — _open should clean up
    del SAID[:]
    r = LC.start(sh)
    await lvship.sleep_ms(400)
    check("a failing PWM never escapes", ERRS == [], ERRS)
    # either start failed or play stopped and said; pins not left driven
    if sh.made:
        check("a failing PWM: nothing left driven", all(p.dead or p.duty == 0 for p in sh.made.values()) and getattr(sh, "rgb", None) is None,
              [(p.dead, p.duty) for p in sh.made.values()])
    await halt(sh)

    # -- charger_watch integration: a steady plug starts it, a loose plug doesn't,
    #    a steady unplug stops it. USB-present-without-UPS is just unplugged (rd False).
    sh = Ship([16, 17, 18], chg=False, pct=40)
    hook(sh)

    class Rd:
        def __init__(self, v=False):
            self.v = v
            self.fail = False
            self.reads = 0

        def __call__(self):
            self.reads += 1
            if self.fail:
                raise OSError(5)
            return self.v

    rd = Rd(False)
    stopped = [False]
    script = []
    t_origin = [None]

    def at(ms, fn):
        script.append((ms, fn))

    async def run_watch(ms):
        t_origin[0] = now()
        todo = list(script)

        def stop():
            while todo and now() - t_origin[0] >= todo[0][0]:
                todo.pop(0)[1]()
            return now() - t_origin[0] >= ms
        await charger_watch(sh, rd, stop=stop)

    # unplugged the whole time: never starts, and lvcharge is not loaded just to stop
    sys.modules.pop("lvcharge", None)
    await run_watch(500)
    check("watch, unplugged: no light", sh.made == {} and getattr(sh, "rgb", None) is None)
    check("watch, unplugged: lvcharge never loaded", "lvcharge" not in sys.modules)
    import lvcharge as LC

    # a loose plug: flips every 100 ms (in step with the watch), never held 300 ms,
    # then a steady unplug. The script is applied when the watch next looks, so
    # a flip at t is what the following 100 ms read sees.
    sh = Ship([16, 17, 18], chg=False, pct=40)
    hook(sh)
    rd = Rd(False)
    script[:] = []
    for i, k in enumerate(range(0, 1200, 100)):
        at(k, (lambda v: lambda: setattr(rd, "v", v))(i % 2 == 1))
    at(1200, lambda: setattr(rd, "v", False))
    await run_watch(1800)
    check("a loose plug: never taken, no light", sh.bat[2] is False and sh.made == {} and getattr(sh, "rgb", None) is None, (sh.bat, sh.made))

    # a steady plug: taken after ~300 ms, the light comes on; unplug, it goes dark
    sh = Ship([16, 17, 18], chg=False, pct=55)
    hook(sh)
    rd = Rd(False)
    script[:] = []
    at(200, lambda: setattr(rd, "v", True))
    at(200 + STEADY + EVERY + 800, lambda: setattr(rd, "v", False))
    # run long enough for plug (300 ms), light, then unplug + 300 ms + settle
    t_origin[0] = now()
    todo = list(script)
    saw = []

    def stop():
        while todo and now() - t_origin[0] >= todo[0][0]:
            todo.pop(0)[1]()
        saw.append((now() - t_origin[0], sh.bat[2], lit(sh) if sh.made else False, getattr(sh, "rgb", None) is not None))
        return now() - t_origin[0] >= 2000
    await charger_watch(sh, rd, stop=stop)
    plugged = [s for s in saw if s[1] is True]
    check("steady plug: bat[2] taken", sh.bat[2] is False)  # ended unplugged
    check("steady plug: the light came on after it held", any(s[2] or s[3] for s in plugged), plugged[:5])
    check("steady unplug: dark at the end", getattr(sh, "rgb", None) is None and (not sh.made or all(p.dead and p.duty == 0 for p in sh.made.values())))
    await halt(sh)

    # USB power without the UPS charger: the pin stays False, no light
    sh = Ship([16, 17, 18], chg=False, pct=40)
    hook(sh)
    rd = Rd(False)  # Pico USB does not assert the UPS-Lite plug line
    script[:] = []
    await run_watch(600)
    check("USB only (no UPS charger): no light", sh.made == {} and sh.bat[2] is False and getattr(sh, "rgb", None) is None)

    check("no leaked exception handler entries", ERRS == [], ERRS)
    # one last halt in case anything is still running
    import lvcharge as LC
    await halt(None)


asyncio.run(on_vclock(ship_case))
print("chargelight: %d checks ok" % ok[0])
