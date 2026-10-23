# The LED notifier: the Pico W's onboard LED as a quiet "something is waiting for you"
# light, for a case printed in transparent PLA. Off unless /data/ship.json says
# "led_notify": true (or a phone switches it on: CREW > your page > Ship light).
# lvship loads this module only when the light is on, so a board with it off holds none
# of this code (it keeps lv/led.py's dark Notifier).
#
# The hardware: the Pico W's only LED hangs off the CYW43 Wi-Fi/Bluetooth chip (WL_GPIO0),
# not the RP2040. machine.Pin("LED") sends each on/off to the radio chip over its SPI bus.
# There is no PWM, so a "pulse" is a short on/off rhythm. To stay out of the radio's way:
#   * every pattern is a few writes (a gentle pulse is 2 writes every 4 s, on average one
#     SPI command every 2 s), from the main loop's idle slot, never from a BLE/IRQ callback;
#   * a pattern never starts while a BLE sync or an HTTP request is in progress (busy); it
#     waits and starts after;
#   * no pin object until the first blink; the pin goes dark when the light is switched off.
#
# What it shows, most important first:
#   test      3 slow blinks (1 s on, 1 s off), once: the bench check (selftest led_test)
#   new day   3 quick flashes, once, when a new flight day's page is ready (06:00)
#   gift      double blink every 3 s: a crewmate sent this ship's crew a gift
#   waiting   one short blink every 4 s: today's page hasn't been opened here yet
# Everything clears when a signed-in phone opens the game here (the phone has seen it).
#
# When it stays dark:
#   * quiet hours, 22:00-07:00 local by default ("led_quiet": "HH:MM-HH:MM", "" for none).
#     The 06:00 new-day flash falls in them, so it shows at 07:00 instead (once);
#   * the time unknown (no phone since boot): dark, unless "led_unknown_time": true;
#   * a daily budget of lit time, 240 s by default ("led_budget_s"), about 3 hours of the
#     waiting pulse; it resets at local midnight.
# Kept small on purpose: on the board this module's code lives in the heap next to two
# phones and a BLE sync (tests/phone_heap.py --led). Reading the settings and the phone's
# switch are in lvledcfg.py, loaded only for that moment and then dropped.
# Local time is the phones' (lv/clock.py: X-Phone-Time and X-Phone-TZ on each request),
# so quiet hours follow daylight saving once a phone has been by after the change.
#
# Patterns: (lit ms in all, on, off, on, ..., the pause before the next pattern)
TEST = (3000, 1000, 1000, 1000, 1000, 1000, 1000)
DAY = (210, 70, 180, 70, 180, 70, 2000)
GIFT = (180, 90, 200, 90, 3000)
WAIT = (90, 90, 4000)


def _pin():
    from machine import Pin
    return Pin("LED", Pin.OUT)


class Led:
    """clock: lv/clock.py Clock. q: quiet hours (from, to) in local minutes or None;
    unknown: blink with the time unknown; budget: lit ms a day. lvledcfg.make() builds
    one from ship.json. `state` says what it does or why it is dark: off, idle, test, day,
    gift, waiting, quiet, no clock, budget."""

    def __init__(self, clock, q=(1320, 420), unknown=False, budget=240000, pin=_pin):
        self.clock = clock
        self.q = q
        self.unknown = unknown
        self.budget = budget
        self.pin = pin                 # the factory until the first blink, then the Pin
        self.enabled = self.lit = self.waiting = self.flash = self.testing = False
        self.gifts = self.writes = self.used = self.i = self.at = self.next = 0
        self.seq = self.day = None
        self.state = "off"

    def set_enabled(self, on):
        if not on:
            self.seq = None
            self.state = "off"
            if self.lit:
                self._write(0)
        self.enabled = bool(on)

    def note(self, what):
        """What happened (lvship.Ship._led): "new_day" (a new flight day's page: the
        flash, then waiting), "gift" (one arrived), "seen" (a phone has looked: all
        clear), "test" (the bench's 3 slow blinks)."""
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
        self.pin.value(v)
        self.lit = v
        self.writes += 1

    def poll(self, radio_busy=False):
        """Call from the main loop. Returns ms until it next wants to be called."""
        c = self.clock
        now = c.uptime()
        p = self.seq
        if p:
            if now < self.at:
                return self.at - now
            self.i += 1
            if self.i >= len(p) - 1:            # done: dark, then the pause
                if self.lit:
                    self._write(0)
                self.seq = None
                self.next = now + p[-1]
                return p[-1]
        else:
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
                if m is None and not self.unknown:
                    s = "no clock"
                elif q and m is not None and ((m >= q[0] or m < q[1]) if q[0] > q[1] else q[0] <= m < q[1]):
                    s = "quiet"
                elif self.used + p[0] > self.budget:
                    s = "budget"
                else:
                    self.used += p[0]
                    if s == "day":
                        self.flash = False
            self.state = s
            if s not in ("test", "day", "gift", "waiting"):    # dark: look again later
                self.next = now + (5000 if s == "idle" else 30000)
                return self.next - now
            self.seq, self.i = p, 1
        v = self.i & 1
        if v != self.lit:
            self._write(v)
        self.at = now + self.seq[self.i]
        return self.seq[self.i]
