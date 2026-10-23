# The LED notifier (board/lvled.py; its settings, board/lvledcfg.py) on a fake clock and
# pin: patterns, quiet hours (with the wrap past midnight and the 06:00 flash deferred to 07:00), the unknown clock, the
# daily budget and its midnight reset, a daylight-saving change, busy radio deferral,
# seen() and switching off. Runs on CPython and MicroPython (tests/run.sh runs both).
import sys

sys.path.insert(0, "board")
sys.path.insert(0, ".")
import lvled
import lvledcfg
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

# off by default: never touches the pin, not even to create it
clk = Clock(ticks=lambda: T[0], diff=lambda a, b: a - b)
led = lvledcfg.make(clk, {}, pin=lambda: 1 / 0)
led.note("new_day")
led.note("gift")
run(led, 60000)
check("off by default", not led.enabled and led.writes == 0 and not hasattr(led.pin, "value") and why(led) == "off")

# idle: on, nothing waiting -> dark
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
run(led, 60000)
check("idle dark", led.writes == 0 and why(led) == "idle")

# waiting: one 90 ms blink every 4 s or so
led.waiting = True
run(led, 20000)
o = ons(pin)
check("waiting pulses", 4 <= len(o) <= 5, o)
check("waiting rhythm", all(4000 <= b - a <= 4200 for a, b in zip(o, o[1:])), o)
check("waiting 90 ms on", lit_ms(pin) == 90 * len(o) and not led.lit)
check("waiting 2 writes a pulse", led.writes == 2 * len(o))

# seen() clears everything; the LED ends dark
led.note("gift")
led.note("new_day")
led.note("seen")
n = led.writes
run(led, 30000)
check("seen clears", led.writes == n and not led.lit and why(led) == "idle")

# gift: double blink every ~3.4 s; outranks waiting
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.waiting = True
led.note("gift")
check("gift why", why(led) == "gift")
run(led, 3000)
o = ons(pin)
check("gift double blink", len(o) == 2 and o[1] - o[0] == 290, o)
run(led, 10000)
check("gift repeats", len(ons(pin)) >= 6)

# unknown clock: dark unless led_unknown_time
led, clk, pin = make()
led.waiting = True
led.note("gift")
run(led, 30000)
check("unknown clock dark", led.writes == 0 and why(led) == "no clock")
led, clk, pin = make({"led_unknown_time": True})
led.waiting = True
run(led, 10000)
check("unknown clock allowed", len(ons(pin)) >= 2 and why(led) == "waiting")

# quiet hours: 23:30 dark, the new-day flash at 06:00 waits for 07:00, once
led, clk, pin = make(when=at(2026, 10, 23, 23, 30, -300))
led.waiting = True
run(led, 60000)
check("quiet 23:30 dark", led.writes == 0 and why(led) == "quiet")
T[0] = 1000 + (6 * 60 + 30) * 60000          # 06:00 next morning (the board's uptime moves on)
led.note("new_day")
run(led, 30 * 60000)
check("06:00 flash held in quiet hours", led.writes == 0 and led.flash)
run(led, 31 * 60000)                        # past 07:00
o = ons(pin)
check("flash at 07:00", len(o) >= 3 and clk.minute() >= 420, (o, clk.minute()))
first = o[0]
check("flash is 3 quick flashes", o[1] - o[0] == 250 and o[2] - o[1] == 250, o[:4])
check("flash once, then waiting", not led.flash and why(led) == "waiting" and o[3] - o[2] > 2000, o[:5])
seven = 1000 + 450 * 60000                  # uptime at 07:00 (learned 23:30 at uptime 1000)
check("flash within 30 s of 07:00", 0 <= first - seven <= 30000, first - seven)

# busy radio: never starts a pattern during a sync / request; starts right after
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.note("new_day")
run(led, 20000, busy=True)
check("busy defers", led.writes == 0)
run(led, 100)
check("starts when free", led.writes >= 1)
# ...but a pattern already playing finishes (its off write) even if the radio gets busy
run(led, 5000, busy=True)
check("finishes dark while busy", not led.lit)

# budget: led_budget_s 1 -> 11 waiting pulses (90 ms each), then dark until local midnight
led, clk, pin = make({"led_budget_s": 1}, when=at(2026, 10, 23, 12, 0, -300))
led.waiting = True
run(led, 120000)
check("budget stops", len(ons(pin)) == 11 and why(led) == "budget", len(ons(pin)))
run(led, 11 * 3600000)                     # to 23:00: quiet anyway
n = len(ons(pin))
T[0] += 8 * 3600000                        # 07:00 next day: a new budget
run(led, 10000)
check("budget resets at midnight", len(ons(pin)) > n)

# daylight saving: quiet hours follow the phones' zone. 02:30 UTC on Nov 2 is 21:30 CDT
# before the change... the phone reports CST (-360) after it, the same instant is 20:30.
when = days(2026, 11, 2) * 86400000 + (3 * 60 + 30) * 60000      # 03:30 UTC
led, clk, pin = make(when=when, tz=-300)                         # 22:30 CDT: quiet
led.waiting = True
check("DST before: 22:30 quiet", why(led) == "quiet" and clk.minute() == 22 * 60 + 30)
clk.learn(when, -360)                                            # 21:30 CST
check("DST after: 21:30 lit", why(led) == "waiting" and clk.minute() == 21 * 60 + 30)
run(led, 5000)
check("DST blinks", len(ons(pin)) >= 1)

# the bench test: 3 slow blinks, even in quiet hours or with no clock; 6 writes
led, clk, pin = make()
led.note("test")
run(led, 7000)
o = ons(pin)
check("test 3 slow blinks", len(o) == 3 and o[1] - o[0] == 2000 and lit_ms(pin) == 3000, o)
check("test 6 writes, dark after", led.writes == 6 and not led.lit)
led, clk, pin = make(when=at(2026, 10, 23, 23, 0, -300))
led.note("test")
run(led, 7000)
check("test in quiet hours", led.writes == 6)

# switching off mid-blink turns it dark at once
led, clk, pin = make(when=at(2026, 10, 23, 12, 0, -300))
led.note("test")
run(led, 500)
check("lit mid-test", led.lit)
led.set_enabled(False)
check("off goes dark", not led.lit and pin.v == 0 and why(led) == "off")
n = led.writes
run(led, 10000)
check("off stays dark", led.writes == n)

print("test_led: %d checks ok" % ok[0])
