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


fail = None             # tests: called at "open", "write", "read" and "rename" to simulate a failure


def _hit(where):
    if fail:
        fail(where)


def valid(c):
    """Is c a whole ship identity, one the ship may write or keep as a backup? A ship number
    1-8 (the bench and the web updater always write one) and, if there is a hotspot
    password, one of 8-63 characters. No password is allowed: the updater's "WPA2, firmware
    default password" writes none. {"led_notify": true} alone is not one: a ship.json like
    that comes up as ship 1 (review #1 M1)."""
    if not isinstance(c, dict):
        return False
    i = c.get("ship_id")
    if isinstance(i, bool) or not (isinstance(i, int) or isinstance(i, str) and i.isdigit()) or not 1 <= int(i) <= 8:
        return False
    pw = c.get("hotspot_password")
    return pw is None or isinstance(pw, str) and 8 <= len(pw) <= 63


def save(path, c):
    """Write the settings dict c to path whole, as lvcode.save does crew.json: the text to
    path.new, read back and compared, then renamed over path (one step on littlefs and
    POSIX), so ship.json is always the old file or the new one, never a half-written one
    (0.2.6 and before wrote it in place: a restart mid-write could leave it unreadable,
    and the ship would come up as a default ship 1). True, or False (path as it was).
    A rename that fails is a failure: there is no second route that moves ship.json aside
    first (that left a moment with no ship.json at all)."""
    import json
    import os
    text = json.dumps(c)
    tmp = path + ".new"
    try:
        _hit("write")
        with open(tmp, "w") as f:
            f.write(text)
        _hit("read")
        with open(tmp) as f:
            if f.read() != text:
                raise OSError("ship.json.new reads back wrong")
        _hit("rename")
        os.rename(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def toggle(phone, on):
    """The phone's Ship light switch (CREW > your page; lvphone.Phone, POST /api/led): on
    or off now and after a restart (led_notify in /data/ship.json, the rest kept). Only a
    ship.json that reads back as a whole identity (valid) is rewritten. Missing, unreadable
    (any error but "no such file" too: a damaged block, no heap), or not an identity: the
    switch works until the restart and the file is left exactly as it is."""
    sh = phone.ship
    on = sh.led_on(on)
    sh.v += 1
    if phone.data:
        import json
        p = phone.data + "/ship.json"
        try:
            _hit("open")
            with open(p) as f:
                c = json.load(f)
        except Exception:
            c = None
        if not valid(c):
            sh.say("led: ship.json missing, unreadable or not whole: setting kept until restart")
        else:
            c["led_notify"] = on
            if not save(p, c):
                sh.say("led: setting not saved")
    sh.say("led: notifier %s (from a phone)" % ("on" if on else "off"))
    import lvship
    lvship.drop("lvledcfg")          # (Ship.led_on drops it too, unless it had nothing to do)
    return on
