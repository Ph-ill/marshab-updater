# The launch light (0.3.4): when a ship with an RGB LED (ship.json "rgb_pins", board/lvrgb.py)
# is switched on, the LED plays a Starship launch once, about 8 s, then goes dark. Every
# other ship never loads this module (main.py's launch() checks rgb_pins first).
# main.py's run() starts it as its own task before the web server, so the web server, the
# captive DNS and the BLE sync come up while it plays: nothing waits for it, and nothing it
# does can reach the boot (start() and play() catch everything; the pins are always let go).
#
# The sequence, LAUNCH_MS = 8000 ms from the task's first frame:
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
# worked out in small ints (duty() below: lvrgb.duty's v*v*sc*257 can pass 2**30, a bigint on
# the board, and the jitter writes nearly every frame).
#
# Who has the light: the launch takes the RGB LED the way a Test light does (sh.rgb), so a
# Test light tap meanwhile takes over (lvrgb._open switches the launch's PWMs off and this
# task ends without touching the new ones). It also ends at once, all off, when an update's
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
        sh.say(s)
    except Exception:
        pass


def _taken(sh):
    """Another light playback holds a light, or an update is uploading."""
    if getattr(sh, "ledtest", None) is not None:
        return True
    w = getattr(sh, "web", None)
    return w is not None and getattr(w, "ota_busy", 0)


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
    """main.py's run(), once per boot: the launch's task on a ship with usable rgb_pins.
    True if it was started. Never raises."""
    try:
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
