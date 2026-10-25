# The LED notifier (board/lvled.py; its settings, board/lvledcfg.py) on a fake clock and
# pin: the breathing patterns (the squared ramp, how many breaths and how fast, each one
# distinct), frames that write at most twice, the plain-blink fallback while the radio is
# busy or slow, no allocation per frame (MicroPython), quiet hours (with the wrap past
# midnight and the 06:00 breaths deferred to 07:00), the unknown clock, the daily budget
# and its midnight reset, a daylight-saving change, busy radio deferral, seen(), switching
# off, and the light's own asyncio task in real time. Runs on CPython and MicroPython
# (tests/run.sh runs both).
import sys

sys.path.insert(0, "board")
sys.path.insert(0, ".")
import lvled
import lvledcfg
import time
from lv.clock import Clock

T = [0]


def days(y, m, d):
    # days since 1970-01-01 (H. Hinnant's days_from_civil)
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def at(y, mo, d, hh, mm, tz):
    """epoch ms of local y-mo-d hh:mm in a zone tz minutes east of UTC"""
    return ((days(y, mo, d) * 1440 + hh * 60 + mm) - tz) * 60000


DIM = []                        # the dim frames' busy-waits (lvled._t.sleep_us), us
COST = [0]                      # what a pin write "takes" (lvled's write-cost average), us


class FakeTime:
    # lvled's time functions: each ticks_us() call moves on by COST, so a write measures
    # COST; sleep_us (the dim busy-wait) is logged in DIM
    def __init__(self):
        self.us = 0
        self.rec = True

    def ticks_us(self):
        self.us += COST[0]
        return self.us

    def ticks_diff(self, a, b):
        return a - b

    def sleep_us(self, n):
        if self.rec:
            DIM.append(n)


FT = lvled._t = FakeTime()
FRAME, DIM_US, PLAIN_US = 10, 1500, 2000    # lvled's _FRAME, _DIM_US, _PLAIN_US (const)


class Pin:
    def __init__(self):
        self.log = []          # (uptime ms, value)
        self.v = 0

    def value(self, v):
        self.v = v
        self.log.append((T[0], v))


def make(cfg=None, when=None, tz=-300):
    T[0] = 1000
    clk = Clock(ticks=lambda: T[0], diff=lambda a, b: a - b)
    if when is not None:
        clk.learn(when, tz)
    pin = Pin()
    cfg = dict(cfg or {})
    cfg.setdefault("led_notify", True)
    led = lvledcfg.make(clk, cfg, say=lambda m: None, pin=lambda: pin)
    led.set_enabled(cfg["led_notify"])
    return led, clk, pin


def why(led):
    """What it does now (lvled.Led.state), looking again at once if it is dark."""
    if led.seq is None:
        led.next = 0
        led.poll()
    return led.state


def run(led, ms, busy=False):
    end = T[0] + ms
    while T[0] < end:
        w = led.poll(busy)
        T[0] = min(end, T[0] + max(1, w))


def ons(pin, since=0):
    return [t for t, v in pin.log if v and t >= since]


def lit_ms(pin):
    tot, t0 = 0, None
    for t, v in pin.log:
        if v:
            t0 = t
        elif t0 is not None:
            tot += t - t0
            t0 = None
    return tot


ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


# parse_quiet / quiet()
check("parse default", lvledcfg.parse_quiet("22:00-07:00") == (1320, 420))
check("parse off", lvledcfg.parse_quiet("") is None and lvledcfg.parse_quiet("off") is None)
for bad in ("25:00-07:00", "22:00", "x-y"):
    try:
        lvledcfg.parse_quiet(bad)
        check("parse rejects " + bad, False)
    except ValueError:
        ok[0] += 1
for spec, hhmm, want in (("22:00-07:00", (23, 0), True), ("22:00-07:00", (0, 0), True),
                         ("22:00-07:00", (6, 59), True), ("22:00-07:00", (22, 0), True),
                         ("22:00-07:00", (7, 0), False), ("22:00-07:00", (21, 59), False),
                         ("01:00-02:00", (1, 30), True), ("01:00-02:00", (2, 10), False),
                         ("", (23, 0), False), ("off", (3, 0), False)):
    led, clk, pin = make({"led_quiet": spec}, when=at(2026, 10, 23, hhmm[0], hhmm[1], -300))
    led.waiting = True
    check("quiet %s at %02d:%02d" % (spec, hhmm[0], hhmm[1]), (why(led) == "quiet") == want, why(led))
led, clk, pin = make({"led_quiet": "nonsense"})
check("bad led_quiet falls back", led.q == (1320, 420))


