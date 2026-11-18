# The update light (0.3.7): while a ship with an RGB LED (ship.json "rgb_pins",
# board/lvrgb.py) is taking an over-the-air update, the LED shows a distinct blue
# glow so someone nearby can see it is updating and should not switch it off.
# Every other ship never loads this module (the hook checks rgb_pins before
# importing). It never sets sh.ledtest, so an update's own pieces are not held
# off by lvotaq.lit; Test light and a hail see sh.otaled and stand aside.
#
# Phases:
#   recv    a fast ~1 s violet-blue pulse while the phone is sending the envelope
#           and the files (POST /api/ota/put). Stays lit between pieces (ota_busy
#           falls in those gaps; this flag does not).
#   apply   a slower pale white-blue breath once apply() has handed the staged
#           update to lvboot (~1.5 s to the restart). "Don't switch off."
#   off     a 403 (the signature or the manifest refused the set), a successful
#           cancel, a stale gap with no piece for STALE_MS, or an error hook;
#           pins released, sh.otaled cleared, the charge light may resume.
#
# What this light cannot cover (the running set is the one that drives it):
#   * installing this release itself, if the ship is still on an older set
#   * the 0.3.1-updater stepping stone (already published; this module is not in it)
#   * after the restart: boot.py / lvboot.py swap the files (not in the OTA set);
#     the new set's launch light then plays as usual
#   * the last envelope piece's signature check is blocking, so a frame may freeze
#     for a moment; the hook also waits until that check has returned 200 before
#     first starting, so the heap at that tight moment does not hold this module
#
# Integer-only, no allocation on the quiet path, lvrgb.duty's small-int split,
# 25 fps asyncio (FRAME = 40 ms). It takes the RGB LED (sh.rgb) and will _open
# over a charge or launch play. Never raises from hook() / start() / stop().
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship
from lvrgb import pins, scale, duty, _open, _off

RECV, APPLY = "recv", "apply"
PERIOD_RECV = 1000
PERIOD_APPLY = 2800
_FRAME = 40
_WAIT = 100
STALE_MS = 120000           # no piece for this long in recv: go dark
APPLY_STALE_MS = 30000      # apply should restart in ~1.5 s; a stuck glow gives up
PEAK_RECV = 140             # 0-255 peak of the receive pulse
APPLY_BASE = 50             # dim floor of the apply breath (never goes dark)
APPLY_SWING = 90
# violet-blue (recv), pale white-blue (apply)
_RECV = (70, 0, 255)
_APPLY = (180, 210, 255)

_task = None
_stop = False
_halt = False
_pw = None
_host = None
_phase = RECV
_poke = 0


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


def level(t, k, phase):
    """Colour k's 0-255 at t ms into this play, for phase 'recv' or 'apply'."""
    if phase == APPLY:
        c = _APPLY[k]
        e = env(t, PERIOD_APPLY)
        return c * (APPLY_BASE + APPLY_SWING * e // 100) // 255
    c = _RECV[k]
    return c * PEAK_RECV * env(t, PERIOD_RECV) // 25500


def _say(sh, s):
    try:
        (sh.say if sh is not None else print)(s)
    except Exception:
        pass


def busy():
    """An update-light task is running (playing or parked)."""
    return _task is not None


def phase():
    return None if _stop or _task is None else _phase


def _release(sh, pw):
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


def _mark(sh, ph):
    try:
        if sh is not None:
            sh.otaled = ph
    except Exception:
        pass


def _unmark(sh):
    try:
        if sh is not None and getattr(sh, "otaled", None):
            sh.otaled = None
    except Exception:
        pass


def stop(sh=None, halt=False):
    """Go dark at once. If halt, the task ends (tests). Never raises."""
    global _stop, _halt
    try:
        _stop = True
        if halt:
            _halt = True
        host = sh if sh is not None else _host
        _unmark(host)
        _release(host, _pw)
    except Exception:
        pass


def start(sh, phase=RECV):
    """Show the update light in this phase. True if it was started or is already
    running. Never raises. A running play just changes phase and is poked so the
    stale timer restarts."""
    global _stop, _halt, _task, _host, _phase, _poke
    try:
        if phase not in (RECV, APPLY):
            phase = RECV
        _stop = False
        _halt = False
        _phase = phase
        _poke = lvship.ticks_ms()
        cfg = getattr(sh, "cfg", None) or {}
        if cfg.get("rgb_pins") is None:
            return False
        ps = pins(cfg, sh.say)
        if not ps:
            return False
        _host = sh
        _mark(sh, phase)
        if _task is not None:
            return True
        _task = asyncio.create_task(play(sh, ps, scale(cfg)))
        return True
    except Exception as e:
        _say(sh, "led: no update light %r" % (e,))
        try:
            _unmark(sh)
            _release(sh, _pw)
            _task = None
        except Exception:
            pass
        return False


def hook(sh, phase=None):
    """main.py / lvota / lvotap: 'recv', 'apply', or None to stop. Never raises.
    No-op without rgb_pins (the module is not imported by the caller if they
    check first; this also refuses them)."""
    try:
        if phase is None:
            stop(sh)
            return
        start(sh, phase)
    except Exception:
        pass


async def play(sh, ps, sc):
    """The update glow on GPIOs ps at brightness sc. The PWMs are made here, in
    the task, so a coroutine that never runs holds no pin. Takes the LED even if
    a charge or launch play already holds it (this light has priority)."""
    global _task, _pw, _host, _phase, _stop
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    me = _task
    pw = None
    t0 = 0
    was_ph = None
    was = [-1, -1, -1]
    try:
        _host = sh
        while not _halt:
            # stop() releases pins at once so the glow goes dark without waiting
            # for this frame. If start() then clears _stop before we notice, the
            # local handle still points at the deinit'd PWMs — drop it and
            # re-open rather than writing them (ValueError would end the task).
            if pw is not None and pw is not _pw:
                pw = None
                was[0] = was[1] = was[2] = -1
            if _stop:
                if pw is not None:
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                _unmark(sh)
                if _halt:
                    break
                await sleep_ms(_WAIT)
                continue
            # recv with no piece for STALE_MS: the phone walked away
            stale = STALE_MS if _phase == RECV else APPLY_STALE_MS
            if _poke and ticks_diff(ticks_ms(), _poke) >= stale:
                _stop = True
                _unmark(sh)
                if pw is not None:
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                await sleep_ms(_WAIT)
                continue
            if pw is None:
                pw = _open(sh, ps)          # takes the LED from a charge/launch play
                sh.rgb = pw
                _pw = pw
                t0 = ticks_ms()
                was_ph = None
                was[0] = was[1] = was[2] = -1
                if _stop or _halt:
                    pw = _release(sh, pw)
                    was[0] = was[1] = was[2] = -1
                    await sleep_ms(_WAIT)
                    continue
            ph = _phase
            if was_ph is not None and ph != was_ph:
                t0 = ticks_ms()
                t = 0
            else:
                t = ticks_diff(ticks_ms(), t0)
            was_ph = ph
            k = 0
            while k < 3:                # (not range(): no object a frame)
                x = level(t, k, ph)
                if x != was[k]:
                    pw[k][1].duty_u16(duty(x, sc[k]))
                    was[k] = x
                k += 1
            await sleep_ms(_FRAME)
    except Exception as e:
        _say(sh, "led: update light stopped %r" % (e,))
    finally:
        if pw is not None and getattr(sh, "rgb", None) is pw:
            _release(sh, pw)
        _unmark(sh)
        if _task is me:
            _task = None
            if _host is sh:
                _host = None
