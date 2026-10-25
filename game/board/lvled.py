# The LED notifier: the Pico W's onboard LED as a quiet "something is waiting for you"
# light, for a case printed in transparent PLA. Off unless /data/ship.json says
# "led_notify": true (or a phone switches it on: CREW > your page > Ship light).
# lvship loads this module only when the light is on, so a board with it off holds none
# of this code (it keeps lv/led.py's dark Notifier).
#
# The hardware: the Pico W's only LED hangs off the CYW43 Wi-Fi/Bluetooth chip (WL_GPIO0),
# not the RP2040. machine.Pin("LED") sends each on/off to the radio chip over its SPI bus
# (about 0.3 ms a write, measured on a Pico W with the hotspot up). There is no PWM, so
# every pattern BREATHES in software: 100 frames a second (10 ms each), the LED on for part
# of each frame and off for the rest, the on part following a squared ramp (dim stays dim
# for a while, then it swells) up and back down. Fast enough that the eye sees a glow, not
# a flicker; tried on a real board first (bench `--led-test`).
#
# Staying out of the radio's and the phones' way:
#   * the light runs as its own small asyncio task (run(), started by lvship's loop while
#     the light is on). It yields to the web server, the DNS and the BLE sync after every
#     edge: the on part of a frame is an `await sleep_ms`, except a dim one (under 1.5 ms),
#     which is a short busy-wait so the dim end of the ramp stays dim. While a pattern
#     plays that is two radio writes and at most ~1.5 ms of CPU per 10 ms frame; between
#     patterns it sleeps (no radio traffic at all);
#   * frames nearly dark (under 0.1 ms on) or nearly full are a single write or none;
#   * a pattern never starts while a BLE sync or an HTTP request is in progress (busy); it
#     waits and starts after. If one starts DURING a pattern, the rest of it plays as a
#     plain blink (lit through the bright middle of each breath: 2 writes a breath) and
#     the breathing comes back with the next pattern;
#   * it times its own writes (a running average, `wus`): if the radio chip gets slow
#     (over 2 ms a write) it plays plain blinks instead, until the writes are fast again;
#   * no allocations per frame (small-int arithmetic, the asyncio sleep singleton), no
#     tables; no pin object until the first write; the pin goes dark when switched off.
#
# What it shows, most important first (each one distinct by count and pace):
#   test      3 slow breaths (1 s up, 1 s down), once: the bench check (selftest led_test)
#   new day   3 quick breaths, once, when a new flight day's page is ready (06:00)
#   gift      a double heartbeat pulse every ~4 s: a crewmate sent this ship a gift
#   waiting   one slow, gentle breath every ~5 s: today's page hasn't been opened here yet
# Everything clears when a signed-in phone opens the game here (the phone has seen it).
#
# When it stays dark:
#   * quiet hours, 22:00-07:00 local by default ("led_quiet": "HH:MM-HH:MM", "" for none).
#     The 06:00 new-day breaths fall in them, so they show at 07:00 instead (once);
#   * the time unknown (no phone since boot): dark, unless "led_unknown_time": true;
#   * a daily budget of lit time, 900 s by default ("led_budget_s"), counted by brightness
#     (a breath's squared ramp averages a third of full), about 2.5 hours of the waiting
#     breath; it resets at local midnight.
# Kept small on purpose: on the board this module's code lives in the heap next to two
# phones and a BLE sync (tests/phone_heap.py --led). Reading the settings and the phone's
# switch are in lvledcfg.py, loaded only for that moment and then dropped.
# Local time is the phones' (lv/clock.py: X-Phone-Time and X-Phone-TZ on each request),
# so quiet hours follow daylight saving once a phone has been by after the change.
#
# Patterns: (breaths, ms up, ms down, ms dark between breaths, ms pause before the next)
TEST = (3, 1000, 1000, 500, 2000)
DAY = (3, 200, 300, 150, 2000)
GIFT = (2, 150, 250, 120, 3000)
WAIT = (1, 600, 800, 0, 3500)
try:
    from micropython import const
except ImportError:                     # CPython (the tests)
    def const(x):
        return x
_FRAME = const(10)      # ms a frame (100 Hz)
_DIM_US = const(1500)   # on parts shorter than this are a busy-wait, not an await
_PLAIN_US = const(2000)  # average write cost above this: plain blinks

import time as _t        # ticks_us, ticks_diff, sleep_us (on CPython lvledcfg.make fills in stand-ins)


def _pin():
    from machine import Pin
    return Pin("LED", Pin.OUT)


