# Test light on an external RGB LED (0.3.1, opt-in; the colour fade since 0.3.3). Only a ship
# whose /data/ship.json has "rgb_pins" loads this module: lvledtest.start imports it for the
# request and drops it again; the pattern's task keeps it alive for its 18 s, then it goes.
# Every other ship never loads it and keeps the onboard LED's test exactly as before (10 s).
#
# ship.json (both optional; rgb_pins absent or null: the onboard LED, unchanged):
#   rgb_pins   [red, green, blue] RP2040 GPIO numbers, e.g. [16, 17, 18] (Pico pins 21, 22,
#              24), each colour from its pin through a resistor to the common cathode on GND
#   rgb_scale  [red, green, blue] brightness at full, 1-100 %, default [100, 100, 100]:
#              full on each channel of a common-cathode RGB LED; turn one down if it
#              outshines the others
# Refused (said, and the onboard test plays instead): not three distinct whole numbers,
# a pin outside GP0-22/26-28 (GP23-25 and 29 are the radio chip's on a Pico W), one of the
# battery's pins (bat_sda/bat_scl/bat_chg, default 4/5/6) while the battery is not off, or
# two pins on the same PWM slice and channel (GPn and GPn+16 would mirror each other).
#
# The pattern, TEST_MS = 18000 ms (the onboard test stays 10 s: lvledtest.TEST_MS):
#   start on red; nine steps, each a 1 s linear fade to the next colour and a 1 s hold:
#   red, orange, yellow, green, cyan, blue, purple, pink, warm white, then back to red
#   at 18000 the test ends dark (every duty 0, as the cleanup always does)
# Real hardware PWM (machine.PWM, 1 kHz): these are RP2040 GPIOs, not the radio chip's LED,
# so a frame is three duty writes when the level changes and nothing in between; no
# busy-wait, and nothing to fall back to while a sync or a request is busy. Every frame
# (20 ms) is an await. Per-channel 0-255 value v is v²/65025 of full, then that channel's
# rgb_scale percentage. No tables and no allocation per frame: the palette is a module-level
# tuple; level() returns one small int per colour. The end, however it comes (18 s up, an
# error, a cancel, an update starting, a newer test taking over a stale one): every duty 0,
# every PWM deinit'd and the pins back to inputs.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvlight import _hold

_FADE, _HOLD = 1000, 1000
_STEP = _FADE + _HOLD                   # 2000 ms a colour: fade, then hold
# red, orange, yellow, green, cyan, blue, purple, pink, warm white, then red again
_PAL = (
    255, 0, 0,
    255, 60, 0,
    255, 160, 0,
    0, 255, 0,
    0, 255, 200,
    0, 0, 255,
    150, 0, 255,
    255, 40, 120,
    255, 200, 180,
    255, 0, 0,
)
TEST_MS = 9 * _STEP                     # 18000
_FRAME = 20
SCALE = (100, 100, 100)


def pins(cfg, say=print):
    """ship.json's rgb_pins, checked: a tuple of three GPIO numbers, or None (absent, null
    or refused: the onboard LED)."""
    p = cfg.get("rgb_pins")
    if p is None:
        return None
    try:
        if len(p) != 3:
            raise ValueError
        bad = ()
        if cfg.get("battery", "auto") is not False:
            bad = (cfg.get("bat_sda", 4), cfg.get("bat_scl", 5), cfg.get("bat_chg", 6))
        seen = 0
        for n in p:
            if isinstance(n, bool) or not isinstance(n, int) or not (0 <= n <= 22 or 26 <= n <= 28) or n in bad:
                raise ValueError
            b = 1 << (n & 15)           # its PWM slice and channel
            if seen & b:
                raise ValueError
            seen |= b
        return (p[0], p[1], p[2])
    except Exception:
        say("led: rgb_pins %r not usable (3 distinct GPIOs, not the battery's): onboard light" % (p,))
        return None


def scale(cfg):
    s = cfg.get("rgb_scale")
    try:
        if len(s) == 3 and all(not isinstance(x, bool) and isinstance(x, int) and 1 <= x <= 100 for x in s):
            return (s[0], s[1], s[2])
    except Exception:
        pass
    return SCALE


def level(t, k):
    """Colour k's (0 red, 1 green, 2 blue) 0-255 at t ms; -1 once it's over."""
    if t >= TEST_MS:
        return -1
    s = t // _STEP
    u = t - s * _STEP
    a = _PAL[s * 3 + k]
    b = _PAL[(s + 1) * 3 + k]
    if u >= _FADE:
        return b
    return a + (b - a) * u // _FADE


def duty(v, sc):
    """PWM duty 0-65535 for a 0-255 channel at scale sc (1-100 %): v²/65025 of full, then sc%.
    Same numbers as before, without a product over 2**30 (v*v*sc*257 can reach 1.67e9)."""
    if v <= 0:
        return 0
    q = v * v * sc                      # at most 6,502,500
    d = q // 25500 * 257 + q % 25500 * 257 // 25500
    return 65535 if d > 65535 else d


def _pwm(sh, n):
    f = getattr(sh, "rgb_pwm", None)    # tests: a fake PWM's factory
    if f:
        return f(n)
    from machine import Pin, PWM
    p = PWM(Pin(n))
    p.freq(1000)
    return p


def _off(sh, pw):
    for n, p in pw:
        try:
            p.duty_u16(0)
        except Exception:
            pass
        try:
            p.deinit()                  # (even when the duty write failed)
        except Exception:
            pass
        try:
            if not getattr(sh, "rgb_pwm", None):
                from machine import Pin
                Pin(n, Pin.IN)          # not driven at all, not just dark
        except Exception:
            pass


def _open(sh, ps):
    """The three PWMs, dark; a stale test's (sh.rgb) switched off first. Raises (after
    switching off what it opened) if one can't be made."""
    old = getattr(sh, "rgb", None)
    if old:
        sh.rgb = None                   # (its task sees this and ends)
        _off(sh, old)
    pw = []
    try:
        for n in ps:
            p = _pwm(sh, n)
            p.duty_u16(0)
            pw.append((n, p))
    except BaseException:
        _off(sh, pw)
        raise
    return pw


async def play(sh, ps, sc):
    """The 18 s colour fade on GPIOs ps (pins()) at brightness sc (scale()). The PWMs are
    made here, in the task, so a coroutine that never runs holds no pin."""
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    pw = None
    t0 = ticks_ms()
    was = [-1, -1, -1]
    try:
        pw = _open(sh, ps)
        sh.rgb = pw
        while sh.rgb is pw:
            _hold(sh)
            w = sh.web
            if w is not None and getattr(w, "ota_busy", 0):
                sh.say("led: test stopped for an update")
                break
            t = ticks_diff(ticks_ms(), t0)
            if level(t, 0) < 0:
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
        sh.say("led: test stopped %r" % (e,))
    finally:
        if pw is None or getattr(sh, "rgb", None) is pw:    # (else a newer test's _open() switched these off)
            if pw:
                _off(sh, pw)
            sh.rgb = None
            sh.ledtest = None
            sh.ledtest_ms = None
            _hold(sh, True)
