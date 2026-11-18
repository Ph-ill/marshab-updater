# The launch light (0.3.4; 0.3.5 starts it as soon as the ship can read rgb_pins): when a
# ship with an RGB LED (ship.json "rgb_pins", board/lvrgb.py) is switched on, the LED plays
# a Starship launch once, about 8 s, then goes dark. Every other ship never loads this
# module (main.py peeks rgb_pins, or launch() checks it, before importing).
# It starts on a machine.Timer (begin()), before the event loop exists, so it plays through
# the 2 s boot window and the hotspot and BLE coming up. main.py then attach()es the running
# play to the real ship, and run()'s launch() only uses start() (an asyncio task) if the
# Timer never began. start() and play() stay for the tests and as that fallback. Nothing
# waits for it, and nothing it does can reach the boot (begin(), start() and play() catch
# everything; the pins are always let go; stop() aborts for safe mode, /data/safe, /data/maint
# or Ctrl-C).
#
# The sequence, LAUNCH_MS = 8000 ms from the first frame:
#   0-1500     power on: a faint cool blue flickers on three times (onsets 450 ms apart:
#              never more than 3 a second), the third staying on
#   1500-3000  tanking: one slow breath up to a pale white-blue and back
#   3000-3600  ignition: a sudden deep orange that stutters (dips to a dim orange twice)
#   3600-6000  full thrust: ramps to a bright orange-yellow, its brightness jittering
#   6000-8000  liftoff: the flame turns white (still jittering until 7000), then fades through
#              a dimming blue to dark
#   8000       over: every duty 0, every PWM deinit'd, the pins back to inputs (lvrgb._off)
# The jitter (3600-7000) is 63-100 % of the colour's value, a new step every 60 ms, from a
# small integer hash of the time (deterministic, no state, no allocation). Each 0-255 value
# then gets lvrgb.duty's curve (v*v/65025 of full, then rgb_scale %), as the Test light does,
# worked out in small ints (duty() below, and lvrgb.duty since 0.3.5: v*v*sc*257 can pass
# 2**30, a bigint on the board, and the jitter writes nearly every frame).
#
# Who has the light: the launch takes the RGB LED the way a Test light does (sh.rgb), so a
# Test light tap meanwhile takes over (lvrgb._open switches the launch's PWMs off and this
# play ends without touching the new ones). It also ends at once, all off, when an update's
# upload starts (web.ota_busy) or any light playback is marked (sh.ledtest: a Test light, a
# hail's flicker); it never sets sh.ledtest itself, so it never makes a Test light tap wait
# (no 429) or an update wait. It doesn't start at all if one of those already holds a light.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvrgb import pins, scale, _open, _off

LAUNCH_MS = 8000
_FRAME = 20
# Keyframes, (ms, red, green, blue) each, 0-255: linear between neighbours, a jump where
# two share a time.
_K = (
    0, 0, 40, 110,          # power on: faint cool blue, three flickers
    120, 0, 40, 110,
    120, 0, 0, 0,
    450, 0, 0, 0,
    450, 0, 40, 110,
    600, 0, 40, 110,
    600, 0, 0, 0,
    900, 0, 0, 0,
    900, 0, 40, 110,
    1500, 0, 40, 110,       # tanking: a breath up to pale white-blue and back
    2250, 150, 190, 240,
    3000, 0, 40, 110,
    3000, 255, 45, 0,       # ignition: deep orange, stuttering
    3100, 255, 45, 0,
    3100, 90, 15, 0,
    3180, 90, 15, 0,
    3180, 255, 45, 0,
    3300, 255, 45, 0,
    3300, 90, 15, 0,
    3360, 90, 15, 0,
    3360, 255, 45, 0,
    3600, 255, 45, 0,       # full thrust: up to bright orange-yellow (jittering)
    4400, 255, 150, 0,
    6000, 255, 150, 0,      # liftoff: to white, through a dimming blue, to dark
    7000, 255, 235, 210,
    7500, 0, 50, 170,
    8000, 0, 0, 0,
)
_J0, _J1 = 3600, 7000       # the jitter's span

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


class _Host:
    """A stand-in for the ship until attach() binds the play to the real one."""

    def __init__(self, cfg, say):
        self.cfg = cfg
        self.say = say
        self.rgb = None
        self.ledtest = None
        self.web = None


def jitter(t):
    """The flame's brightness at t ms, 160-255 (of 255): a new value every 60 ms."""
    x = (t // 60 + 1) * 2473 & 4095     # (small ints only: no bigint on the board)
    x ^= x >> 5
    x = x * 2473 & 4095
    x ^= x >> 6
    return 160 + x * 96 // 4096


def duty(v, sc):
    """lvrgb.duty(v, sc), exactly, without a product over 2**30: v*v*sc*257 // 25500."""
    if v <= 0:
        return 0
    q = v * v * sc                      # at most 6,502,500
    d = q // 25500 * 257 + q % 25500 * 257 // 25500
    return 65535 if d > 65535 else d


def level(t, k):
    """Colour k's (0 red, 1 green, 2 blue) 0-255 at t ms into the launch; -1 once it's over."""
    if t >= LAUNCH_MS or t < 0:
        return -1
    i = 0
    while _K[i + 4] <= t:
        i += 4
    a = _K[i + 1 + k]
    v = a + (_K[i + 5 + k] - a) * (t - _K[i]) // (_K[i + 4] - _K[i])
    if _J0 <= t < _J1:
        v = v * jitter(t) // 255
    return v


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
    global _pw, _timer, _was, _sc, _busy
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


def _frame():
    """One Timer frame. True if the play should continue. No allocation on the quiet path."""
    sh, pw = _host, _pw
    if pw is None or sh is None:
        return False
    if getattr(sh, "rgb", None) is not pw or _taken(sh):
        if _taken(sh) and getattr(sh, "rgb", None) is pw:
            _say(sh, "led: launch light gave way")
        return False
    t = lvship.ticks_diff(lvship.ticks_ms(), _t0)
    if t >= LAUNCH_MS:
        return False
    k = 0
    while k < 3:                    # (not range(): no object a frame)
        x = level(t, k)
        if x != _was[k]:
            pw[k][1].duty_u16(duty(x, _sc[k]))
            _was[k] = x
        k += 1
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
    global _pw, _host, _t0, _was, _sc, _timer, _played
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
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    pw = None
    was = [-1, -1, -1]
    try:
        if getattr(sh, "rgb", None) or _taken(sh):
            return                      # someone else has the light: no launch this boot
        pw = _open(sh, ps)
        sh.rgb = pw
        t0 = ticks_ms()
        while sh.rgb is pw:
            if _taken(sh):
                _say(sh, "led: launch light gave way")
                break
            t = ticks_diff(ticks_ms(), t0)
            if t >= LAUNCH_MS:
                break
            k = 0
            while k < 3:                # (not range(): no object a frame)
                x = level(t, k)
                if x != was[k]:
                    pw[k][1].duty_u16(duty(x, sc[k]))
                    was[k] = x
                k += 1
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
