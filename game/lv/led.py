# The onboard LED as a quiet "something is waiting for you" light.
#
# Pico W facts this relies on: the only LED on the board is the user LED, wired to the
# CYW43 Wi-Fi/BT chip's WL_GPIO0, not to the RP2040. machine.Pin('LED') drives it by
# sending a command to the radio chip over its SPI bus; there is no PWM, just on/off.
# (There is no separate power LED on a Pico W.) Nothing else in this repo touches it.
#
# So every change is a radio-chip command. To keep it out of the way:
#  * off unless the ship config says led_notify: true; when off, the pin is never even
#    created (no SPI traffic at all);
#  * poll() is called from the main loop's idle slot, never from a BLE IRQ or scan
#    callback; pass radio_busy=True during a sync/HTTP burst and it just waits;
#  * one short blink (110 ms) every 4.5 s = under one command a second, average;
#  * dark in quiet hours (22:00-07:00 local, from the phone's clock), dark if the time
#    is unknown, and a daily budget of lit time (4 minutes = about 3.5 hours of blinking);
#  * any visit by the owner switches it off until something new turns up.
QUIET_FROM = 22 * 60
QUIET_TO = 7 * 60
ON_MS = 110
PERIOD_MS = 4500
BUDGET_MS = 240000


def _pin():
    from machine import Pin
    return Pin("LED", Pin.OUT)


class Notifier:
    def __init__(self, clock, enabled=False, pin_factory=_pin):
        self.clock = clock
        self.enabled = bool(enabled)
        self._factory = pin_factory
        self.pin = None
        self.waiting = False
        self.lit = False
        self.on_at = 0
        self.next = 0
        self.used = 0          # lit ms today
        self.day = None        # local day the budget belongs to
        self.writes = 0

    def _write(self, v):
        if self.pin is None:
            self.pin = self._factory()
        self.pin.value(v)
        self.lit = bool(v)
        self.writes += 1

    def set_enabled(self, on):
        on = bool(on)
        if not on and self.lit:
            self._write(0)
        self.enabled = on

    def set_waiting(self, flag):
        # True while the owner has something unseen (lv/engage.Local.unseen).
        self.waiting = bool(flag)

    def allowed(self):
        m = self.clock.minute()
        if m is None:
            return False
        if QUIET_FROM > QUIET_TO:
            if m >= QUIET_FROM or m < QUIET_TO:
                return False
        elif QUIET_FROM <= m < QUIET_TO:
            return False
        d = self.clock.date()
        if d != self.day:
            self.day, self.used = d, 0
        return self.used + ON_MS <= BUDGET_MS

    def poll(self, radio_busy=False):
        """Returns ms until it next wants to be called."""
        if not self.enabled:
            return 60000
        now = self.clock.uptime()
        if self.lit:
            left = ON_MS - (now - self.on_at)
            if left > 0:
                return left
            if radio_busy:
                return 20
            self._write(0)
            self.used += now - self.on_at
            return max(0, self.next - now)
        if now < self.next:
            return self.next - now
        if radio_busy:
            return 50
        if not self.waiting or not self.allowed():
            self.next = now + PERIOD_MS
            return PERIOD_MS
        self._write(1)
        self.on_at = now
        self.next = now + PERIOD_MS
        return ON_MS
