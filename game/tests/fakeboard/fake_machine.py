# machine for the unix port: Pin("LED") records its writes (tests/fakeboard/fakeboard.py).
# A UPS-Lite's CW2015 fuel gauge on I2C (board/lvbatt.py) when BAT["on"]: LV_FAKE_BAT=
# "PERCENT,MV,CHARGING" (e.g. 72,3950,1) in the environment, or tests set BAT directly.
import os

writes = []
_b = (os.getenv("LV_FAKE_BAT") or "").split(",")
BAT = {"on": len(_b) == 3, "soc": int(_b[0]) * 256 if len(_b) == 3 else 0,
       "mv": int(_b[1]) if len(_b) == 3 else 0, "chg": len(_b) == 3 and _b[2] == "1",
       "mode": 0xC0, "fail": False, "reads": 0}
_b = None


class Pin:
    OUT = 1
    IN = 0
    PULL_UP = 1
    PULL_DOWN = 2

    def __init__(self, name, mode=None, pull=None):
        self.name = name
        self.v = 0

    def value(self, v=None):
        if v is None:
            if self.name == 6:          # the UPS-Lite's "power plugged in" line (charger detect)
                return 1 if BAT["on"] and BAT["chg"] else 0
            return self.v
        self.v = 1 if v else 0
        writes.append(self.v)


def reset():
    raise SystemExit("machine.reset (fake board)")


def bootloader():
    raise SystemExit("machine.bootloader (fake board)")


def unique_id():
    return b"\xfa\x4e\xb0\xa2\x00\x00\x00\x01"


class I2C:
    """The CW2015 at 0x62: VERSION 0x73, VCELL (305 uV steps), SOC, MODE (asleep at power-up)."""

    def __init__(self, i, sda=None, scl=None, freq=400000, timeout=50000):
        self.i = i

    def _dev(self, addr):
        if addr != 0x62 or not BAT["on"] or BAT["fail"]:
            raise OSError(19)           # ENODEV, as an unanswered address reads on the Pico
        BAT["reads"] += 1

    def readfrom_mem(self, addr, reg, n):
        self._dev(addr)
        asleep = BAT["mode"] & 0xC0
        raw = (BAT["mv"] * 1000 // 305) & 0x3FFF
        soc = 0 if asleep else BAT["soc"]
        regs = {0: 0x73, 2: raw >> 8, 3: raw & 255, 4: soc >> 8, 5: soc & 255, 10: BAT["mode"]}
        return bytes([regs.get(reg + k, 0) for k in range(n)])

    def writeto_mem(self, addr, reg, buf):
        self._dev(addr)
        if reg == 10:
            BAT["mode"] = buf[0] & 0xC0      # wake; the quick start finishes at once here
