# Test light on external red, green and blue LEDs (0.3.1, opt-in). Only a ship whose
# /data/ship.json has "rgb_pins" loads this module: lvledtest.start imports it for the
# request and drops it again; the pattern's task keeps it alive for its 10 s, then it goes.
# Every other ship never loads it and keeps the onboard LED's test exactly as before.
#
# ship.json (both optional; rgb_pins absent or null: the onboard LED, unchanged):
#   rgb_pins   [red, green, blue] RP2040 GPIO numbers, e.g. [16, 17, 18] (Pico pins 21, 22,
#              24), each LED from its pin through a resistor to GND
#   rgb_scale  [red, green, blue] brightness at full, 1-100 %, default [40, 70, 100]: red
#              on a lower resistor (200 vs 150 ohm) draws more current, and green looks
#              brighter than blue at the same current, so this evens the three out
# Refused (said, and the onboard test plays instead): not three distinct whole numbers,
# a pin outside GP0-22/26-28 (GP23-25 and 29 are the radio chip's on a Pico W), one of the
# battery's pins (bat_sda/bat_scl/bat_chg, default 4/5/6) while the battery is not off, or
# two pins on the same PWM slice and channel (GPn and GPn+16 would mirror each other).
#
# The pattern, TEST_MS = 10000 ms as the onboard test (lvledtest.level):
#   0-6000      red, then green, then blue: one breath each (1 s up, 1 s down)
#   6000-9600   all three: a colour wheel (red to green to blue to red, 1.2 s a step),
#               faded in over its first 0.4 s and out over its last 0.4 s
#   9600-10000  dark
# Real hardware PWM (machine.PWM, 1 kHz): these are RP2040 GPIOs, not the radio chip's LED,
# so a frame is three duty writes when the level changes and nothing in between; no
# busy-wait, and nothing to fall back to while a sync or a request is busy. Every frame
# (20 ms) is an await. Brightness follows a squared ramp, as lvled.py's breaths do.
# No tables and no allocation per frame: level() returns one small int per colour.
# The end, however it comes (10 s up, an error, a cancel, an update starting, a newer test
# taking over a stale one): every duty 0, every PWM deinit'd and the pins back to inputs.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvlight import _hold

TEST_MS = 10000
_FRAME = 20
SCALE = (40, 70, 100)


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
    """Colour k's (0 red, 1 green, 2 blue) brightness 0-100 at t ms; -1 once it's over."""
    if t >= TEST_MS:
        return -1
    if t < 6000:                        # one breath each, in turn
        if t // 2000 != k:
            return 0
        t %= 2000
        return t // 10 if t < 1000 else (2000 - t) // 10
    u = t - 6000
    if u >= 3600:
        return 0
    s, f = u // 1200, (u % 1200) * 100 // 1200
    x = 100 - f if s == k else f if (s + 1) % 3 == k else 0
    e = min(100, u // 4, (3600 - u) // 4)   # fade in and out, 400 ms each
    return x * e // 100


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
    """The 10 s pattern on GPIOs ps (pins()) at brightness sc (scale()). The PWMs are made
    here, in the task, so a coroutine that never runs holds no pin."""
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
                    d = x * x * sc[k] * 21 // 320      # 0-65535 (100*100*100*21/320 = 65625)
                    pw[k][1].duty_u16(65535 if d > 65535 else d)
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
            _hold(sh, True)
