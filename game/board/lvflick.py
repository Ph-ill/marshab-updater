# The hail light (lvlive.py's flick): when a crewmate's hail arrives, the ship's light
# flickers for FLICK_MS so someone nearby knows to look.
# Loaded for the start and dropped (lvship.drop); the task keeps the code alive for its ~10 s.
#   * 3 Hz at most (167 ms on, 167 ms off, full on/off writes: no PWM, no busy-wait; under
#     the 3 flashes a second of the photosensitivity guidelines, WCAG 2.3.1); it
#     only ever lights at the start of an "on" half, so a link starting and stopping
#     meanwhile can't make it switch faster.
#   * It waits (up to WAIT_MS) until no BLE link or HTTP request is in progress, since it
#     usually starts in the middle of the sync that brought the item, and pauses dark while
#     one runs.
#   * The Ship light (lvled.Led, if on) is held dark meanwhile exactly as "Test light" does
#     (lvledtest._hold: a light it left on mid-pattern goes dark at once), the pin is
#     written dark before the wait, and sh.ledtest is set, so a test tap meanwhile gets a
#     429 and the two never write the pin at once.
# maybe() checks first: the hail light switch (Settings, "Flicker for hails": its own,
# on unless switched off, whether or not the Ship light is on: FIXREVIEW2 J5), a known
# clock (a phone's, since the start), quiet hours, the daily allowance (lvlive.LIGHTS, 12)
# and that no test is playing.
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvship

FLICK_MS = 10000
HALF = 167              # ms on, then ms off: 3 Hz
WAIT_MS = 30000


async def play(sh, pin, T):
    sleep_ms, ticks_ms, ticks_diff = lvship.sleep_ms, lvship.ticks_ms, lvship.ticks_diff
    t0 = ticks_ms()
    lit = 0
    try:
        T._hold(sh)
        pin.value(0)            # (dark from the start, whatever was lit before)
        while T._busy(sh) and ticks_diff(ticks_ms(), t0) < WAIT_MS:
            T._hold(sh)
            await sleep_ms(200)
        t0 = ticks_ms()
        dark = -1
        while True:
            T._hold(sh)
            t = ticks_diff(ticks_ms(), t0)
            if t >= FLICK_MS:
                break
            k = t // HALF
            if T._busy(sh):
                dark = k        # a link or a request: dark for the rest of this half too,
            # so a busy flag that comes and goes can never flicker it faster than 3 Hz
            v = 1 if k % 2 == 0 and k != dark else 0
            if v != lit:
                pin.value(v)
                lit = v
            await sleep_ms(25)
    except Exception as e:
        sh.say("led: hail light stopped %r" % (e,))
    finally:
        try:
            pin.value(0)
        except Exception:
            pass
        sh.ledtest = None
        T._hold(sh, True)


def led_busy(sh):
    """Is a light playback (Test light, or this flicker) still running? sh.ledtest holds its
    start, counted as Test light's (TEST_MS long); like the 429 in lvledtest.start and
    main.py, a mark more than 5 s past its end is stale (a task that never ran its finally)
    and is cleared rather than holding the light off for good."""
    t = getattr(sh, "ledtest", None)
    if t is None:
        return False
    if 10000 - lvship.ticks_diff(lvship.ticks_ms(), t) > -5000:
        return True
    sh.ledtest = None
    return False


def maybe(lk):
    """lvlive's Link.flick: the light for a hail that just arrived, if it may play."""
    sh = lk.sh
    c = sh.clock
    m, d = c.minute(), c.date()
    v = lk.cfg.get("light", True)       # its own switch, on unless set off (FIXREVIEW2 J5)
    if not v or m is None or not c.known():
        return False
    q = getattr(sh.led, "q", None) or (1320, 420)
    if (m >= q[0] or m < q[1]) if q[0] > q[1] else q[0] <= m < q[1]:
        return False
    if lk.lc[0] != d:
        lk.lc = [d, 0]
    import lvlive
    if lk.lc[1] >= lvlive.LIGHTS or led_busy(sh):
        return False
    lk.lc[1] += 1
    return start(sh)


def start(sh):
    import lvlight as T
    try:
        pin = T._pin(sh)
    except Exception as e:
        sh.say("led: hail light, no light %r" % (e,))
        return False
    # Counts as a test for the 429 (its ms: the wait plus the flicker, at most).
    try:
        from time import ticks_add
    except ImportError:                  # CPython (the tests)
        def ticks_add(a, b):
            return a + b
    # The task first, the busy mark after (as lvledtest.start): if building the coroutine
    # or the task fails (a MemoryError with the heap at its tightest), nothing is left
    # marked busy. The mark is set before the task first runs (create_task only schedules
    # it); play() clears it in its finally.
    try:
        c = play(sh, pin, T)
        asyncio.create_task(c)
    except Exception as e:
        c = None
        sh.ledtest = None
        sh.say("led: hail light, no task %r" % (e,))
        return False
    finally:
        lvship.drop("lvlight")           # the task holds only the shared helpers
    sh.ledtest = ticks_add(lvship.ticks_ms(), WAIT_MS + FLICK_MS - T.TEST_MS)
    # Which playback owns the mark (review 3 m2): Test light's 429 says "kind": "hail" while
    # sh.ledhail is the same mark, so the page can say the light is showing a hail instead
    # of "three blinks" (any later mark, or none, isn't this one: nothing to clear).
    sh.ledhail = sh.ledtest
    return True
