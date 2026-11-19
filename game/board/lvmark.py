# A RAM marker that survives a soft reset (Ctrl-D, mpremote) and a watchdog
# reboot, and is cleared by a power-on or RUN-pin reset. The launch light plays
# on a real start and not again in the same power cycle. 0.3.9 used
# ticks_ms() > 400 at main() for this, the same rule as lvboot.soft() — but
# that rule is only true in boot.py, which runs ~25 ms after a real start.
# By the time main.py has imported and start_launch() runs, a cold boot is
# already past 400 ms (firmware, boot.py, frozen imports), so every power-on
# was treated as a soft reset and the light never played.
#
# Hardware (Pico W / Pico 2 W): the RP2040/RP2350 watchdog scratch registers.
# pico-sdk hardware/regs/watchdog.h: "Scratch register. Information persists
# through soft reset of the chip." RESET value 0 (power-on and RUN).
# WATCHDOG_BASE is 0x40058000 on RP2040 and 0x400D8000 on RP2350; SCRATCH0
# is at +0x0C, SCRATCH1 at +0x10. pico-sdk and the bootrom use scratch[4..7]
# for watchdog_reboot / a bootrom handshake (watchdog.c: scratch[4] =
# 0xb007c0d3, or 0 for a regular flash reboot). MicroPython's machine.reset()
# is watchdog_reboot(0, SRAM_END, 0), which writes scratch[4] only, so
# scratch[0] and scratch[1] survive it — clear() must run before a reset
# that should play the light (an update, a crash restart). This project
# does not write machine.mem_backup; if a firmware includes that view, it
# only maps the same words.
#
# Failure mode is "the light plays", never "no light": present() is True only
# when both words hold our magic and its complement; a failed read, a
# missing machine.mem32, an unknown chip, or garbage, all return False.

# Tests may replace mem32 (a mapping of word address -> value) and BASE.
mem32 = None
BASE = None

MAGIC = 0x4C564C31          # 'LVL1'
MASK = 0xFFFFFFFF
RP2040 = 0x40058000
RP2350 = 0x400D8000
SCRATCH0 = 0x0C
SCRATCH1 = 0x10


def _uname_machine():
    try:
        import os
        return os.uname().machine
    except Exception:
        pass
    try:
        import sys
        return getattr(sys.implementation, "_machine", "") or ""
    except Exception:
        return ""


def detect_base(machine=""):
    """Watchdog base for this chip, or None if we must not poke an address."""
    if BASE is not None:
        return BASE
    # A test that injected mem32 and left BASE alone uses the RP2040 layout.
    if mem32 is not None and not machine:
        return RP2040
    m = (machine or _uname_machine()).upper()
    # "Pico 2" / RP2350 first: "Pico 2 W" also contains "Pico".
    if "RP2350" in m or "PICO 2" in m or "PICO2" in m:
        return RP2350
    if "RP2040" in m or "PICO" in m:
        return RP2040
    return None


def _mem():
    m = mem32
    if m is not None:
        return m
    import machine
    return machine.mem32


def _words():
    b = detect_base()
    if b is None:
        return None
    return b + SCRATCH0, b + SCRATCH1


def present():
    """True only when this power cycle already left our marker."""
    try:
        import sys
        if sys.platform != "rp2" and mem32 is None:
            return False
        w = _words()
        if w is None:
            return False
        m = _mem()
        a = int(m[w[0]]) & MASK
        b = int(m[w[1]]) & MASK
        return a == MAGIC and b == (MAGIC ^ MASK)
    except Exception:
        return False


def mark():
    """Leave a marker a later soft reset in this power cycle can see."""
    try:
        w = _words()
        if w is None:
            return
        m = _mem()
        m[w[0]] = MAGIC
        m[w[1]] = MAGIC ^ MASK
    except Exception:
        pass


def clear():
    """Drop the marker so the next machine.reset() plays the light."""
    try:
        w = _words()
        if w is None:
            return
        m = _mem()
        m[w[0]] = 0
        m[w[1]] = 0
    except Exception:
        pass
