# The Long Voyage: deterministic game core.
# Runs unchanged on CPython 3 and MicroPython 1.29. Integer math only, no hash(),
# no dict-order dependence, no floats. Every ship computes the same story from
# the same pack + the same choice log.
#
# On the game firmware (tools/build_firmware.sh) this package is frozen into flash.
# A module can still be replaced without reflashing: put lv/<name>.mpy (or .py) in
# lvx/ on the board's filesystem (/lvx) and it is used instead of the frozen lv.<name>
# (the updater's partial releases do this). OVERRIDES lists what was replaced.
# The loader lives in the frozen lvfrozen.py (tools/fw/lvfrozen_rt.py), so it costs no
# heap; on stock MicroPython (no lvfrozen) lvx/ is ignored: replace lv/<name>.mpy itself.
# Never put a /lv directory next to the frozen package: it would hide all of it.
VERSION = "0.1.0"

try:
    import lvfrozen            # only on the game firmware (tools/fw/gen_lvfrozen.py)
except ImportError:
    lvfrozen = None
OVERRIDES = lvfrozen.overrides(globals()) if lvfrozen else []


def firmware():
    """(frozen core or None, overrides): what the game firmware froze in
    ({id, version, core, modules, shadowed}) and which lv modules /lvx replaced."""
    return (lvfrozen.firmware() if lvfrozen else None), list(OVERRIDES)


def describe():
    if lvfrozen is None:
        return "no frozen core (stock MicroPython: every module from the filesystem)"
    return lvfrozen.describe(OVERRIDES)
