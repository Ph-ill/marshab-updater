# The launch light (0.3.4; earlier since 0.3.5; flame + Wi-Fi since 0.3.9): when a
# ship with an RGB LED (ship.json "rgb_pins", board/lvrgb.py) is switched on, the LED
# plays a flame for about 5.6 s, then a blue breath until the hotspot is up (or a
# short green flash at once if it already is), then a short green flash, then goes
# dark. Every other ship never loads this module (main.py peeks rgb_pins, or launch()
# checks it, before importing).
# It starts on a machine.Timer (begin()), before the event loop exists, so it plays
# through the 2 s boot window and the hotspot and BLE coming up. main.py then
# attach()es the running play to the real ship, and run()'s launch() only uses
# start() (an asyncio task) if the Timer never began. start() and play() stay for
# the tests and as that fallback. Nothing waits for it, and nothing it does can
# reach the boot (begin(), start() and play() catch everything; the pins are always
# let go; stop() aborts for safe mode, /data/safe, /data/maint or Ctrl-C).
#
# The flame, LAUNCH_MS = 5600 ms from the first frame (0.3.9; was an 8 s Starship
# sequence through 0.3.8): red/orange/yellow, organic flicker (a cheap 16-bit hash
# of the time: no LCG state, no allocation, small ints only), building up then
# dying down. Same rgb_scale curve as Test light (duty() below).
#   0-5600     flame (see envelope() / level())
#   then       if the hotspot is already up: two short green flashes and dark
#              if not: a ~1 s blue breath until wifi_up(), then the green flashes
#              if the hotspot never comes: 30 s (WIFI_WAIT) of blue, two dim amber
#              blinks, dark. wifi_none() (no hotspot configured) skips this and
#              goes dark at the end of the flame.
#
# Who has the light: the launch takes the RGB LED the way a Test light does (sh.rgb),
# so a Test light tap meanwhile takes over (lvrgb._open switches the launch's PWMs
# off and this play ends without touching the new ones). It also ends at once, all
# off, when an update's upload starts (web.ota_busy), an update glow (sh.otaled) or
# any light playback is marked (sh.ledtest: a Test light, a hail's flicker); it
# never sets sh.ledtest itself, so it never makes a Test light tap wait (no 429)
# or an update wait. It doesn't start at all if one of those already holds a light.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvrgb import pins, scale, _open, _off

LAUNCH_MS = 5600
WIFI_WAIT = 30000
_FRAME = 20
# Flame envelope: (ms, 0-255 intensity), linear between. Builds, holds a peak, dies.
_E = (
    0, 20,
    180, 36,
    700, 90,
    2000, 210,
    3200, 255,
    4000, 200,
    5600, 0,
)


def envelope(t):
    """Flame intensity 0-255 at t ms, or -1 once the flame is over."""
    if t >= LAUNCH_MS or t < 0:
        return -1
    i = 0
    while _E[i + 2] <= t:
        i += 2
    a, b = _E[i + 1], _E[i + 3]
    return a + (b - a) * (t - _E[i]) // (_E[i + 2] - _E[i])


def _hash16(t, salt):
    """16-bit, two LCG steps from t and salt. Pure, small ints only, no state."""
    x = (t + salt) & 0xFFFF
    x = (x * 25173 + 13849) & 0xFFFF
    x = (x * 25173 + 13849) & 0xFFFF
    return x


