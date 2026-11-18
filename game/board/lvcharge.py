# The charge light (0.3.6): while a ship with an RGB LED (ship.json "rgb_pins",
# board/lvrgb.py) is charging, the LED breathes slowly, its colour following the
# cell's level when the gauge has one. Every other ship never loads this module
# (main.py charge_light checks rgb_pins before importing). It starts from the
# charger watch when the plug-detect line has held, uses the same ship.bat the
# watch and the gauge already keep (no extra I2C, no extra pin reads), and ends
# when the cable has been out long enough for the watch to take "unplugged".
#
# What the ship can tell: bat[2] is the UPS-Lite's "power plugged in" line
# (True/False/None), not a separate "charging vs full" signal; bat[0] is the
# CW2015's percent, or None until a reading lands. The Pico's own USB socket
# does not charge the cell and does not assert that line, so this light stays
# dark then. "Full" here means percent >= 100 while still plugged in.
#
# The sequence, PERIOD = 3000 ms a breath while charging, PERIOD_FULL = 8000 ms
# when full and still plugged in:
#   charging    a slow breath, 0-100-0 over 3 s, on a squared envelope (dim stays
#               dim, then it swells), peak PEAK of 255, then lvrgb.duty's curve
#               and rgb_scale; colour from amber/orange at low, through yellow,
#               to green near full; a soft cyan-blue if the percent is unknown
#   full        a much slower, shallower green breath around a dim glow
#   unplugged   over: every duty 0, every PWM deinit'd, the pins back to inputs
#
# Who has the light: this play takes the RGB LED the way the launch does (sh.rgb)
# and never sets sh.ledtest, so a Test light tap is never a 429: the test takes
# the LED over (lvrgb._open switches these PWMs off and this play parks without
# touching the new ones). It also parks, all off, when an update's upload starts
# (web.ota_busy) or any light playback is marked (sh.ledtest: a Test light, a
# hail's flicker), and while someone else holds sh.rgb (the boot launch). When
# that has ended and the ship is still charging, the breath starts again from
# dark. It doesn't start at all without usable rgb_pins; safe mode never starts
# the charger watch, so it never starts this either.
#
# A 25 fps asyncio task (FRAME = 40 ms), not a Timer: it may run for hours, and
# it must yield to the web server, the DNS and the BLE sync. Integer-only, no
# allocation on the quiet path (no range(), one small int per colour, duty
# writes only when a channel's level changes). Pins are opened in the task, so
# a coroutine that never runs holds no pin.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvrgb import pins, scale, duty, _open, _off

PERIOD = 3000
PERIOD_FULL = 8000
_FRAME = 40
_WAIT = 100                 # ms between looks while parked for a higher-priority light
PEAK = 72                   # 0-255 peak of the charging breath (subtle)
FULL_BASE = 18              # 0-255 dim green floor when full and still plugged in
FULL_SWING = 22             # plus this at the top of the slow full breath
# soft cyan-blue when the gauge has no percent yet (not a fake level)
UNKNOWN = (0, 90, 160)
# percent, red, green, blue: amber/orange at low, through yellow, to green
_STOPS = (
    0, 255, 70, 0,
    25, 255, 130, 0,
    50, 255, 190, 0,
    80, 160, 220, 20,
    100, 0, 200, 40,
)

# The play, if one is running.
_task = None
_stop = False
_pw = None
_host = None


def colour(pct, k):
    """Channel k's (0 red, 1 green, 2 blue) 0-255 for a 0-100 percent, or the
    unknown colour when pct is None."""
    if pct is None:
        return UNKNOWN[k]
    if pct <= 0:
        return _STOPS[1 + k]
    if pct >= 100:
        return _STOPS[len(_STOPS) - 3 + k]
    i = 0
    while _STOPS[i + 4] <= pct:
        i += 4
    a = _STOPS[i + 1 + k]
    return a + (_STOPS[i + 5 + k] - a) * (pct - _STOPS[i]) // (_STOPS[i + 4] - _STOPS[i])


def env(t, period):
    """Perceptual 0-100 breath at t ms into a cycle of period ms (squared ramp)."""
    if period <= 0:
        return 0
    if t < 0:
        t = 0
    u = t % period
    h = period // 2
    d = period - h
    if h <= 0 or d <= 0:
        return 0
    x = u * 100 // h if u < h else (period - u) * 100 // d
    return x * x // 100


