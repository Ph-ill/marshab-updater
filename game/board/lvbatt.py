# The ship's battery (optional): a UPS-Lite v1.3 (a Raspberry Pi Zero UPS) wired to the
# Pico W, docs/BATTERY.md. Its CW2015 fuel gauge answers on I2C at 0x62; its "power
# plugged in" line (the Pi's GPIO4) goes to a spare pin. Local display only: the reading
# is never part of the choice log, the story or anything synced.
#
# Like lvledcfg, this module is loaded for a moment and dropped (lvship.Ship.bat_poll), so
# a running ship holds only ship.bat, a short list, between readings:
#   at boot     start(): one look for the gauge. Not there: ship.bat stays None, the pins
#               go back to plain inputs and nothing more runs (a board with no battery).
#   every 60 s  poll(): percent, mV, charging, from the main loop while neither the radio
#               nor the web server is busy. Each I2C transfer has a 10 ms timeout; an error
#               only means "unknown" (three in a row and the numbers go blank).
# ship.bat = [percent or None, mV or None, charging (True/False/None), SOC in 1/256 %,
#             mV smoothed, errors in a row, ticks_ms of the last reading, ms to the next,
#             I2C speed in kHz]
#            (one list, so a ship holds one attribute for all of it); /api/state sends
#            the first three ("bat").
#
# ship.json (all optional):
#   battery        "auto" (look once at boot, the default), true (always on: shows
#                  "unknown" when the gauge doesn't answer), false (never look)
#   bat_sda, bat_scl   GPIO numbers, default 4 and 5 (I2C0: Pico pins 6 and 7)
#   bat_i2c        the RP2040 I2C block for those pins, default 0
#   bat_khz        I2C speed; default: try 50 kHz, then 10 kHz (below)
#   bat_chg        the charger-detect GPIO, default 6 (Pico pin 9); -1 or null: none
#   bat_chg_pull   "down" (default), "up" or "none" for that pin
#   bat_every_s    seconds between readings, default 60
#
# The CW2015 (Cellwise datasheet CW2015CHBD v1.2; the UPS-Lite vendor script):
#   0x00 VERSION, 0x02-03 VCELL (14 bit, 305 uV a step), 0x04-05 SOC (high byte %, low
#   byte 1/256 %), 0x0A MODE (bits 7-6 sleep: 11 asleep, the power-up default; bits 5-4
#   quick start). Asleep it reports nothing new, so start() wakes it with 0x30 (awake +
#   quick start, as the vendor script does), only when it is asleep: a gauge that has been
#   running keeps its estimate across Pico restarts. Just after waking, SOC reads 0 for a
#   moment; that counts as unknown and the next look is 5 s later.
#
# No pull-up resistors needed (docs/BATTERY.md): a Raspberry Pi has 1.8 kOhm pull-ups on
# its I2C pins, so the UPS-Lite's published schematic has none of its own, and this module
# uses the RP2040's internal pull-ups (50-80 kOhm; machine.I2C on rp2 turns them on too).
# Those are far weaker than I2C's usual 4.7 kOhm, so the bus runs slowly: at 50 kHz each
# half clock is 8-12 us, and a line takes ~3 us to rise to the RP2040's 2 V input high
# with 60 kOhm and ~50 pF of short wires (~7.5 us at the worst case, 80 kOhm and 100 pF;
# the CW2015 already reads high at 1.4 V). If the gauge doesn't answer at 50 kHz the boot look tries
# 10 kHz, and three failed readings in a row also drop to 10 kHz. External 4.7 kOhm
# resistors to 3V3(OUT) still work at any speed; bat_khz pins the speed.
from lv.clock import ticks_ms

ADDR = 0x62
EVERY = 60000
# A lithium cell behind the UPS-Lite's protection reads 2.5-4.5 V. Outside that, VCELL is
# not a reading: right after a quick start the gauge answers 0 there for a moment while it
# still has an SOC, and on ship 5 that 0 was taken as the first reading, then smoothed
# towards the real 3.88 V a quarter at a time (it showed 1698 mV after two more looks).
MV_LO = 2500
MV_HI = 4500
MV_JUMP = 300           # smoothing is for Wi-Fi dips (~0.1-0.2 V); more than this: take it