def jitter(t):
    """Brightness scale 180-255 at t ms: a new value about every 40 ms."""
    return 180 + _hash16(t // 40, 17) * 76 // 65536


def hue(t):
    """Green 12-200 and a little blue 0-16 at t ms (red stays 255 before envelope)."""
    h = _hash16(t // 50, 91)
    return 12 + h * 189 // 65536, h * 16 // 65536


def duty(v, sc):
    """lvrgb.duty(v, sc), exactly, without a product over 2**30: v*v*sc*257 // 25500."""
    if v <= 0:
        return 0
    q = v * v * sc                      # at most 6,502,500
    d = q // 25500 * 257 + q % 25500 * 257 // 25500
    return 65535 if d > 65535 else d


def level(t, k):
    """Colour k's (0 red, 1 green, 2 blue) 0-255 at t ms into the flame; -1 once it's over."""
    e = envelope(t)
    if e < 0:
        return -1
    g, b = hue(t)
    v = (255, g, b)[k] * e // 255 * jitter(t) // 255
    return v if v <= 255 else 255


# The Timer play (begin / attach / stop), if one is running this boot.
_pw = None
_host = None
_t0 = 0
_was = None
_sc = None
_timer = None
_busy = False
_played = False             # begin() started once this boot (even if it has since ended)
_END = []                   # hooks, called once when that play ends or is stopped
_wifi = 0                   # 0 waiting, 1 up, 2 none configured
_up_t = 0                   # ticks when wifi_up() ran (0: never)
_tw = 0                     # ticks when the post-flame phase started (0: still in the flame)


class _Host:
    """A stand-in for the ship until attach() binds the play to the real one."""

    def __init__(self, cfg, say):
        self.cfg = cfg
        self.say = say
        self.rgb = None
        self.ledtest = None
        self.web = None


def _say(sh, s):
    try:
        (sh.say if sh is not None else print)(s)
    except Exception:
        pass


def _taken(sh):
    """Another light playback holds a light, or an update is uploading."""
    if getattr(sh, "ledtest", None) is not None:
        return True
    if getattr(sh, "otaled", None) is not None:     # an update's glow (0.3.7)
        return True
    w = getattr(sh, "web", None)
    return w is not None and getattr(w, "ota_busy", 0)


def busy():
    """A Timer play is holding the LED right now."""
    return _pw is not None


def played():
    """begin() has already started a launch this boot (it may have ended)."""
    return _played


def wifi_up():
    """The hotspot is up. After the flame, two short green flashes, then dark."""
    global _wifi, _up_t
    if _wifi == 1:
        return
    _wifi = 1
    try:
        _up_t = lvship.ticks_ms()
    except Exception:
        _up_t = 1


def wifi_none():
    """No hotspot is configured: go dark at the end of the flame, no blue wait."""
    global _wifi
    _wifi = 2


def on_end(cb):
    """Call cb once when the Timer play ends or is stopped. Never raises later from here."""
    _END.append(cb)


def _ended():
    cbs, _END[:] = _END[:], []
    for cb in cbs:
        try:
            cb()
        except Exception:
            pass


def _finish():
    """Stop the timer and release the pins if we still hold them. Idempotent."""
    global _pw, _timer, _was, _sc, _busy, _tw
    tm = _timer
    _timer = None
    if tm is not None:
        try:
            tm.deinit()
        except Exception:
            pass
    pw, sh = _pw, _host
    _pw = None
    _was = None
    _sc = None
    _tw = 0
    if pw is not None and getattr(sh, "rgb", None) is pw:
        try:
            sh.rgb = None
        except Exception:
            pass
        try:
            _off(sh, pw)
        except Exception:
            pass
    _busy = False
    _ended()


def after(dt, wifi, wait=WIFI_WAIT):
    """Post-flame colour (r, g, b) at dt ms, or None when that phase is over.
    wifi 1: two short green flashes; 2: already over; 0: blue breath for `wait`
    ms, then two dim amber blinks. Tests use this; the play path uses after_into."""
    if not after_into(dt, wifi, wait, _OUT):
        return None
    return (_OUT[0], _OUT[1], _OUT[2])


_OUT = [0, 0, 0]            # after() / the play path, reused (no per-frame tuple)


def after_into(dt, wifi, wait, out):
    """Write the post-flame colour into out (length 3). False when that phase is over."""
    if wifi == 2:
        return False
    if wifi == 1:
        if dt < 150 or 250 <= dt < 400:
            out[0], out[1], out[2] = 0, 220, 40
            return True
        if dt < 250:
            out[0], out[1], out[2] = 0, 0, 0
            return True
        return False
    if dt < wait:
        p = dt % 1000
        v = p * 200 // 500 if p < 500 else (1000 - p) * 200 // 500
        out[0], out[1], out[2] = 0, 16 + v // 10, 40 + v
        return True
    x = dt - wait
    if x < 120 or 200 <= x < 320:
        out[0], out[1], out[2] = 160, 40, 0
        return True
    if x < 200:
        out[0], out[1], out[2] = 0, 0, 0
        return True
    return False


def _post_into(now, out):
    """Write the post-flame colour into out. False if the play is over."""
    global _tw
    if _wifi == 2:
        return False
    if _tw == 0:
        _tw = now or 1
    if _wifi == 1:
        # green starts at flame-end if already up, or at wifi_up() if that was later
        t0 = _up_t if _up_t and lvship.ticks_diff(_up_t, _t0) >= LAUNCH_MS else _tw
        return after_into(lvship.ticks_diff(now, t0), 1, WIFI_WAIT, out)
    return after_into(lvship.ticks_diff(now, _tw), 0, WIFI_WAIT, out)


def _drive(pw, rgb, sc, was):
    """Write rgb (3 ints) onto pw if a channel changed. No allocation."""
    k = 0
    while k < 3:
        x = rgb[k]
        if x != was[k]:
            pw[k][1].duty_u16(duty(x, sc[k]))
            was[k] = x
        k += 1


def _frame():
    """One Timer frame. True if the play should continue. No allocation on the quiet path."""
    sh, pw = _host, _pw
    if pw is None or sh is None:
        return False
    if getattr(sh, "rgb", None) is not pw or _taken(sh):
        if _taken(sh) and getattr(sh, "rgb", None) is pw:
            _say(sh, "led: launch light gave way")
        return False
    now = lvship.ticks_ms()
    t = lvship.ticks_diff(now, _t0)
    if t < LAUNCH_MS:
        k = 0
        while k < 3:
            x = level(t, k)
            if x != _was[k]:
                pw[k][1].duty_u16(duty(x, _sc[k]))
                _was[k] = x
            k += 1
        return True
    if not _post_into(now, _OUT):
        return False
    _drive(pw, _OUT, _sc, _was)
    return True


def _on_timer(_t=None):
    global _busy
    if _busy or _pw is None:
        return
    _busy = True
    try:
        try:
            if _frame():
                return
        except Exception as e:
            _say(_host, "led: launch light stopped %r" % (e,))
        _finish()
    finally:
        _busy = False


def _make_timer():
    # tests replace this. A virtual timer: the rp2 port's only kind (as lvboot.arm).
    from machine import Timer
    return Timer(-1)


def begin(cfg, say=print, host=None):
    """Start the launch on a machine.Timer, before the event loop (0.3.5). True if it
    started (or is already playing). Never raises. A second successful begin() this boot
    is a no-op; if this boot already finished a Timer play, False."""
    global _pw, _host, _t0, _was, _sc, _timer, _played, _wifi, _up_t, _tw
    try:
        if _pw is not None:
            if host is not None:
                attach(host)
            return True
        if _played:
            return False
        if not cfg or cfg.get("rgb_pins") is None:
            return False
        ps = pins(cfg, say)
        if not ps:
            return False
        # The timer first: a missing Timer must not open pins (start() can still
        # schedule an asyncio play once the loop is up).
        tm = _make_timer()
        if host is None:
            host = _Host(cfg, say)
        if getattr(host, "rgb", None) or _taken(host):
            try:
                tm.deinit()
            except Exception:
                pass
            return False
        pw = _open(host, ps)
        host.rgb = pw
        _host, _pw, _sc = host, pw, scale(cfg)
        _was = [-1, -1, -1]
        _t0 = lvship.ticks_ms()
        _wifi, _up_t, _tw = 0, 0, 0
        _frame()                        # the first frame now, not in 20 ms
        tm.init(mode=getattr(type(tm), "PERIODIC", 1), period=_FRAME, callback=_on_timer)
        _timer = tm
        _played = True
        return True
    except Exception as e:
        _say(host if host is not None else None, "led: no launch light %r" % (e,))
        _finish()
        return False


def attach(sh):
    """Bind a running Timer play to the real ship, so a Test light can take it over.
    True if a launch is in progress."""
    global _host
    try:
        if _pw is None:
            return False
        if sh is _host:
            return True
        pw = _pw
        old = _host
        if old is not None and getattr(old, "rgb", None) is pw:
            old.rgb = None
        sh.rgb = pw
        _host = sh
        return True
    except Exception:
        return False


def stop():
    """Abort a running launch and release the pins if we still hold them. Never raises."""
    try:
        _finish()
    except Exception:
        pass


async def play(sh, ps, sc):
    """The launch on GPIOs ps (lvrgb.pins) at brightness sc (lvrgb.scale). The PWMs are made
    here, in the task, so a coroutine that never runs holds no pin."""
    global _t0, _up_t, _tw, _wifi
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    pw = None
    was = [-1, -1, -1]
    try:
        if getattr(sh, "rgb", None) or _taken(sh):
            return                      # someone else has the light: no launch this boot
        pw = _open(sh, ps)
        sh.rgb = pw
        t0 = ticks_ms()
        _t0 = t0
        _tw = 0
        while sh.rgb is pw:
            if _taken(sh):
                _say(sh, "led: launch light gave way")
                break
            now = ticks_ms()
            t = ticks_diff(now, t0)
            if t < LAUNCH_MS:
                k = 0
                while k < 3:
                    x = level(t, k)
                    if x != was[k]:
                        pw[k][1].duty_u16(duty(x, sc[k]))
                        was[k] = x
                    k += 1
            else:
                if not _post_into(now, _OUT):
                    break
                _drive(pw, _OUT, sc, was)
            await sleep_ms(_FRAME)
    except Exception as e:
        _say(sh, "led: launch light stopped %r" % (e,))
    finally:
        if pw is not None and getattr(sh, "rgb", None) is pw:  # (else a Test light took these over)
            sh.rgb = None
            _off(sh, pw)


def start(sh):
    """main.py's run(), once per boot if begin() never ran: the launch's task on a ship
    with usable rgb_pins. True if it was started, or a Timer play was already running
    (then attach() binds it). Never raises."""
    try:
        if _pw is not None:
            return attach(sh)
        cfg = getattr(sh, "cfg", None) or {}
        if cfg.get("rgb_pins") is None:
            return False
        ps = pins(cfg, sh.say)
        if not ps:
            return False
        asyncio.create_task(play(sh, ps, scale(cfg)))
        return True
    except Exception as e:
        _say(sh, "led: no launch light %r" % (e,))
        return False