def level(t, k, pct):
    """Colour k's 0-255 at t ms into this play, for percent pct (None or 0-100)."""
    c = colour(pct, k)
    full = pct is not None and pct >= 100
    e = env(t, PERIOD_FULL if full else PERIOD)
    if full:
        return c * (FULL_BASE + FULL_SWING * e // 100) // 255
    return c * PEAK * e // 25500


def _say(sh, s):
    try:
        (sh.say if sh is not None else print)(s)
    except Exception:
        pass


def _taken(sh):
    """Another light playback holds a light, or an update is uploading."""
    if getattr(sh, "ledtest", None) is not None:
        return True
    w = getattr(sh, "web", None)
    return w is not None and getattr(w, "ota_busy", 0)


def _charging(sh):
    b = getattr(sh, "bat", None)
    return b is not None and b[2] is True


def _pct(sh):
    b = getattr(sh, "bat", None)
    if b is None:
        return None
    return b[0]


def busy():
    """A charge-light task is running (playing or parked for a higher-priority light)."""
    return _task is not None


def _release(sh, pw):
    """Let the pins go if we still hold them. Idempotent. Returns None."""
    global _pw
    if pw is not None and sh is not None and getattr(sh, "rgb", None) is pw:
        try:
            sh.rgb = None
        except Exception:
            pass
        try:
            _off(sh, pw)
        except Exception:
            pass
    if _pw is pw:
        _pw = None
    return None


# _halt: tests (and a crash path) ask the task to end; unplug only sets _stop,
# so a quick plug after can resume the same task (start() clears _stop first).
_halt = False


def stop(sh=None, halt=False):
    """Go dark at once. If halt, the task ends (tests). Never raises. Pins are
    released now if we still hold them; the task, if any, is left running until
    it next wakes, so a start() meanwhile can resume it instead of overlapping."""
    global _stop, _halt
    try:
        _stop = True
        if halt:
            _halt = True
        _release(sh if sh is not None else _host, _pw)
    except Exception:
        pass


def start(sh):
    """main.py's charger watch: the charge breath's task on a ship with usable
    rgb_pins, once the plug-detect line is taken as plugged in. True if it was
    started or is already running. Never raises. _stop is cleared first so a
    plug that follows a just-unplugged stop() resumes the same task."""
    global _stop, _halt, _task, _host
    try:
        _stop = False
        _halt = False
        if _task is not None:
            if sh is not None:
                _host = sh
            return True
        cfg = getattr(sh, "cfg", None) or {}
        if cfg.get("rgb_pins") is None:
            return False
        ps = pins(cfg, sh.say)
        if not ps:
            return False
        if not _charging(sh):
            return False
        _host = sh
        _task = asyncio.create_task(play(sh, ps, scale(cfg)))
        return True
    except Exception as e:
        _say(sh, "led: no charge light %r" % (e,))
        try:
            _release(sh, _pw)
            _task = None
        except Exception:
            pass
        return False


async def play(sh, ps, sc):
    """The charge breath on GPIOs ps (lvrgb.pins) at brightness sc (lvrgb.scale).
    The PWMs are made here, in the task, so a coroutine that never runs holds no
    pin. Parks (all off) for a higher-priority light, or while unplugged, and
    resumes if start() has run and the ship is still charging."""
    global _task, _pw, _host
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    me = _task
    pw = None
    t0 = 0
    was_full = None
    was = [-1, -1, -1]
    try:
        _host = sh
        while not _halt:
            if _stop or not _charging(sh):
                if pw is not None:
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                if _halt:
                    break
                await sleep_ms(_WAIT)
                continue
            held = getattr(sh, "rgb", None)
            if _taken(sh) or (held is not None and held is not pw):
                if pw is not None:
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                await sleep_ms(_WAIT)
                continue
            if pw is None:
                if getattr(sh, "rgb", None) or _taken(sh):
                    await sleep_ms(_WAIT)
                    continue
                pw = _open(sh, ps)
                sh.rgb = pw
                _pw = pw
                t0 = ticks_ms()
                was_full = None
                was[0] = was[1] = was[2] = -1
                if _taken(sh) or _stop or _halt:    # marked busy, or unplugged, while we opened
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                    await sleep_ms(_WAIT)
                    continue
            t = ticks_diff(ticks_ms(), t0)
            pct = _pct(sh)
            full = pct is not None and pct >= 100
            if was_full is not None and full != was_full:
                t0 = ticks_ms()         # entering or leaving "full": start a new breath, no jump
                t = 0
            was_full = full
            k = 0
            while k < 3:                # (not range(): no object a frame)
                x = level(t, k, pct)
                if x != was[k]:
                    pw[k][1].duty_u16(duty(x, sc[k]))
                    was[k] = x
                k += 1
            await sleep_ms(_FRAME)
    except Exception as e:
        _say(sh, "led: charge light stopped %r" % (e,))
    finally:
        if pw is not None and getattr(sh, "rgb", None) is pw:
            _release(sh, pw)
        if _task is me:
            _task = None
            if _host is sh:
                _host = None
