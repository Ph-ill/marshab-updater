# "Test light" (Settings > Ship light, web/settings.js; POST /api/led/test from board/main.py's
# ota_route): a signed-in crew member makes the ship's light play a short, unmistakable
# pattern, so they can see it works without opening the case. Loaded per request and dropped
# (lvship.drop); the pattern's task keeps this module's code alive for its ~4 s, then it goes.
# Shipped over the air: the frozen core (lvled, lvledcfg, lvweb, lvphone) is unchanged.
#
# The pattern, TEST_MS = 4000 ms from the tap:
#   0-1500     three bright blinks (250 ms on, 250 ms off): the LED fully on, one write each
#   1500-1800  dark
#   1800-4000  one full breath (1 s up, 1.2 s down): software PWM as lvled.py breathes, 10 ms
#              frames lit (x/100)^2 of each, the dim end a short busy-wait (under 1.5 ms),
#              the rest an await, so the web server, the DNS, the BLE sync and the charger
#              watch (main.py, every 100 ms) all run between edges
#   then dark, and the light goes back to what it was doing.
# It plays whether the Ship light is on or off. When it is on (lvled.Led), the notifier is
# held dark for the test (its pattern dropped, its next look pushed past the test) and let go
# at the end, so the two never write the pin at once; quiet hours, the budget and anything
# waiting (gift, new day) are untouched. While a BLE sync or an HTTP request is in progress
# the breath plays as a plain blink (lit through its bright middle), as lvled does.
# One at a time: a tap while it plays gets 429 {ms: left} and changes nothing.
#   200 {ok, ms}  started      401 no session      404 not POST (main.py)
#   429 {ms}      already playing                  500 no light to drive (no machine.Pin)
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship

TEST_MS = 4000
_BLINKS, _ON = 3, 250                   # blinks, ms on (and off) each
_B0, _UP, _DN = 1800, 1000, 1200        # the breath: starts at, ms up, ms down
_FRAME = 10                             # ms a frame (100 Hz), as lvled
_DIM_US = 1500                          # on parts shorter than this: a busy-wait

try:
    from time import sleep_us as _us
except ImportError:                     # CPython (the tests)
    def _us(n):
        pass


def level(t):
    """Brightness 0-100 at t ms into the test; -1 once it's over."""
    if t < 2 * _ON * _BLINKS:
        return 100 if t % (2 * _ON) < _ON else 0
    t -= _B0
    if t < 0:
        return 0
    if t < _UP:
        return t * 100 // _UP
    t -= _UP
    if t < _DN:
        return (_DN - t) * 100 // _DN
    return -1


def _pin(sh):
    f = getattr(sh, "led_pin", None)    # tests: a fake pin's factory
    if f:
        return f()
    p = getattr(sh.led, "pin", None)    # lvled.Led's own, once it has written
    if hasattr(p, "value"):
        return p
    from machine import Pin
    return Pin("LED", Pin.OUT)


def _hold(sh, let_go=False):
    # Keep lvled.Led (the Ship light, when on) dark and off the pin; let_go: look again now.
    l = sh.led
    if getattr(l, "enabled", False) and hasattr(l, "seq"):
        l.seq = None
        l.mid = l.lit = 0
        n = l.clock.uptime()
        if let_go:
            l.next = n
        elif l.next < n + 500:
            l.next = n + 500


def _busy(sh):
    return (sh.ble is not None and sh.ble.busy()) or (sh.web is not None and sh.web.busy > 0)


async def play(sh, pin):
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    t0 = ticks_ms()
    lit = 0
    try:
        while True:
            _hold(sh)
            x = level(ticks_diff(ticks_ms(), t0))
            if x < 0:
                break
            on = x * x                  # us lit in the 10 ms frame
            if x and x < 100 and _busy(sh):
                on = 10000 if x >= 50 else 0
            if on < 100 or on >= 9500:  # dark or full: one write at most
                v = 1 if on >= 100 else 0
                if v != lit:
                    pin.value(v)
                    lit = v
                await sleep_ms(_FRAME)
                continue
            pin.value(1)
            if on < _DIM_US:
                _us(on)
                pin.value(0)
                lit = 0
                await sleep_ms(_FRAME - 1)
                continue
            m = (on + 500) // 1000
            lit = 1
            await sleep_ms(m)
            pin.value(0)
            lit = 0
            await sleep_ms(_FRAME - m)
    except Exception as e:
        sh.say("led: test stopped %r" % (e,))
    finally:
        try:
            pin.value(0)
        except Exception:
            pass
        sh.ledtest = None
        _hold(sh, True)


def start(web, req):
    """POST /api/led/test (main.py has checked the method). Returns (status, obj)."""
    if web.get_phone().who(req) is None:
        return 401, {"err": "signed out"}
    sh = web.ship
    t = getattr(sh, "ledtest", None)
    if t is not None:
        left = TEST_MS - lvship.ticks_diff(lvship.ticks_ms(), t)
        if left > -5000:                # (a test that never finished can't block for good)
            return 429, {"err": "The light is already testing.", "ms": max(0, left)}
    try:
        pin = _pin(sh)
    except Exception as e:
        sh.say("led: test, no light %r" % (e,))
        return 500, {"err": "This ship's light can't be reached."}
    sh.ledtest = lvship.ticks_ms()
    asyncio.create_task(play(sh, pin))
    sh.say("led: test from a phone")
    return 200, {"ok": True, "ms": TEST_MS}