def _hw(ship):
    """(bus maker, charger reader). Tests set ship.bat_hw to fakes."""
    h = getattr(ship, "bat_hw", None)
    if h:
        return h
    from machine import I2C, Pin
    c = ship.cfg

    def bus(k):
        u = Pin.PULL_UP                             # internal pull-ups, before I2C takes the pins
        return I2C(c.get("bat_i2c", 0), sda=Pin(c.get("bat_sda", 4), Pin.IN, u),
                   scl=Pin(c.get("bat_scl", 5), Pin.IN, u), freq=k * 1000, timeout=10000)

    def chg():
        p = c.get("bat_chg", 6)
        if p is None or p < 0:
            return None
        u = c.get("bat_chg_pull", "down")
        return bool(Pin(p, Pin.IN, Pin.PULL_DOWN if u == "down" else Pin.PULL_UP if u == "up" else None).value())
    return bus, chg


def _release(ship):
    """No gauge: SDA/SCL back to plain inputs, as they were before the look."""
    if getattr(ship, "bat_hw", None):
        return
    try:
        from machine import Pin
        Pin(ship.cfg.get("bat_sda", 4), Pin.IN)
        Pin(ship.cfg.get("bat_scl", 5), Pin.IN)
    except Exception:
        pass


def start(ship):
    """Boot: look for the gauge once. Returns ms until the next reading (poll)."""
    on = ship.cfg.get("battery", "auto")
    if on is False or on in ("off", "no", 0):
        return EVERY
    k = ship.cfg.get("bat_khz")
    for k in (k,) if k else (50, 10):              # weak pull-ups: slow, then slower
        try:
            bus = _hw(ship)[0](k)
            bus.readfrom_mem(ADDR, 0, 1)             # VERSION: is anyone there?
            break
        except Exception:
            bus = None
    if bus is None and on not in (True, "on"):
        _release(ship)
        return EVERY
    ship.bat = [None, None, None, 0, 0, 0, 0, 0, k]
    if bus is not None:
        try:
            if bus.readfrom_mem(ADDR, 10, 1)[0] & 0xC0:     # asleep (MODE): wake + quick start
                bus.writeto_mem(ADDR, 10, b"\x30")
                ship.say("battery: gauge woken (quick start)")
        except Exception:
            pass
    ship.say("battery: %s" % ("gauge found at 0x62, I2C %d kHz" % k if bus else "not found, battery forced on"))
    return poll(ship, bus)


def poll(ship, bus=None):
    """One reading into ship.bat. Never raises. Returns ms until the next one (also kept
    in bat[6], bat[7] for lvship's loop)."""
    b = ship.bat
    if b is None:
        return EVERY
    b[6], b[7] = ticks_ms(), _poll(ship, b, bus)
    return b[7]


def _poll(ship, b, bus):
    mk, chg = _hw(ship)
    try:
        b[2] = chg()
    except Exception:
        b[2] = None
    try:
        bus = bus or mk(b[8])
        v = bus.readfrom_mem(ADDR, 2, 2)              # VCELL
        s = bus.readfrom_mem(ADDR, 4, 2)              # SOC
        mv = ((v[0] & 0x3F) << 8 | v[1]) * 305 // 1000
        soc = min(s[0] << 8 | s[1], 25600)
        if soc == 0 and mv > 3600:                    # just woken: no estimate yet
            raise ValueError
        if not MV_LO <= mv <= MV_HI:                  # VCELL not converted yet (reads 0)
            raise ValueError
        if b[0] is None:                              # first good reading: no smoothing yet
            b[3], b[4] = soc, mv
        elif abs(mv - b[4]) > MV_JUMP:                # far off: a new level, not a dip
            b[4] = mv
        else:
            b[4] = (b[4] * 3 + mv) // 4               # Wi-Fi bursts dip the voltage
            if abs(soc - b[3]) > 160:                 # the percent moves when it has moved
                b[3] = soc
        b[0], b[1], b[5] = (b[3] + 128) >> 8, b[4], 0
    except Exception:
        b[5] += 1
        if b[5] >= 3:
            b[0] = b[1] = None
            b[8] = min(b[8], 10)                      # weak pull-ups or long wires: slower
        if b[0] is None:
            return 5000
    try:
        return max(5, int(ship.cfg.get("bat_every_s", 60))) * 1000
    except Exception:
        return EVERY


def line(ship):
    """One line for the selftest and the bench."""
    b = ship.bat
    if b is None:
        return "none detected (optional, docs/BATTERY.md)"
    c = {True: "yes", False: "no", None: "unknown"}[b[2]]
    if b[0] is None:
        return "detected, reading unknown, charging %s" % c
    return "detected, %d%%, %d mV, charging %s" % (b[0], b[1], c)
