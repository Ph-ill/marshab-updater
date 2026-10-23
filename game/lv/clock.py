# Wall-clock time, learned from the phone.
#
# The Pico W has no battery-backed clock and the ships don't use NTP (Wi-Fi is a
# private hotspot). Every page request carries the phone's time:
#   X-Phone-Time: milliseconds since 1970 (UTC)    X-Phone-TZ: minutes east of UTC
# The ship keeps the offset against its own uptime counter. Until a phone has
# connected since boot the time is unknown, and everything that depends on it
# (job outcomes showing today, the LED) waits rather than guesses.
#
# Only used for presentation: the story never depends on the clock.
try:
    from time import ticks_ms, ticks_diff
except ImportError:          # CPython (tests, the mock server)
    import time as _t

    def ticks_ms():
        return int(_t.monotonic() * 1000) & 0x3FFFFFFF

    def ticks_diff(a, b):
        d = (a - b) & 0x3FFFFFFF
        return d - 0x40000000 if d & 0x20000000 else d

EPOCH_MIN = 1704067200000    # 2024-01-01: anything earlier is a phone with a wrong clock
EPOCH_MAX = 2208988800000    # 2040-01-01
SETTLE_MS = 120000           # ignore corrections smaller than 2 minutes


class Clock:
    def __init__(self, ticks=ticks_ms, diff=ticks_diff):
        self._ticks, self._diff = ticks, diff
        self._t = ticks()
        self._up = 0         # ms since boot, kept past the ticks_ms wrap
        self.base = None     # epoch ms at uptime 0, or None when unknown
        self.tz = 0          # minutes east of UTC

    def uptime(self):
        # Call at least every few days (the LED poll and every request do) so the
        # ticks_ms wrap (2^30 ms, ~12 days on MicroPython) is never missed.
        t = self._ticks()
        d = self._diff(t, self._t)
        if d > 0:
            self._up += d
        self._t = t
        return self._up

    def learn(self, epoch_ms, tz_min=0):
        """Take the phone's time. Returns True if it was accepted."""
        try:
            epoch_ms, tz_min = int(epoch_ms), int(tz_min)
        except (TypeError, ValueError):
            return False
        if not (EPOCH_MIN <= epoch_ms <= EPOCH_MAX) or not (-720 <= tz_min <= 840):
            return False
        base = epoch_ms - self.uptime()
        if self.base is None or abs(base - self.base) >= SETTLE_MS or tz_min != self.tz:
            self.base = base
            self.tz = tz_min
        return True

    def learn_headers(self, get):
        # `get(name)` returns a header value or None (works with any server's header map).
        v = get("x-phone-time")
        if v is None:
            return False
        return self.learn(v, get("x-phone-tz") or 0)

    def known(self):
        return self.base is not None

    def epoch_ms(self):
        return None if self.base is None else self.base + self.uptime()

    def local_minutes(self):
        # Minutes since 1970 in the phone's time zone, or None.
        e = self.epoch_ms()
        return None if e is None else e // 60000 + self.tz

    def minute(self):
        # Minute of the local day 0..1439, or None if the time is unknown.
        m = self.local_minutes()
        return None if m is None else m % 1440

    def date(self):
        # Local day number (days since 1970), or None.
        m = self.local_minutes()
        return None if m is None else m // 1440
