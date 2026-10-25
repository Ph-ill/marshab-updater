# The LED notifier's settings and switch (lvled.py has the notifier itself). Loaded for
# the moment it is needed and then dropped (lvship.Ship.led_on deletes it from
# sys.modules), so none of this sits in the heap while phones play.
#   led_notify        true: on (game firmware only; "force" also on stock MicroPython)
#   led_quiet         "HH:MM-HH:MM" local, default "22:00-07:00"; "" or "off": no quiet hours
#   led_unknown_time  true: breathe before any phone has brought the time (default false)
#   led_budget_s      lit seconds a day (by brightness), default 900
QUIET = "22:00-07:00"


def _hm(s):
    s = s.strip()
    if len(s) < 4 or s[-3] != ":":
        raise ValueError
    m = int(s[:-3]) * 60 + int(s[-2:])
    if not 0 <= m < 1440:
        raise ValueError
    return m


def parse_quiet(s):
    """'22:00-07:00' -> (1320, 420); '' / 'off' / None -> None. Raises ValueError."""
    if not s or s == "off":
        return None
    a, b = str(s).split("-")
    return _hm(a), _hm(b)


class _HostTime:
    # CPython (the tests): the three MicroPython time functions lvled uses
    def ticks_us(self):
        import time
        return time.perf_counter_ns() // 1000

    def ticks_diff(self, a, b):
        return a - b

    def sleep_us(self, n):
        pass


def make(clock, cfg, say=print, pin=None):
    import lvled
    if not hasattr(lvled._t, "ticks_us"):
        lvled._t = _HostTime()
    try:
        q = parse_quiet(cfg.get("led_quiet", QUIET))
    except Exception:
        say("led: led_quiet %r not understood (HH:MM-HH:MM), using %s" % (cfg.get("led_quiet"), QUIET))
        q = parse_quiet(QUIET)
    try:
        b = int(cfg.get("led_budget_s", 900)) * 1000
    except Exception:
        b = 900000
    return lvled.Led(clock, q, bool(cfg.get("led_unknown_time", False)), b, pin or lvled._pin)


def switch(ship, on):
    """lvship.Ship.led_on's work: swap lv/led.py's dark Notifier for an lvled.Led, switch it."""
    if on and not hasattr(ship.led, "note"):
        ship.led = make(ship.clock, ship.cfg, ship.say)
    ship.led.set_enabled(on)
    if ship.cfg.get("led_notify") != "force":
        ship.cfg["led_notify"] = bool(on)
    return bool(on)


def toggle(phone, on):
    """The phone's Ship light switch (CREW > your page; lvphone.Phone, POST /api/led): on
    or off now and after a restart (led_notify in /data/ship.json, the rest kept)."""
    sh = phone.ship
    on = sh.led_on(on)
    sh.v += 1
    if phone.data:
        import json
        p = phone.data + "/ship.json"
        try:
            with open(p) as f:
                c = json.load(f)
        except Exception:
            c = {}
        c["led_notify"] = on
        try:
            with open(p, "w") as f:
                json.dump(c, f)
        except OSError as e:
            sh.say("led: setting not saved %s" % e)
    sh.say("led: notifier %s (from a phone)" % ("on" if on else "off"))
    import lvship
    lvship.drop("lvledcfg")          # (Ship.led_on drops it too, unless it had nothing to do)
    return on