def bursts(pin, gap, since=0):
    """The pin's writes grouped into bursts (a breath, or a pattern) split by quiet gaps
    longer than `gap` ms: [(first write, last write, writes)]."""
    out = []
    for t, v in pin.log:
        if t < since:
            continue
        if out and t - out[-1][1] <= gap:
            a, b, n = out[-1]
            out[-1] = (a, t, n + 1)
        else:
            out.append((t, t, 1))
    return out


def frames(p):
    """Plays pattern p through Led.poll, frame by frame: [(ms since its start, us lit)] and
    the ms at which it ended."""
    led, clk, pin = make()
    FT.us = 0
    led.seq, led.t0, led.mid = p, clk.uptime(), 0
    t0, out = T[0], []
    while True:
        t, nd = T[0], len(DIM)
        w = led.poll()
        if led.seq is None:
            return out, t - t0
        if led.mid:                     # lit, the await part: on for w ms, then dark
            on = w * 1000
            T[0] += w
            w = led.poll()
        elif len(DIM) > nd:             # dim: lit for a short busy-wait
            on = DIM[-1]
        else:
            on = 10000 if led.lit else 0
        out.append((t - t0, on))
        T[0] += w


def shape(p):
    """(breaths, ms until it ended, peak us lit a frame)"""
    f, end = frames(p)
    n = sum(1 for a, b in zip([(0, 0)] + f, f) if b[1] and not a[1])
    return n, end, max(on for t, on in f)


# the patterns themselves: how many breaths, how long, the squared ramp
for name, p, want in (("test", lvled.TEST, (3, 7000)), ("day", lvled.DAY, (3, 1800)),
                      ("gift", lvled.GIFT, (2, 920)), ("waiting", lvled.WAIT, (1, 1400))):
    n, dur, peak = shape(p)
    check("%s: %d breaths in %d ms" % (name, want[0], want[1]), n == want[0] and want[1] <= dur < want[1] + FRAME,
          (n, dur))
    check("%s reaches (near) full" % name, peak >= 8000, peak)    # (10 ms frames sample the peak)
check("each pattern distinct (count, pace)", len(set((shape(p)[0], p[1]) for p in
                                                        (lvled.TEST, lvled.DAY, lvled.GIFT, lvled.WAIT))) == 4)
