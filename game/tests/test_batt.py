# The ship's battery (board/lvbatt.py: a UPS-Lite's CW2015 fuel gauge on I2C, its charger
# line on a pin) against a fake gauge: present, absent, erroring, charging, waking from
# sleep, smoothing, forced on, switched off, and the selftest/bench line. Then the real
# lvship.Ship on the fake board (tests/fakeboard): /api/state's "bat" and lvbatt dropped
# after each use. Runs on CPython and MicroPython (tests/run.sh runs both).
import sys

sys.path.insert(0, "board")
sys.path.insert(0, ".")
import lvbatt

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


class Gauge:
    """A CW2015 at 0x62 (registers as in the datasheet); fail=True: every transfer errors."""

    def __init__(self, pct=72, mv=3950, mode=0xC0):
        self.soc, self.mv, self.mode = pct * 256, mv, mode
        self.fail = False
        self.writes = []
        self.reads = 0
        self.chg = False
        self.chg_fail = False
        self.made = 0

    def bus(self):
        self.made += 1
        return self

    def charging(self):
        if self.chg_fail:
            raise OSError(5)
        return self.chg

    def readfrom_mem(self, addr, reg, n):
        if self.fail or addr != 0x62:
            raise OSError(19)
        self.reads += 1
        raw = (self.mv * 1000 // 305) & 0x3FFF
        soc = 0 if self.mode & 0xC0 else self.soc
        r = {0: 0x73, 2: raw >> 8, 3: raw & 255, 4: soc >> 8, 5: soc & 255, 10: self.mode}
        return bytes([r.get(reg + k, 0) for k in range(n)])

    def writeto_mem(self, addr, reg, buf):
        if self.fail:
            raise OSError(19)
        self.writes.append((reg, bytes(buf)))
        if reg == 10:
            self.mode = buf[0] & 0xC0


class Ship:
    def __init__(self, g, **cfg):
        self.cfg = cfg
        self.bat = None
        self.said = []
        if g is not None:
            self.bat_hw = (g.bus, g.charging)

    def say(self, s):
        self.said.append(s)


# -- absent: one look at boot, then nothing
g = Gauge()
g.fail = True
s = Ship(g)
check("absent start", lvbatt.start(s) == 60000 and s.bat is None)
check("absent quiet", s.said == [], s.said)
check("absent poll no-op", lvbatt.poll(s) == 60000 and s.bat is None and g.made == 1)
check("absent line", lvbatt.line(s).startswith("none detected"))

# -- switched off in ship.json: not even a look
for off in (False, "off", "no", 0):
    g = Gauge()
    s = Ship(g, battery=off)
    check("off %r" % (off,), lvbatt.start(s) == 60000 and s.bat is None and g.made == 0 and g.reads == 0)

# -- present, asleep at power-up: woken once with 0x30, first SOC 0 = unknown, then a reading
g = Gauge(72, 3950)
s = Ship(g)
nxt = lvbatt.start(s)
check("woken", g.writes == [(10, b"\x30")], g.writes)
check("woken said", "battery: gauge woken (quick start)" in s.said and "battery: gauge found at 0x62" in s.said, s.said)
check("present", s.bat is not None and s.bat[0] == 72 and s.bat[2] is False, s.bat)
check("mV", s.bat[1] in (3949, 3950), s.bat)
check("every 60 s", nxt == 60000, nxt)
check("line", lvbatt.line(s) == "detected, 72%%, %d mV, charging no" % s.bat[1], lvbatt.line(s))

# -- already awake (a Pico restart while the UPS stayed on): no quick start, estimate kept
g = Gauge(55, 3800, mode=0)
s = Ship(g)
lvbatt.start(s)
check("awake: no write", g.writes == [] and s.bat[0] == 55, (g.writes, s.bat))

# -- just woken: SOC 0 with a full-looking cell is "not ready": unknown, 5 s retry
g = Gauge(80, 4000, mode=0)
g.soc = 0
s = Ship(g)
check("not ready retry", lvbatt.start(s) == 5000 and s.bat[0] is None and s.bat[1] is None, s.bat)
check("not ready line", lvbatt.line(s) == "detected, reading unknown, charging no", lvbatt.line(s))
g.soc = 80 * 256
check("ready", lvbatt.poll(s) == 60000 and s.bat[0] == 80, s.bat)
# a really empty cell does read 0%: low voltage, so it counts
g = Gauge(0, 3400, mode=0)
s = Ship(g)
lvbatt.start(s)
check("empty is 0%", s.bat[0] == 0, s.bat)

# -- charging: the charger line
g = Gauge(40, 3900, mode=0)
g.chg = True
s = Ship(g)
lvbatt.start(s)
check("charging", s.bat[2] is True and lvbatt.line(s).endswith("charging yes"), s.bat)
g.chg = False
lvbatt.poll(s)
check("unplugged", s.bat[2] is False, s.bat)
g.chg_fail = True
lvbatt.poll(s)
check("charger unknown", s.bat[2] is None and s.bat[0] == 40, s.bat)
check("charger unknown line", lvbatt.line(s).endswith("charging unknown"), lvbatt.line(s))

# -- smoothing: the voltage is averaged (Wi-Fi bursts), the percent moves past 0.6 %
g = Gauge(60, 3900, mode=0)
s = Ship(g)
lvbatt.start(s)
g.mv = 3700                                   # a dip under load
lvbatt.poll(s)
check("mV smoothed", 3840 <= s.bat[1] <= 3860, s.bat)
g.soc = 60 * 256 + 100                        # +0.4 %: held
lvbatt.poll(s)
check("pct held", s.bat[0] == 60 and s.bat[3] == 60 * 256, s.bat)
g.soc = 59 * 256 - 10                         # -1 %: moves
lvbatt.poll(s)
check("pct moves", s.bat[0] == 59, s.bat)
g.soc = 120 * 256                             # nonsense above 100 %: capped
lvbatt.poll(s)
check("pct capped", s.bat[0] == 100, s.bat)

# -- erroring: two misses keep the last numbers, the third blanks them; it comes back
g = Gauge(66, 3880, mode=0)
s = Ship(g)
lvbatt.start(s)
g.fail = True
check("miss 1", lvbatt.poll(s) == 60000 and s.bat[0] == 66 and s.bat[5] == 1, s.bat)
check("miss 2", lvbatt.poll(s) == 60000 and s.bat[0] == 66, s.bat)
check("miss 3 unknown", lvbatt.poll(s) == 5000 and s.bat[0] is None and s.bat[1] is None, s.bat)
check("unknown keeps polling", lvbatt.poll(s) == 5000, s.bat)
g.fail = False
check("back", lvbatt.poll(s) == 60000 and s.bat[0] == 66 and s.bat[5] == 0, s.bat)

# -- forced on with no gauge: shows "unknown", never raises
g = Gauge()
g.fail = True
s = Ship(g, battery=True)
check("forced", lvbatt.start(s) == 5000 and s.bat is not None and s.bat[0] is None, s.bat)
check("forced said", "battery: not found, battery forced on" in s.said, s.said)

# -- a bad bat_every_s and a short one
g = Gauge(50, 3800, mode=0)
s = Ship(g, bat_every_s="soon")
check("bad every", lvbatt.start(s) == 60000)
s = Ship(Gauge(50, 3800, mode=0), bat_every_s=1)
check("min every", lvbatt.start(s) == 5000)

# -- a bus that can't even be made (bad pins in ship.json): absent
def nobus():
    raise ValueError("bad pin")


s = Ship(None)
s.bat_hw = (nobus, lambda: False)
check("no bus", lvbatt.start(s) == 60000 and s.bat is None)

print("test_batt: %d checks ok" % ok[0])
