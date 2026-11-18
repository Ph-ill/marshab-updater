# The update light (0.3.7, board/lvotaled.py): a violet-blue pulse while an over-the-air
# update is arriving, then a slower pale white-blue breath once apply() has handed it to
# lvboot. On fake PWMs and the virtual clock test_chargelight.py uses: start/stop, the
# recv and apply sequences, a 403 or a cancel going dark, priority over the charge light,
# Test light 429 while it plays, no ledtest mark, skipped without rgb_pins, pin cleanup,
# a stale recv with no piece going dark, and main.py / lvotap / lvota hooks. Runs on
# CPython and MicroPython:
#   python3 tests/test_otaled.py && micropython tests/test_otaled.py  (from game/)
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
import lvotaled  # noqa: E402
import lvrgb  # noqa: E402
from lv.led import Notifier  # noqa: E402
from lv.clock import Clock  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


E, L, D = lvotaled.env, lvotaled.level, lvrgb.duty
PR, PA, PEAK = lvotaled.PERIOD_RECV, lvotaled.PERIOD_APPLY, lvotaled.PEAK_RECV


# -- 1. the sequence itself
check("1 s recv pulse, ~2.8 s apply breath", PR == 1000 and PA == 2800)
check("recv peak visible", 100 <= PEAK <= 180, PEAK)
check("apply never goes fully dark", L(0, 2, "apply") > 0 and L(PA // 2, 2, "apply") > L(0, 2, "apply"))
check("env: dark at the ends, full at mid", E(0, PR) == 0 and E(PR, PR) == 0 and E(PR // 2, PR) == 100)
check("never out of range", all(0 <= L(t, k, ph) <= 255
                                for t in range(0, PA, 17)
                                for k in range(3)
                                for ph in ("recv", "apply")))
# recv: violet-blue (blue most, some red, no green); apply: pale white-blue
mid_r = (L(PR // 2, 0, "recv"), L(PR // 2, 1, "recv"), L(PR // 2, 2, "recv"))
mid_a = (L(PA // 2, 0, "apply"), L(PA // 2, 1, "apply"), L(PA // 2, 2, "apply"))
lo_a = (L(0, 0, "apply"), L(0, 1, "apply"), L(0, 2, "apply"))
check("recv mid: violet-blue", mid_r[2] > mid_r[0] > mid_r[1] == 0 and mid_r[2] == PEAK, mid_r)
check("apply mid: pale white-blue, all channels", min(mid_a) > 0 and mid_a[2] >= mid_a[1] >= mid_a[0], mid_a)
check("apply floor is lit", min(lo_a) >= 0 and lo_a[2] > 0 and lo_a[2] < mid_a[2], (lo_a, mid_a))
check("recv is faster than apply (dark at 1 s, apply still mid-cycle)", L(1000, 2, "recv") == 0 and L(1000, 2, "apply") > 0)
def ref_duty(v, sc):
    if v <= 0:
        return 0
    d = v * v * sc * 257 // 25500
    return 65535 if d > 65535 else d
check("duty: lvrgb.duty's curve", all(lvotaled.duty(v, s) == lvrgb.duty(v, s) == ref_duty(v, s)
                                      for v in range(-1, 256) for s in (1, 40, 100)))
check("products stay small ints", 255 * PEAK * 100 < 1 << 30 and 255 * (lvotaled.APPLY_BASE + lvotaled.APPLY_SWING) < 1 << 30)
sys.modules.pop("lvotaled", None)
sys.modules.pop("lvrgb", None)
sys.modules.pop("lvlight", None)
del lvotaled, lvrgb


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
        self.otaled = None
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
g = {"lvship": lvship, "asyncio": asyncio, "print": lambda *a: SAID.append(" ".join([str(x) for x in a]))}
exec(src[src.index("# ---- the charger line"):src.index("\ndef main():")], g)
exec(src[src.index("def http_admission"):src.index("\nasync def ota_ok")], g)
check("main.py: update_light is defined next to the charger hooks", "def update_light" in src)
check("main.py: mid-upload pieces start the recv glow", 'update_light(web.ship, "recv")' in src)
check("main.py: the last envelope piece does not start it before the signature check",
      "last_env" in src and src.index("if not last_env:") < src.index("import lvotaq"))
check("main.py: a Test light tap during an update is 429",
      '"The ship is updating."' in src and '"kind": "update"' in src)
ota_src = open(HERE + "/board/lvota.py").read()
otap_src = open(HERE + "/board/lvotap.py").read()
api = ota_src[ota_src.index("async def api"):]
apply_part = api[api.index("/api/ota/apply"):]
cancel_part = api[api.index("/api/ota/cancel"):api.index("/api/ota/apply")]
check("lvota: apply 200 starts the apply glow, apply 403 and cancel 200 go dark",
      '_led(web, "apply")' in apply_part
      and apply_part.index('_led(web, "apply")') < apply_part.index("return restart(web)")
      and "code == 403" in apply_part
      and apply_part.index("code == 403") < apply_part.index('_led(web, None)')
      and '_led(web, None)' in cancel_part)
check("lvotap: a 200 piece keeps the recv glow, a 403 goes dark",
      '_led(web, "recv")' in otap_src and '_led(web, None)' in otap_src)
update_light = g["update_light"]
hook_ota = g["ota_hooks"]


def hook(ship):
    srv = Server(ship)
    hook_ota(FakeLvweb, srv)
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
    import lvotaled as UL
    UL.stop(sh, halt=True)
    t = now()
    while UL.busy() and diff(now(), t) < 500:
        await lvship.sleep_ms(10)
    check("halted", not UL.busy())


async def wait_lit(sh, cap=800):
    t = now()
    while not lit(sh) and diff(now(), t) < cap:
        await lvship.sleep_ms(10)
    return lit(sh)


async def wait_off(sh, cap=800):
    t = now()
    while getattr(sh, "rgb", None) is not None and diff(now(), t) < cap:
        await lvship.sleep_ms(10)
    return getattr(sh, "rgb", None) is None and (not sh.made or all(p.dead and p.duty == 0 for p in sh.made.values()))


async def ship_case():
    asyncio.get_event_loop().set_exception_handler(lambda loop, ctx: ERRS.append(ctx))
    import lvotaled as UL
    import lvledtest
    import lvcharge as LC

    # no rgb_pins: hook never loads the module (after a pop), nothing made
    for v in ("absent", None):
        sys.modules.pop("lvotaled", None)
        sh = Ship(v)
        del SAID[:]
        update_light(sh, "recv")
        await lvship.sleep_ms(200)
        check("no rgb_pins %r: lvotaled never loaded" % (v,),
              "lvotaled" not in sys.modules and sh.made == {} and getattr(sh, "otaled", None) is None,
              (sh.made, list(sys.modules)))
    import lvotaled as UL

    # refused pins
    sh = Ship([4, 5, 6])
    del SAID[:]
    check("refused pins: start is False", UL.start(sh, "recv") is False)
    await lvship.sleep_ms(200)
    check("refused pins: nothing made, not marked", sh.made == {} and sh.otaled is None and any("rgb_pins" in x for x in SAID), SAID)

    # recv play, never busy-marked as a test
    sh = Ship([16, 17, 18])
    hook(sh)
    T0[0] = now()
    check("recv starts", UL.start(sh, "recv") is True and UL.busy())
    check("marked otaled recv, never ledtest", sh.otaled == "recv" and sh.ledtest is None)
    check("recv came on", await wait_lit(sh))
    await lvship.sleep_ms(500)
    check("recv mid: blue duty is highest", sh.made[18].duty > sh.made[16].duty and sh.made[17].duty == 0,
          {n: sh.made[n].duty for n in sh.made})
    check("still never ledtest", sh.ledtest is None)

    # phase change to apply: still holding, colour becomes paler (green comes up)
    T0[0] = now()
    check("apply starts on the same task", UL.start(sh, "apply") is True and sh.otaled == "apply")
    await lvship.sleep_ms(200)
    check("apply: still lit, green now on (white-blue)", lit(sh) and sh.made[17].duty > 0 and sh.made[18].duty > 0,
          {n: sh.made[n].duty for n in sh.made})
    await halt(sh)
    check("halt: all off, otaled cleared", all_off(sh) and sh.otaled is None)

    # stop (not halt) goes dark and unmarks; a later start resumes
    sh = Ship([16, 17, 18])
    hook(sh)
    UL.start(sh, "recv")
    check("before stop: lit", await wait_lit(sh) and sh.otaled == "recv")
    update_light(sh, None)
    check("stop: dark and unmarked", await wait_off(sh) and sh.otaled is None)
    UL.start(sh, "recv")
    check("start after stop: back", await wait_lit(sh) and sh.otaled == "recv")
    await halt(sh)

    # priority over the charge light
    sh = Ship([16, 17, 18], chg=True, pct=40)
    hook(sh)
    check("charge first", LC.start(sh) is True)
    check("charge was lit", await wait_lit(sh))
    old = dict(sh.made)
    UL.start(sh, "recv")
    t = now()
    while not (all(p.dead and p.duty == 0 for p in old.values()) and
               16 in sh.made and sh.made[16] not in old.values()) and diff(now(), t) < 800:
        await lvship.sleep_ms(10)
    check("update takes the LED: charge PWMs off", all(p.dead and p.duty == 0 for p in old.values()),
          [(p.dead, p.duty) for p in old.values()])
    # recv starts dark at t=0 of the pulse; wait for the first visible frame
    check("update plays on fresh PWMs", await wait_lit(sh) and sh.made[16] not in old.values() and sh.otaled == "recv")
    check("charge task parked, not holding rgb", LC.busy() and getattr(sh, "rgb", None) is not None)
    await halt(sh)
    # charge should be able to resume (otaled cleared)
    check("charge resumes after the update light ends", await wait_lit(sh))
    LC.stop(sh, halt=True)
    t = now()
    while LC.busy() and diff(now(), t) < 500:
        await lvship.sleep_ms(10)

    # Test light 429 while updating
    sh = Ship([16, 17, 18])
    srv = hook(sh)
    UL.start(sh, "recv")
    check("before Test light: lit", await wait_lit(sh))
    s, j = lvledtest.start(srv, Req("POST", "/api/led/test", tok="tok"))
    check("Test light 429 during an update", s == 429 and j.get("kind") == "update", (s, j))
    check("Test light did not take the LED", sh.otaled == "recv" and sh.ledtest is None and lit(sh))
    # main.py's route should say the same
    c, body = await ask(srv, Req("POST", "/api/led/test", tok="tok"))
    check("main.py route: 429 update", c == 429 and body.get("kind") == "update", (c, body))
    await halt(sh)

    # hook 403 / cancel go dark (via update_light)
    sh = Ship([16, 17, 18])
    hook(sh)
    update_light(sh, "recv")
    check("hook recv: lit", await wait_lit(sh))
    update_light(sh, None)
    check("hook stop (cancel / 403): dark", await wait_off(sh) and sh.otaled is None)
    await halt(sh)

    # stale recv: no poke for STALE_MS, goes dark
    sh = Ship([16, 17, 18])
    hook(sh)
    UL.start(sh, "recv")
    check("before stale: lit", await wait_lit(sh))
    UL._poke = now() - (UL.STALE_MS + 10)
    check("stale recv: goes dark", await wait_off(sh, cap=400) and sh.otaled is None)
    await halt(sh)

    # apply with no poke for APPLY_STALE_MS also goes dark (stuck apply, no restart)
    sh = Ship([16, 17, 18])
    hook(sh)
    UL.start(sh, "apply")
    check("before apply stale: lit", await wait_lit(sh))
    UL._poke = now() - (UL.APPLY_STALE_MS + 10)
    check("stale apply: goes dark", await wait_off(sh, cap=400) and sh.otaled is None)
    await halt(sh)

    # apply does not go dark at 1 s (its period is slower, and the floor is lit)
    sh = Ship([16, 17, 18])
    hook(sh)
    UL.start(sh, "apply")
    check("apply came on", await wait_lit(sh))
    await lvship.sleep_ms(1000)
    check("apply still lit at 1 s (and otaled held)", lit(sh) and sh.otaled == "apply")
    await halt(sh)

    # start twice: one task
    sh = Ship([16, 17, 18])
    hook(sh)
    check("start once", UL.start(sh, "recv") is True)
    t1 = UL._task
    check("start twice: same task", UL.start(sh, "recv") is True and UL._task is t1)
    await wait_lit(sh)
    await halt(sh)

    # lvotap._led / lvota._led no-op without rgb_pins (don't load)
    import lvotap
    import lvota
    sys.modules.pop("lvotaled", None)
    sh = Ship("absent")
    srv = Server(sh)
    lvotap._led(srv, "recv")
    lvota._led(srv, "apply")
    lvota._led(srv, None)
    check("lvotap/lvota hooks without rgb_pins never load lvotaled", "lvotaled" not in sys.modules)

    check("no leaked exception handler entries", ERRS == [], ERRS)
    import lvotaled as UL
    await halt(None)


asyncio.run(on_vclock(ship_case))
print("otaled: %d checks ok" % ok[0])