up = lvled.WAIT[1]
f, end = frames(lvled.WAIT)
r = [on for t, on in f if t <= up]
check("ramp rises", all(a <= b for a, b in zip(r, r[1:])) and r[0] == 0 and r[-1] >= 9900, r)
half = [on for t, on in f if abs(t - up // 2) <= 5]
check("ramp is squared (half way = a quarter, to the ms)", half and all(2000 <= on <= 3000 for on in half), half)
r = [on for t, on in f if t >= up]
check("ramp falls", all(a >= b for a, b in zip(r, r[1:])) and r[-1] < 100, r[-5:])
check("frames 9-10 ms apart", all(9 <= y[0] - x[0] <= FRAME for x, y in zip(f, f[1:])))

# off by default: never touches the pin, not even to create it
clk = Clock(ticks=lambda: T[0], diff=lambda a, b: a - b)
led = lvledcfg.make(clk, {}, pin=lambda: 1 / 0)
led.note("new_day")
led.note("gift")
run(led, 60000)
check("off by default", not led.enabled and led.writes == 0 and not hasattr(led.pin, "value") and why(led) == "off")
check("default budget 900 s", led.budget == 900000)
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.waiting = True
run(led, 100)
check("charged a third of a breath", led.used == 1400 // 3 and led.seq is lvled.WAIT, led.used)

# idle: on, nothing waiting -> dark
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
run(led, 60000)
check("idle dark", led.writes == 0 and why(led) == "idle")

# waiting: one slow breath every ~4.9 s, drawn in 10 ms frames
led.waiting = True
DIM[:] = []
t0 = T[0]
run(led, 20000)
b = bursts(pin, 300)
check("waiting breaths", 4 <= len(b) <= 5, b)
check("waiting rhythm", all(4800 <= y[0] - x[0] <= 5000 for x, y in zip(b, b[1:])), b)
check("a breath lasts ~1.4 s", all(1100 <= y - x <= 1400 for x, y, n in b[:-1]), b)
frames = 1400 // FRAME
check("at most 2 writes a frame", all(n <= 2 * frames for x, y, n in b), b)
check("breathing, not blinking (many writes a breath)", all(n >= 100 for x, y, n in b[:-1]), b)
check("the dim end is a short busy-wait", DIM and max(DIM) < DIM_US and min(DIM) >= 100, (min(DIM or [0]), max(DIM or [0])))
on = [y[0] - x[0] for x, y in zip(pin.log, pin.log[1:]) if x[1] and not y[1]]
check("brighter frames lit 2-9 ms by await", max(on) <= FRAME and any(2 <= d < FRAME for d in on), on[:20])
check("dark between breaths", not led.lit and why(led) == "waiting")

# seen() clears everything; the LED ends dark
led.note("gift")
led.note("new_day")
led.note("seen")
run(led, 30000)
n = led.writes
run(led, 30000)
check("seen clears", led.writes == n and not led.lit and why(led) == "idle")

# gift: a double pulse every ~3.9 s; outranks waiting
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.waiting = True
led.note("gift")
check("gift why", why(led) == "gift")
run(led, 12000)
p = bursts(pin, 300)
check("gift repeats", len(p) >= 3 and all(3800 <= y[0] - x[0] <= 4000 for x, y in zip(p, p[1:])), p)
d = bursts(pin, 60, since=p[0][0])
d = [x for x in d if x[0] <= p[0][1]]
check("gift is a double pulse", len(d) == 2 and 450 <= d[1][0] - d[0][0] <= 600, d)

# unknown clock: dark unless led_unknown_time
led, clk, pin = make()
led.waiting = True
led.note("gift")
run(led, 30000)
check("unknown clock dark", led.writes == 0 and why(led) == "no clock")
led, clk, pin = make({"led_unknown_time": True})
led.waiting = True
run(led, 10000)
check("unknown clock allowed", len(bursts(pin, 300)) >= 2 and why(led) == "waiting")

# quiet hours: 23:30 dark, the new-day breaths at 06:00 wait for 07:00, once
led, clk, pin = make(when=at(2026, 10, 23, 23, 30, -300))
led.waiting = True
run(led, 60000)
check("quiet 23:30 dark", led.writes == 0 and why(led) == "quiet")
T[0] = 1000 + (6 * 60 + 30) * 60000          # 06:00 next morning (the board's uptime moves on)
led.note("new_day")
run(led, 30 * 60000)
check("06:00 breaths held in quiet hours", led.writes == 0 and led.flash)
run(led, 31 * 60000)                        # past 07:00
p = bursts(pin, 300)
check("new day at 07:00", len(p) >= 2 and clk.minute() >= 420, (p[:3], clk.minute()))
first = p[0][0]
d = bursts(pin, 60)
d = [x for x in d if x[0] <= p[0][1]]
check("new day is 3 quick breaths", len(d) == 3 and all(450 <= y[0] - x[0] <= 700 for x, y in zip(d, d[1:])), d)
check("once, then waiting", not led.flash and why(led) == "waiting" and p[1][0] - p[0][1] > 2000, p[:3])
seven = 1000 + 450 * 60000                  # uptime at 07:00 (learned 23:30 at uptime 1000)
check("new day within 30 s of 07:00", 0 <= first - seven <= 30000, first - seven)

# busy radio: never starts a pattern during a sync / request; starts right after
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.note("new_day")
run(led, 20000, busy=True)
check("busy defers", led.writes == 0)
run(led, 100)
check("starts when free", led.writes >= 1)
# ...and if the radio gets busy mid-pattern, the rest plays as plain blinks (2 writes a
# breath), ending dark
n = led.writes
run(led, 5000, busy=True)
check("busy mid-pattern: plain blinks", 1 <= led.writes - n <= 6 and not led.lit, led.writes - n)

# the write cost: ~0.3-0.4 ms on a Pico W (one command to the radio chip) still breathes;
# over 2 ms a write, a plain blink (2 writes a breath)
led, clk, pin = make({"led_unknown_time": True})
led.waiting = True
COST[0] = 400
run(led, 1500)
check("0.4 ms writes: breathing", led.writes >= 100 and 350 <= led.wus <= 400, (led.writes, led.wus))
led, clk, pin = make({"led_unknown_time": True})
led.waiting = True
COST[0] = PLAIN_US + 100
led.wus = COST[0]
run(led, 1500)
check("slow writes: a plain blink", led.writes == 2 and not led.lit, led.writes)
COST[0] = 0

# no allocation per frame (MicroPython: the board's heap)
try:
    import gc
    alloc = gc.mem_alloc
except AttributeError:
    alloc = None
if alloc:
    class Quiet:
        def value(self, v):
            pass
    led, clk, pin = make({"led_unknown_time": True})
    led.pin = Quiet()
    FT.rec = False
    def edges(led, n):
        a = alloc()
        while n:
            T[0] += max(1, led.poll())
            n -= 1
        return alloc() - a

    led.note("test")
    edges(led, 20)                  # (warm up: the first calls set things up once)
    edges(led, 1)
    gc.collect()
    a = edges(led, 500)             # 500 edges, well inside the 7 s pattern
    check("no allocation per frame", a == 0 and led.seq is not None, a)
    FT.rec = True

# budget: led_budget_s 1 -> 2 waiting breaths (466 ms of full each), then dark until local midnight
led, clk, pin = make({"led_budget_s": 1}, when=at(2026, 10, 23, 12, 0, -300))
led.waiting = True
run(led, 120000)
check("budget stops", len(bursts(pin, 300)) == 2 and why(led) == "budget", len(bursts(pin, 300)))
run(led, 11 * 3600000)                     # to 23:00: quiet anyway
n = led.writes
T[0] += 8 * 3600000                        # 07:00 next day: a new budget
run(led, 10000)
check("budget resets at midnight", led.writes > n)
check("900 s is ~2.5 h of waiting", 2.4 <= 900000 / (1400 // 3) * (1400 + lvled.WAIT[4]) / 3600000 <= 2.8)

# daylight saving: quiet hours follow the phones' zone. 02:30 UTC on Nov 2 is 21:30 CDT
# before the change... the phone reports CST (-360) after it, the same instant is 20:30.
when = days(2026, 11, 2) * 86400000 + (3 * 60 + 30) * 60000      # 03:30 UTC
led, clk, pin = make(when=when, tz=-300)                         # 22:30 CDT: quiet
led.waiting = True
check("DST before: 22:30 quiet", why(led) == "quiet" and clk.minute() == 22 * 60 + 30)
clk.learn(when, -360)                                            # 21:30 CST
check("DST after: 21:30 lit", why(led) == "waiting" and clk.minute() == 21 * 60 + 30)
run(led, 5000)
check("DST breathes", len(bursts(pin, 300)) >= 1)

# the bench test: 3 slow breaths, even in quiet hours or with no clock; dark after
led, clk, pin = make()
led.note("test")
run(led, 9000)
d = bursts(pin, 300)
check("test 3 slow breaths", len(d) == 3 and all(2400 <= y[0] - x[0] <= 2600 for x, y in zip(d, d[1:])), d)
check("test dark after, many writes", led.writes >= 6 and not led.lit and led.seq is None)
led, clk, pin = make(when=at(2026, 10, 23, 23, 0, -300))
led.note("test")
run(led, 9000)
check("test in quiet hours", len(bursts(pin, 300)) == 3)

# switching off mid-breath turns it dark at once
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.note("test")
while not led.lit:
    T[0] += max(1, led.poll())
check("lit mid-test", led.lit)
led.set_enabled(False)
check("off goes dark", not led.lit and pin.v == 0 and why(led) == "off")
n = led.writes
run(led, 10000)
check("off stays dark", led.writes == n)

# the light's own task (run(), as lvship starts it) in real time: the new-day breaths
# (1.8 s), then switched off: the task ends, dark
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
try:
    from time import ticks_ms as now_ms
except ImportError:
    def now_ms():
        return int(time.monotonic() * 1000)
clk = Clock(ticks=now_ms, diff=lambda a, b: a - b)
pin = Pin()
led = lvledcfg.make(clk, {"led_unknown_time": True}, say=lambda m: None, pin=lambda: pin)
led.set_enabled(True)
busy = [0]


class Web:
    busy = 0


class Ship:                     # what run() looks at: lvship.Ship's ble and web
    ble = None
    web = Web()


def sleep_ms(ms):
    return asyncio.sleep_ms(ms) if hasattr(asyncio, "sleep_ms") else asyncio.sleep(ms / 1000)


async def main():
    led.task = asyncio.create_task(led.run(Ship(), sleep_ms))
    led.note("new_day")
    for i in range(22):
        if asyncio.__name__.startswith("u") or hasattr(asyncio, "sleep_ms"):
            await asyncio.sleep_ms(100)
        else:
            await asyncio.sleep(0.1)
    led.set_enabled(False)
    for i in range(12):
        if led.task is None:
            break
        await (asyncio.sleep_ms(50) if hasattr(asyncio, "sleep_ms") else asyncio.sleep(0.05))
asyncio.run(main())
check("task played the breaths", led.writes >= 60 and not led.flash, led.writes)
check("task ended dark", led.task is None and not led.lit)

print("test_led: %d checks ok" % ok[0])