class Led:
    """clock: lv/clock.py Clock. q: quiet hours (from, to) in local minutes or None;
    unknown: breathe with the time unknown; budget: lit ms a day. lvledcfg.make() builds
    one from ship.json. `state` says what it does or why it is dark: off, idle, test, day,
    gift, waiting, quiet, no clock, budget."""

    def __init__(self, clock, q=(1320, 420), unknown=False, budget=900000, pin=_pin):
        self.clock = clock
        self.q = q
        self.unknown = unknown
        self.budget = budget
        self.pin = pin                 # the factory until the first write, then the Pin
        self.enabled = self.lit = self.waiting = self.flash = self.testing = False
        self.gifts = self.writes = self.used = self.t0 = self.next = self.wus = self.mid = 0
        self.seq = self.day = self.task = None
        self.state = "off"

    def set_enabled(self, on):
        if not on:
            self.seq = None
            self.mid = 0
            self.state = "off"
            if self.lit:
                self._write(0)
        self.enabled = bool(on)

    def note(self, what):
        """What happened (lvship.Ship._led): "new_day" (a new flight day's page: the
        quick breaths, then waiting), "gift" (one arrived), "seen" (a phone has looked:
        all clear), "test" (the bench's 3 slow breaths)."""
        if what == "seen":
            self.waiting = self.flash = False
            self.gifts = 0
        elif what == "gift":
            self.gifts += 1
        elif what == "new_day":
            self.flash = self.waiting = True
        elif what == "test":
            self.testing = True
            self.next = 0

    def _write(self, v):
        if not hasattr(self.pin, "value"):
            self.pin = self.pin()
        t = _t.ticks_us()
        self.pin.value(v)
        self.wus = (self.wus * 3 + _t.ticks_diff(_t.ticks_us(), t)) >> 2      # average write cost, us
        self.lit = v
        self.writes += 1

    def poll(self, radio_busy=False):
        """Returns ms until it next wants to be called: a frame's edge while a pattern
        plays (run() below), up to seconds between patterns."""
        c = self.clock
        now = c.uptime()
        p = self.seq
        if not p:
            if not self.enabled:
                return 60000
            if now < self.next:
                return self.next - now
            if radio_busy:
                return 50
            s = "idle"
            if self.testing:
                p, s = TEST, "test"
                self.testing = False
            elif self.flash or self.gifts or self.waiting:
                m = c.minute()
                d = c.date()
                if d is None:                    # no clock: count days by uptime
                    d = -1 - now // 86400000
                if d != self.day:
                    self.day, self.used = d, 0
                p, s = (DAY, "day") if self.flash else (GIFT, "gift") if self.gifts else (WAIT, "waiting")
                q = self.q
                u = self.used + p[0] * (p[1] + p[2]) // 3      # lit ms: a breath averages a third
                if m is None and not self.unknown:
                    s = "no clock"
                elif q and m is not None and ((m >= q[0] or m < q[1]) if q[0] > q[1] else q[0] <= m < q[1]):
                    s = "quiet"
                elif u > self.budget:
                    s = "budget"
                else:
                    self.used = u
                    if s == "day":
                        self.flash = False
            self.state = s
            if s not in ("test", "day", "gift", "waiting"):    # dark: look again later
                self.next = now + (5000 if s == "idle" else 30000)
                return self.next - now
            self.seq, self.t0, self.mid = p, now, 0
        # one edge of the playing pattern
        if self.mid:                    # the on part of this frame is over
            r = self.mid
            self.mid = 0
            self._write(0)
            return r
        n, up, dn, gap, r = p           # (unpacking: no tuple made)
        b = up + dn + gap
        t = now - self.t0
        if t >= n * b - gap:            # done: dark, then the pause
            self.seq = None
            self.next = now + r
            on = 0
        else:
            t %= b                      # the ramp, x 0-100-0; lit (x/100)^2 of the frame
            x = t * 100 // up if t < up else (up + dn - t) * 100 // dn if t < up + dn else 0
            on = x * x                  # us lit in the 10 ms frame
            if radio_busy or self.wus > _PLAIN_US:     # plain blink: lit through the bright middle
                on = 10000 if x >= 50 else 0
            r = _FRAME
        if on < 100 or on >= 9500:      # a dark or a full frame: one write at most
            if (on > 100) != self.lit:
                self._write(on > 100)
            return r
        self._write(1)
        if on < _DIM_US:                # dim: a short busy-wait keeps it dim
            _t.sleep_us(on)
            self._write(0)
            return _FRAME - 1
        on = (on + 500) // 1000         # 2-9 ms lit: await it (the loop runs meanwhile)
        self.mid = _FRAME - on
        return on

    async def run(self, ship, sleep_ms):
        """The light's own asyncio task while it is on (lvship.Ship.loop starts it with its
        sleep_ms). Ends when switched off (or cancelled: lvship's loop returning), dark."""
        try:
            while self.enabled:         # busy: a BLE sync or an HTTP request in progress
                await sleep_ms(min(self.poll((ship.ble is not None and ship.ble.busy()) or
                                             (ship.web is not None and ship.web.busy > 0)), 500))
        finally:
            self.task = None
            if self.lit:
                self._write(0)
