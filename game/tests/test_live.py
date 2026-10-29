#!/usr/bin/env python3
"""Ship-to-ship items (board/lvlive.py, lvliveapi.py, lvflick.py) on the fake radio
(tests/fakeble), through the real lv/ble.py and lv/sync.py of the frozen core.
  * install: on by default; off by live.json, after a fault (fault.json) until a phone turns
    it back on, with no Bluetooth or a changed core; the advert says "reads items".
  * delivery: a hail from ship 1 reaches ship 2 by a direct dial (the logs match, so no
    ordinary sync would happen), is acked once, shows "Delivered", "seen" travels back;
    a repeat is not taken twice; an old ship (no Link) syncs as before and gets nothing.
  * will deliver: ship 2 out of range: two dials, then one a minute while heard, and the
    normal sync's backoff is put back as it was.
  * fair use: one undelivered hail per crewmate, the 2 min gap, 20 a day; hail back.
  * the radio: one hail dial per 20 s across peers, only to ships heard in the last 30 s.
  * the light: quiet hours, the clock, the switch, 12 a day, never two at once.
  * a fault in a hook: hooks off, live.json says why, the sync carries on.
  * fuzz: random and mutated trailers never raise and never take a bad item; well-signed
    items with random kinds and bodies (a later release, a buggy ship) never upset the page.
  * kill switches: lvlive.ON (fleet-wide, by release), the Settings switch, the fault net.
  * coexistence: no hail dial while the web server is mid-answer or an update is arriving;
    the radio test's probe (/api/coex/ping) streams what it says.
Runs on CPython and on the MicroPython unix ports:  python3 tests/test_live.py  (from game/)"""
import json
import os
import sys

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except AttributeError:          # MicroPython: no os.path
    HERE = "tests"
ROOT = HERE.rsplit("/", 1)[0] if "/" in HERE else "."
sys.path[:0] = [ROOT, ROOT + "/board", HERE + "/fakeble"]
try:
    os.chdir(ROOT)
except OSError:
    pass

import bluetooth                 # noqa: E402  (the fake)
from lv import sync as S         # noqa: E402
from lv.chlog import ChoiceLog   # noqa: E402
from lv.ble import BleSync       # noqa: E402
from lv.clock import Clock       # noqa: E402
import lvlive                    # noqa: E402
import lvlivein                  # noqa: E402
import lvliveapi                 # noqa: E402

FK = b"test-fleet-key-not-secret"
TMP = "/tmp/lvlive_test"
PHONE_MS = 1792936800000         # 2026-10-25 09:00 CDT
n = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    n[0] += 1


def rm_tree(d):
    try:
        names = os.listdir(d)
    except OSError:
        return
    for f in names:
        p = d + "/" + f
        try:
            os.remove(p)
        except OSError:
            rm_tree(p)
    try:
        os.rmdir(d)
    except OSError:
        pass


def mkdir(d):
    try:
        os.mkdir(d)
    except OSError:
        pass


class Led:
    q = (1320, 420)
    enabled = True          # (the Ship light on: the hail light follows it unless set)


class Sh:
    """The parts of lvship.Ship that lvlive and lvliveapi use."""
    def __init__(self, world, ship, data, live=True):
        self.fk = FK
        self.log = ChoiceLog(FK)
        self.node = S.Node(self.log, ship, FK, 3)
        self.radio = world.new()
        self.ble = BleSync(self.node, self.radio, {"scan_every_ms": 6000, "scan_ms": 3000})
        self.clock = Clock()
        self.clock.learn(PHONE_MS, -300)
        self.led = Led()
        self.data = data
        self.web = None
        self.ledtest = None
        self.live = None
        self.lines = []
        self.flicks = 0
        self.v = 0
        mkdir(data)
        if live:
            lvlive.install(self, data)

    def say(self, t):
        self.lines.append(t)

    def day_check(self):
        return False

    def poll(self, now):
        if self.radio.on:
            self.ble.poll(now)


def run(world, ships, ms, until=None):
    t = 0
    while t < ms:
        world.step(10)
        t += 10
        for s in ships:
            s.poll(world.now)
        if until is not None and t % 100 == 0 and until():
            return t
    return None


class Req:
    def __init__(self, path, method="GET", body=None, who=0):
        self.path, self.method = path, method
        self.body = json.dumps(body).encode() if body is not None else None
        self.w = who
        self.q = {}

    def header(self, k):
        return None


class Phone:
    def who(self, req):
        return req.w


class Web:
    def __init__(self, sh):
        self.ship = sh
        self.ph = Phone()
        self.served = self.refused = self.busy = 0

    def get_phone(self):
        return self.ph


def api(sh, path, method="GET", body=None, who=None):
    return lvliveapi.api(Web(sh), Req(path, method, body, sh.node.ship if who is None else who))


def fresh(seed, k=2, live=(True, True)):
    rm_tree(TMP)
    mkdir(TMP)
    w = bluetooth.World(seed)
    return w, [Sh(w, i, "%s/s%d" % (TMP, i), live[i]) for i in range(k)]


# ---- install
w, (a, b) = fresh(1)
check("on by default", a.live is not None and b.live is not None and a.live_why is None)
check("advert cap bit", a.node.advert()[5] & lvlive.CAP and a.node.advert()[5] & 15 == 0)
i = S.parse_advert(S.adv_data(a.node.advert()))
check("parse sees cap", i is not None and i["cap"] and i["ship"] == 0 and not i["busy"], i)
rm_tree(TMP)
mkdir(TMP)
mkdir(TMP + "/x")
lvlivein.save(TMP + "/x/live.json", {"on": False, "why": "turned off"})
s = Sh(bluetooth.World(2), 0, TMP + "/x")
check("off by live.json", s.live is None and s.live_why == "turned off")
mkdir(TMP + "/y")
# 0.3.0 review R2 M3: a crash that didn't run through Hail's code (a web server MemoryError,
# a story bug) leaves Hail on, and the advert says so
with open(TMP + "/y/fault.json", "w") as f:
    f.write('{"n": 1, "why": "MemoryError: x", "up": 5}')
s = Sh(bluetooth.World(3), 0, TMP + "/y")
check("R2 M3: a crash outside Hail: stays on", s.live is not None and s.live_why is None, s.live_why)
check("R2 M3: ... live.json untouched", lvlivein.load(TMP + "/y/live.json") is None)
with open(TMP + "/y/fault.json", "w") as f:
    f.write('{"n": 1, "why": "x", "up": 5, "live": 1}')
s = Sh(bluetooth.World(3), 0, TMP + "/y")
check("off after a fault", s.live is None and "fault" in s.live_why, s.live_why)
check("fault noted", lvlivein.load(TMP + "/y/live.json")["on"] is False)
st, j = api(s, "/api/live")
check("api when off", st == 200 and j["on"] is False and "fault" in j["why"], j)
st, j = api(s, "/api/live/set", "POST", {"on": True})
check("turned back on", st == 200 and j["on"] and s.live is not None, j)
s2 = Sh(bluetooth.World(4), 0, TMP + "/y")
check("stays on after that fault", s2.live is not None, s2.live_why)
with open(TMP + "/y/fault.json", "w") as f:
    f.write('{"n": 1, "why": "another", "up": 9, "live": 1}')
s3 = Sh(bluetooth.World(5), 0, TMP + "/y")
check("a new fault: off again", s3.live is None)
st, j = api(s3, "/api/live/hail", "POST", {"to": 1})
check("hail when off: 409", st == 409, (st, j))
st, j = api(s3, "/api/live", who=None)
st2, j2 = lvliveapi.api(Web(s3), Req("/api/live", who=None))
check("signed out: 401", st2 == 401)
st, j = lvliveapi.api(Web(s3), Req("/api/coex", who=None))
check("R3 m3: coex signed out: 401", st == 401, (st, j))
st, j = lvliveapi.api(Web(s3), Req("/api/live/coex", who=None))
check("R3 m3: live/coex signed out: 401", st == 401, (st, j))
st, j = api(s3, "/api/coex")
check("coex", st == 200 and j["ble"]["state"] == "idle" and j["live"] is None and "heap" in j, j)
check("coex has no key", "test-fleet" not in json.dumps(j))
import lv                        # noqa: E402
lv.OVERRIDES = ("ble",)
s4 = Sh(bluetooth.World(6), 0, TMP + "/z")
check("core changed: off", s4.live is None and s4.live_why == "core changed")
lv.OVERRIDES = ()

# ---- delivery: a hail 1 -> 2 by a direct dial
w, (a, b) = fresh(7)
t = run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
check("heard each other", t is not None)
check("logs match: no ordinary sync", a.node.digest() == b.node.digest())
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": 2})
check("hail queued", st == 200 and j["ok"] and len(a.live.out) == 1, (st, j))
hid = j["id"]
st, j = api(a, "/api/live")
check("sending", j["out"][0]["st"] == 0 and j["out"][0]["to"] == 1, j["out"])
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("delivered by a direct dial", t is not None and a.live.n["dial"] >= 1, a.live.n)
check("dial fast", t is not None and t < 3000, t)
check("taken once", b.live.n["in"] == 1 and len(b.live.inb) == 1, b.live.n)
check("light on arrival", b.live.lc[1] == 1, b.live.lc)
st, j = api(a, "/api/live")
check("Delivered", j["out"][0]["st"] == 2, j["out"])
check("backoff untouched", a.ble.peers[1].fails == 0)
st, j = api(b, "/api/live")
check("b sees the hail", len(j["in"]) == 1 and j["in"][0]["from"] == 0 and j["in"][0]["ph"] == 2
      and j["in"][0]["can"] == 1 and not j["in"][0]["seen"], j["in"])
check("inbox drained", not b.live.inb)
st, j = api(b, "/api/live/seen", "POST", {"id": j["in"][0]["id"]})
check("seen queued", st == 200 and len(b.live.out) == 1)
t = run(w, [a, b], 10000, lambda: not b.live.out and b.ble.state == "idle")
check("seen delivered", t is not None)
st, j = api(a, "/api/live")
check("X saw it", j["out"][0]["st"] == 3, j["out"])
check("a: no flicker for seen/acks", a.live.lc[1] == 0, a.live.lc)

# a repeat of the hail (as if its ack was lost) is acked but not taken again
a.live.out.append([1, lvlivein.item(a.live, 1, 1, b"\x02\x00\x00\xff\xff", int(hid[2:], 16)), a.clock.date()])
a.live.nx[1] = [0, 0]
a.live.gap = 0
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("repeat acked", t is not None)
check("repeat not taken", b.live.n["dup"] == 1 and b.live.n["in"] == 1, b.live.n)
check("no light for a repeat", b.live.lc[1] == 1)

# hail back, within 10 minutes
st, j = api(b, "/api/live/hail", "POST", {"to": 0, "ph": 1, "back": 1})
check("hail back", st == 200, j)
t = run(w, [a, b], 40000, lambda: not b.live.out and b.ble.state == "idle")
st, j = api(a, "/api/live")
check("a got the hail back", len(j["in"]) == 1 and j["in"][0]["back"] == 1, j["in"])

# fair use
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("2 min gap", st == 429 and "couple" in j["err"], (st, j))
st, j = api(a, "/api/live/hail", "POST", {"to": 0})
check("not yourself", st == 400)
st, j = api(a, "/api/live/hail", "POST", {"to": "1"})
check("bad to", st == 400)
st, j = lvliveapi.api(Web(a), Req("/api/live/hail", "POST", None, 0))
check("empty body", st == 400)
r = Req("/api/live/hail", "POST", None, 0)
r.body = b"[1,2"
check("bad json", lvliveapi.api(Web(a), r)[0] == 400)

# 20 a day, one undelivered per crewmate
j = lvliveapi._hl(a)
j["o"] = [[("%06x" % k), 5, 0, 1, 2] for k in range(20)]
lvlivein.save(a.data + lvliveapi.F, j)
st, j = api(a, "/api/live/hail", "POST", {"to": 3})
check("20 a day", st == 429 and "today" in j["err"], (st, j))

# ---- will deliver: ship 2 out of range
w, (a, b) = fresh(8)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
w.separate(a.radio, b.radio)
f0, n0 = a.ble.peers[1].fails, a.ble.peers[1].next_try
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("queued out of range", st == 200)
run(w, [a, b], 12000)
# 0.3.0 review R2 M1: one dial at once, then at most one per GAP (20 s) across all peers,
# and only to a ship heard in the last NEAR (30 s): a crewmate out of range is left alone
check("one dial at once", a.live.n["dial"] == 1 and a.live.n["dial_fail"] == 1, a.live.n)
check("backoff put back", a.ble.peers[1].fails == f0 and a.ble.peers[1].next_try == n0,
      (a.ble.peers[1].fails, f0))
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("one undelivered per crewmate", st == 429 and "way" in j["err"], (st, j))
run(w, [a, b], 6000)
check("R2 M1: no second dial inside the gap", a.live.n["dial"] == 1, a.live.n)
run(w, [a, b], 160000)
check("R2 M1: at most one more while still recently heard", a.live.n["dial"] in (1, 2), a.live.n)
check("R2 M1: not heard for 30 s: no dials", a.ble.peers[1].seen < w.now - lvlive.NEAR, a.live.n)
st, j = api(a, "/api/live")
check("Will deliver", j["out"][0]["st"] == 1, j["out"])
d = a.live.n["dial"]
run(w, [a, b], 130000)
check("quiet when not heard", a.live.n["dial"] == d, a.live.n)
w.rejoin(a.radio, b.radio)
t = run(w, [a, b], 400000, lambda: not a.live.out and a.ble.state == "idle")
check("delivered once back in range", t is not None and b.live.n["in"] == 1, (t, a.live.n, b.live.n))
check("persisted", not lvlivein.load(a.data + "/livebox.json")["o"])

# ---- an old ship (no Link) and a new one sync as before; nothing is sent to it
w, (a, b) = fresh(9, live=(True, False))
b.log.add if False else None
check("old ship has no cap", not b.node.advert()[5] & lvlive.CAP)
run(w, [a, b], 300000, lambda: 1 in a.ble.peers)
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("an old ship can't be hailed", st == 409 and "update" in j["err"], (st, j))
lvlivein.send(a.live, 1, 1, b"\x00")            # (even if queued) never dialled for
run(w, [a, b], 30000)
check("no dial to an old ship", a.live.n["dial"] == 0)

# ---- items on an ordinary sync with records to move, lossy, MTU 23; and an old ship
from lv import record as R       # noqa: E402
with open("build/season_log.bin", "rb") as f:
    RAW = f.read()
RECS = [RAW[k:k + R.LEN] for k in range(0, len(RAW), R.LEN)]


def fill(s, authors):
    for r in RECS:
        if R.ship(r) in authors:
            s.log.merge(r)


for live in ((True, False), (True, True)):
    w, (a, b) = fresh(10, live=live)
    w.drop, w.dup, w.reorder = 50, 50, 100
    a.ble.cfg["mtu"] = b.ble.cfg["mtu"] = 23
    fill(a, (0, 3, 6))
    fill(b, (1, 4, 7))
    if live[1]:
        for k in range(8):                       # more than fit one HELLO
            api(a, "/api/live/hail", "POST", {"to": 1}) if k == 0 else lvlivein.send(a.live, 3, 1, bytes((5, k)))
    t = run(w, [a, b], 400000, lambda: a.node.digest() == b.node.digest() and not a.live.out
            and a.ble.state == "idle" and b.ble.state == "idle")
    check("sync with %s ship" % ("a new" if live[1] else "an old"), t is not None, (a.ble.n, a.live.n))
    if live[1]:
        check("all 8 items over", b.live.n["in"] == 8 and a.live.n["acked"] == 8, (a.live.n, b.live.n))

# ---- the light's rules
w, (a, b) = fresh(11)
L = b.live


class FakeClock:
    def __init__(self, m, d="2026-10-25", known=True):
        self.m, self.d, self.k = m, d, known

    def minute(self):
        return self.m

    def date(self):
        return self.d

    def known(self):
        return self.k


real = b.clock
for name, clk, cfg, lt, want in (
        ("day", FakeClock(600), {}, None, 1),
        ("quiet night", FakeClock(1350), {}, None, 0),
        ("quiet early", FakeClock(300), {}, None, 0),
        ("no clock", FakeClock(600, known=False), {}, None, 0),
        ("switched off", FakeClock(600), {"light": False}, None, 0),
        ("a test playing", FakeClock(600), {}, 5, 0)):
    b.clock, L.cfg, b.ledtest, L.lc = clk, cfg, lt, [0, 0]
    lvlivein.flick(L)
    check("light: " + name, L.lc[1] == want, L.lc)
b.clock, L.cfg, b.ledtest, L.lc = FakeClock(600), {}, None, [0, 0]
for k in range(20):
    lvlivein.flick(L)
check("12 a day", L.lc == ["2026-10-25", 12], L.lc)
b.clock.d = "2026-10-26"
lvlivein.flick(L)
check("a new day", L.lc == ["2026-10-26", 1], L.lc)
b.led.q = None
b.clock.m = 1400
L.lc = [0, 0]
lvlivein.flick(L)
check("no quiet hours set: 22-07 anyway", L.lc[1] == 0)
b.clock = real
del b.led.q

# lvflick itself: 3 Hz at most, waits for the link, the test's 429 meanwhile
try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
import lvflick                    # noqa: E402
import lvship                     # noqa: E402


class Pin:
    def __init__(self):
        self.w = []

    def value(self, v):
        self.w.append((lvship.ticks_ms(), v))


pin = Pin()
b.led_pin = lambda: pin
lvflick.FLICK_MS = 1200


async def go():
    check("flick starts", lvflick.start(b))
    check("counts as a test", b.ledtest is not None)
    await lvship.sleep_ms(1500)


asyncio.run(go())
ons = [t for t, v in pin.w if v == 1]
check("flicker plays", len(ons) >= 4, pin.w)
check("3 Hz at most", all([ons[k + 1] - ons[k] >= 320 for k in range(len(ons) - 1)]), ons)
check("R2 M6: the pin written dark first", pin.w and pin.w[0][1] == 0, pin.w[:2])
check("dark after", pin.w[-1][1] == 0 and b.ledtest is None)

# a link (or a phone's request) that keeps starting and stopping mid-flicker: still never
# faster than 3 Hz, since the light only comes on at the start of an "on" half
pin.w = []
HALF0 = lvflick.HALF
import lvledtest                  # noqa: E402
busy0 = lvledtest._busy
t00 = lvship.ticks_ms()


def flap(sh):
    t = lvship.ticks_diff(lvship.ticks_ms(), t00)
    return 500 < t < 1100 and (t // 40) % 2 == 1


lvledtest._busy = flap
try:
    asyncio.run(go())
finally:
    lvledtest._busy = busy0
ch = [pin.w[k][0] - pin.w[k - 1][0] for k in range(2, len(pin.w)) if pin.w[k][1] != pin.w[k - 1][1]]
ons = [t for t, v in pin.w if v == 1]
check("flapping link: 3 Hz at most", all([ons[k + 1] - ons[k] >= 320 for k in range(len(ons) - 1)]), ons)
check("flapping link: went dark for it", len(ons) >= 2 and any([d < HALF0 for d in ch]), pin.w)
check("flapping link: dark after", pin.w[-1][1] == 0 and b.ledtest is None)

# ---- a fault in a hook: off, said why, the ordinary sync carries on
w, (a, b) = fresh(12)
fill(a, (0, 3))
fill(b, (1,))


def boom(self, s, m, off):
    raise ValueError("boom")


lvlive.Link.take, take0 = boom, lvlive.Link.take
run(w, [a, b], 300000, lambda: a.live is None or b.live is None)
lvlive.Link.take = take0
x = a if a.live is None else b
check("fault: off, in plain words (no repr)", x.live is None and x.live_why == "fault: ValueError", x.live_why)
c = lvlivein.load(x.data + "/live.json")
check("fault: live.json", c["on"] is False and c["why"] == "fault: ValueError", c)
check("fault: hooks off", "poll" not in x.ble.__dict__ and not x.node.advert()[5] & lvlive.CAP)
check("R2 M4: fault: the advert says paused", x.node.advert()[5] & lvlive.PAUSED, x.node.advert())
t = run(w, [a, b], 400000, lambda: a.node.digest() == b.node.digest() and a.ble.state == b.ble.state == "idle")
check("fault: sync carries on", t is not None)

# ---- fuzz: trailers and adverts from a broken or hostile radio
w, (a, b) = fresh(13)
L = b.live
rng = bluetooth.World(99)


def rbytes(k):
    return bytes([rng.rand(256) for _ in range(k)])


class FakeSess:
    def __init__(self):
        self.to = 0
        self.acks = []


good = lvlivein.item(a.live, 1, 1, b"\x01\x00\x00")
inb0 = len(L.inb)
taken = 0
for k in range(3000):
    s = FakeSess()
    kind = rng.rand(6)
    if kind == 0:
        m = rbytes(rng.rand(300))                                    # noise
    elif kind == 1:
        m = b"D\x00\x00" + bytes((lvlive.MARK, rng.rand(256))) + rbytes(rng.rand(200))
    elif kind == 2:                                                  # a good item, bit flipped
        g = bytearray(good)
        g[rng.rand(len(g))] ^= 1 << rng.rand(8)
        m = b"D\x00\x00" + bytes((lvlive.MARK, 1)) + bytes(g)
    elif kind == 3:                                                  # truncated
        m = (b"D\x00\x00" + bytes((lvlive.MARK, 2)) + good + good)[:3 + rng.rand(41)]
    elif kind == 4:                                                  # n past MAXI
        m = b"D\x00\x00" + bytes((lvlive.MARK, lvlive.MAXI + 1 + rng.rand(9))) + good * 7
    else:                                                            # from the wrong ship
        s.to = 2 + rng.rand(5)
        m = b"D\x00\x00" + bytes((lvlive.MARK, 1)) + good
    try:
        L.take(s, m, 3)
    except Exception as e:
        check("fuzz take raised", False, (k, e, m))
    try:
        S.parse_advert(rbytes(rng.rand(40)))
        S.parse_advert(S.adv_data(rbytes(15)))
    except Exception as e:
        check("fuzz parse raised", False, e)
check("fuzz: nothing bad taken", len(L.inb) == inb0 and L.n["in"] == 0, (L.n, len(L.inb)))
check("fuzz: counted", L.n["bad"] > 1000, L.n)
# the good one still goes in (and only once)
L.take(FakeSess(), b"D\x00\x00" + bytes((lvlive.MARK, 1)) + good, 3)
L.take(FakeSess(), b"D\x00\x00" + bytes((lvlive.MARK, 1)) + good, 3)
check("fuzz: the real one", L.n["in"] == 1 and L.n["dup"] == 1, L.n)
# whole sessions with garbage on the air: no fault
w.drop, w.dup, w.reorder = 100, 100, 200
fill(a, (0, 2))
run(w, [a, b], 300000)
check("lossy air: no fault", a.live is not None and b.live is not None)

# ---- well-signed items with any kind and body: acked, a later kind not kept, page fine
w, (a, b) = fresh(14)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
L = b.live
for k in range(400):
    kind = rng.rand(256)
    body = rbytes(rng.rand(12))
    it = lvlivein.item(a.live, kind, 1, body)
    L.take(FakeSess(), b"D\x00\x00" + bytes((lvlive.MARK, 1)) + it, 3)
check("signed junk: no later kinds kept", all([o[1][0] <= 2 for o in L.inb]), [o[1][0] for o in L.inb])
try:
    st, j = api(b, "/api/live")
    ok = st == 200 and all([0 <= x["ph"] < lvliveapi.PHRASES for x in j["in"]])
    json.dumps(j)
except Exception as e:
    ok = False
    j = e
check("signed junk: the page still answers", ok, j)
check("signed junk: inbox bounded", len(L.inb) == 0 and len(j["in"]) <= lvliveapi.HMAX, len(j["in"]))
check("signed junk: flickers capped", L.lc[1] <= lvlive.LIGHTS, L.lc)

# a later release's kind travels and is acked: it never sticks in the sender's queue
lvlivein.send(a.live, 9, 1, b"\x01\x02")
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("later kind acked", t is not None and not b.live.inb, (t, b.live.inb))

# ---- kill switches
lvlive.ON = False
s = Sh(bluetooth.World(15), 0, TMP + "/k")
check("fleet kill switch", s.live is None and "fleet" in s.live_why, s.live_why)
st, j = api(s, "/api/live/set", "POST", {"on": True})
check("fleet kill switch beats Settings", st == 200 and not j["on"] and s.live is None, j)
lvlive.ON = True
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": lvliveapi.PHRASES})
check("phrase out of range", st == 400, (st, j))
st, j = api(a, "/api/live/hail", "POST", {"to": 8})
check("crewmate out of range", st == 400, (st, j))
st, j = api(a, "/api/live/hail", "POST", {"to": True})
check("to: not a bool", st == 400, (st, j))
st, j = api(a, "/api/live/set", "POST", {"on": False})
check("Settings: off", st == 200 and not j["on"] and a.live is None and "poll" not in a.ble.__dict__, j)
check("Settings: advert plain", not a.node.advert()[5] & lvlive.CAP)
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("Settings off: no hails", st == 409, (st, j))
st, j = api(a, "/api/live/set", "POST", {"on": True})
check("Settings: on again", st == 200 and j["on"] and a.live is not None, j)

# ---- safe-mode auto-off (0.3.0): only a crash lvsafe counted turns Hail off at the next
# boot; its boot notes alone don't, nor a count set aside after a healthy run
import lvsafe                     # noqa: E402
rm_tree(TMP)
mkdir(TMP)
for name, fj, on in (("a boot note alone", '{"boot": "ship.json put back"}', True),
                     ("a count of 0", '{"n": 0, "why": "x", "boot": "y"}', True),
                     ("a count that won't read", '{"n": "?", "why": "x", "live": 1}', False),
                     ("not JSON", 'n=1', True),
                     ("one crash outside Hail", '{"n": 1, "why": "MemoryError", "up": 70}', True),
                     ("one crash in Hail's code", '{"n": 1, "why": "MemoryError", "up": 70, "live": 1}', False)):
    d = TMP + "/f%d" % len(name)
    rm_tree(d)
    mkdir(d)
    with open(d + "/fault.json", "w") as f:
        f.write(fj)
    s = Sh(bluetooth.World(30), 0, d)
    check("fault.json, %s: Hail %s" % (name, "stays on" if on else "off"), (s.live is not None) == on, s.live_why)
d = TMP + "/sm"
mkdir(d)
lvsafe.crashed("OSError(28)", False, 9000, d)
s = Sh(bluetooth.World(31), 0, d)
check("R2 M3: lvsafe noted a crash outside Hail: on", s.live is not None, s.live_why)
os.remove(d + "/fault.json")
lvsafe.crashed("OSError(28)", False, 9000, d, live=True)
check("R2 M3: lvsafe notes Hail's part", lvsafe.faults(d).get("live") == 1, lvsafe.faults(d))
s = Sh(bluetooth.World(31), 0, d)
check("safe mode: a counted crash turns it off", s.live is None and s.live_why == "restarted after a fault", s.live_why)
check("safe mode: off, the advert without the cap bit", not s.node.advert()[5] & lvlive.CAP)
check("R2 M4: ... and with the paused bit (crewmates see a paused ship, not an old one)",
      s.node.advert()[5] & lvlive.PAUSED and s.node.advert()[5] & 15 == 0, s.node.advert())
i = lvlive.parse(S.adv_data(s.node.advert()))
check("R2 M4: parsed: no cap, off", i is not None and not i["cap"] and i["off"] and i["ship"] == 0, i)
lvsafe.crashed("OSError(28)", False, 9000, d, live=True)   # two in a row: safe mode (no BLE at all) ...
check("safe mode: lvsafe says safe", (lvsafe.check(False, d, say=lambda t: None) or "").startswith("safe"))
lvsafe.retry(d)                                        # ... then Try the game again
s = Sh(bluetooth.World(32), 0, d)
check("safe mode: after Try again, Hail still off", s.live is None, s.live_why)
st, j = api(s, "/api/live")
check("safe mode: the page says why", st == 200 and not j["on"] and "fault" in j["why"], j)
st, j = api(s, "/api/live/set", "POST", {"on": True})
check("safe mode: a phone turns it back on", st == 200 and j["on"] and s.live is not None, j)
s = Sh(bluetooth.World(33), 0, d)
check("safe mode: stays on through the next boot (the same crash)", s.live is not None, s.live_why)
os.rename(d + "/fault.json", d + "/fault.last.json")   # main.py after 10 healthy minutes
s = Sh(bluetooth.World(34), 0, d)
check("safe mode: set aside after a healthy run: on", s.live is not None, s.live_why)
lvsafe.crashed("ValueError", False, 100, d, live=True)
s = Sh(bluetooth.World(35), 0, d)
check("safe mode: a new crash: off again", s.live is None, s.live_why)

# ---- end to end in quiet hours, at the day's cap, and with a ship that turned Hail off
w, (a, b) = fresh(40)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
m = b.clock.minute()
b.led.q = ((m - 1) % 1440, (m + 60) % 1440)            # quiet hours now, on b's clock
st, j = api(b, "/api/live")
check("quiet hours: the page knows", j["quiet"] == list(b.led.q) and j["cap"] == lvlive.LIGHTS, j)
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": 1})
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("quiet hours: delivered", t is not None and b.live.n["in"] == 1, (t, b.live.n))
check("quiet hours: no light", b.live.lc[1] == 0, b.live.lc)
st, j = api(a, "/api/live")
check("quiet hours: the sender sees Delivered", j["out"][0]["st"] == 2, j["out"])
st, j = api(b, "/api/live")
check("quiet hours: waiting on the home screen", len(j["in"]) == 1 and not j["in"][0]["seen"], j["in"])
del b.led.q
b.live.lc = [b.clock.date(), lvlive.LIGHTS]            # 12 flickers already today
st, j = api(b, "/api/live")
check("cap: the page knows", j["lights"] == j["cap"] == lvlive.LIGHTS and j["quiet"] is None, j)
a.live.nx.clear()
a.live.gap = 0
lvliveapi.GAP_MS, gap = 0, lvliveapi.GAP_MS
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": 2})
check("cap: a second hail queued", st == 200, (st, j))
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("cap: delivered", t is not None and b.live.n["in"] == 2, (t, b.live.n))
check("cap: no light past 12", b.live.lc[1] == lvlive.LIGHTS, b.live.lc)
lvliveapi.GAP_MS = gap
# b turns Hail off: its advert loses the cap bit and shows the paused one (R2 M4), a won't send
st, j = api(b, "/api/live/set", "POST", {"on": False})
t = run(w, [a, b], 600000, lambda: not a.ble.peers[1].info.get("cap"))   # (the fake hears ~1% of adverts)
check("off: a hears b without the bit", t is not None, a.ble.peers[1].info)
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("R2 M4: off: a won't hail b, in neutral words (not 'needs the update')",
      st == 409 and "isn't taking hails right now" in j["err"] and "update" not in j["err"], (st, j))
st, j = api(a, "/api/live")
pb = [p for p in j["peers"] if p["s"] == 1][0]
check("off: the page greys b, as paused", pb["cap"] == 0 and pb["off"] == 1, j["peers"])

# the fleet kill switch on the receiver: the same, from the release
w, (a, b) = fresh(41)
lvlive.ON = False
b2 = Sh(w, 1, TMP + "/s1b")
lvlive.ON = True
b.radio.on = False
t = run(w, [a, b2], 300000, lambda: 1 in a.ble.peers and a.ble.peers[1].info)
check("fleet switch: a hears b plain", t is not None and not a.ble.peers[1].info.get("cap"), a.ble.peers.get(1) and a.ble.peers[1].info)
st, j = api(a, "/api/live/hail", "POST", {"to": 1})
check("fleet switch: a won't hail b", st == 409, (st, j))

# ---- power loss mid-hail: queued, sender restarts; receiver restarts after taking it
w, (a, b) = fresh(42)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
w.separate(a.radio, b.radio)
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": 4})
hid = j["id"]
run(w, [a, b], 40000)                                   # (not heard for 30 s: Will deliver)
check("power loss: Will deliver before the cut", a.live.out and api(a, "/api/live")[1]["out"][0]["st"] == 1)
with open(a.data + "/livebox.json.new", "w") as f:     # a save cut short leaves its .new
    f.write('{"o": [[1, "trunc')
a.radio.on = False
a2 = Sh(w, 0, a.data)                                   # the sender boots again, same /data
check("power loss: the queue survives", len(a2.live.out) == 1 and a2.live.out[0][0] == 1, a2.live.out)
check("power loss: the hail still listed", api(a2, "/api/live")[1]["out"][0]["id"] == hid)
w.rejoin(a2.radio, b.radio)
t = run(w, [a2, b], 400000, lambda: not a2.live.out and a2.ble.state == "idle")
check("power loss: delivered after the restart", t is not None and b.live.n["in"] == 1, (t, a2.live.n, b.live.n))
check("power loss: one light", b.live.lc[1] == 1, b.live.lc)
check("power loss: the sender sees Delivered", api(a2, "/api/live")[1]["out"][0]["st"] == 2)
b.radio.on = False
b2 = Sh(w, 1, b.data)                                   # the receiver boots again
check("power loss: the receiver's inbox survives", len(api(b2, "/api/live")[1]["in"]) == 1)
seq = int(hid[2:], 16)
a2.live.out.append([1, lvlivein.item(a2.live, 1, 1, b"\x04\x00\x00\xff\xff", seq), a2.clock.date()])  # as if its ack never came
a2.live.nx[1] = [0, 0]
a2.live.gap = 0
t = run(w, [a2, b2], 400000, lambda: not a2.live.out and a2.ble.state == "idle")
check("power loss: the repeat is acked", t is not None, (a2.live.n, b2.live.n))
check("power loss: not taken twice, no second light", b2.live.n["in"] == 0 and b2.live.n["dup"] == 1 and b2.live.lc[1] == 1,
      (b2.live.n, b2.live.lc))
# an item the peer won't take (a wrong mac): no storm of dials, the same 2 then 1 a minute
it = bytearray(lvlivein.item(a2.live, 1, 1, b"\x05\x00\x00", seq + 1))
it[-1] ^= 0xFF
a2.live.out.append([1, bytes(it), a2.clock.date()])
a2.live.nx[1] = [0, 0]
a2.live.gap = 0
d0 = a2.live.n["dial"]
run(w, [a2, b2], 180000)
check("refused item: no dial storm", a2.live.n["dial"] - d0 <= 5 and b2.live.n["bad"] >= 1, (a2.live.n, b2.live.n))

# ---- coexistence: hail dials hold while the web is mid-answer or an update arrives
w, (a, b) = fresh(16)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
a.web = Web(a)
a.web.busy = 1
api(a, "/api/live/hail", "POST", {"to": 1})
run(w, [a, b], 3000)
check("no dial mid-answer", a.live.n["dial"] == 0, a.live.n)
a.web.busy = 0
a.ota_t = lvship.ticks_ms()
run(w, [a, b], 3000)
check("no dial while an update arrives", a.live.n["dial"] == 0, a.live.n)
a.ota_t = lvship.ticks_ms() - lvlive.OTA_MS - 1
t = run(w, [a, b], 10000, lambda: not a.live.out and a.ble.state == "idle")
check("dials after the update", t is not None and a.live.n["dial"] >= 1, a.live.n)

# the radio test's probe
import lvweb                     # noqa: E402


class W:
    def __init__(self):
        self.b = b""
        self.drains = 0

    def write(self, x):
        self.b += bytes(x)

    async def drain(self):
        self.drains += 1


for kb, want in ((0, 0), (4, 4096), (99, lvliveapi.PING_KB * 1024), ("x", 0)):
    r = Req("/api/coex/ping", who=0)
    r.q = {"kb": str(kb)}
    ww = W()
    asyncio.run(lvliveapi.ping(lvweb, Web(a), r, ww))
    hd, _, body = ww.b.partition(b"\r\n\r\n")
    check("ping %s KB" % kb, b" 200 " in hd and b"X-Ble: idle" in hd and len(body) == want
          and (b"Content-Length: %d" % want) in hd, (hd, len(body)))
check("ping drains per piece", ww.drains >= 1)
r = Req("/api/coex/ping", who=None)
ww = W()
asyncio.run(lvliveapi.ping(lvweb, Web(a), r, ww))
check("ping signed out: 401", b" 401 " in ww.b.split(b"\r\n")[0], ww.b[:40])

# ---- OTA coexistence: the signature check waits for a quiet radio and server (lvotaq.quiet)
import lvotaq as lvota            # noqa: E402  (quiet moved from lvota in 0.3.0)


class QB:
    def __init__(self, n):
        self.n = n                # busy for n looks

    def busy(self):
        self.n -= 1
        return self.n >= 0


class QW:
    def __init__(self, b, busy=1):
        self.ship = type("S", (), {})()
        self.ship.ble = b
        self.busy = busy


qb = QB(5)
asyncio.run(lvota.quiet(QW(qb), {"f": "0", "o": "0", "n": "4"}, b"abcd"))
check("check waits for the sync", qb.n == -1, qb.n)
qb = QB(5)
asyncio.run(lvota.quiet(QW(qb), {"f": "0", "o": "0", "n": "8"}, b"abcd"))
check("not before the envelope's last piece", qb.n == 5)
qb = QB(5)
asyncio.run(lvota.quiet(QW(qb), {"f": "1", "o": "0", "n": "4"}, b"abcd"))
check("not for a file piece", qb.n == 5)
asyncio.run(lvota.quiet(QW(QB(0)), {"f": "0", "o": "x"}, b""))
check("a bad query: no wait, no error", True)
q0, lvota.QUIET_MS = lvota.QUIET_MS, 300
t0 = lvship.ticks_ms()
asyncio.run(lvota.quiet(QW(QB(10 ** 6), busy=3), {"f": "0", "o": "0", "n": "1"}, b"a"))
dt = lvship.ticks_diff(lvship.ticks_ms(), t0)
lvota.QUIET_MS = q0
check("a sync that won't end: the check goes ahead", 250 <= dt < 2000, dt)
qw = QW(QB(0), busy=3)


async def calm():
    await lvship.sleep_ms(200)
    qw.busy = 1


async def both():
    asyncio.create_task(calm())
    await lvota.quiet(qw, {"f": "0", "o": "0", "n": "1"}, b"a")
    return qw.busy


check("waits for the other requests too", asyncio.run(both()) == 1)

# 0.3.0: a file piece waits (PIECE_MS at most) for the other requests, never for the radio
qw = QW(QB(10 ** 6), busy=3)


async def both_piece():
    asyncio.create_task(calm())
    await lvota.quiet(qw, {"f": "2", "o": "1024"}, b"a" * 1024)
    return qw.busy


check("a file piece waits for the other requests", asyncio.run(both_piece()) == 1 and qw.ship.ble.n == 10 ** 6,
      qw.ship.ble.n)
p0, lvota.PIECE_MS = lvota.PIECE_MS, 300
t0 = lvship.ticks_ms()
asyncio.run(lvota.quiet(QW(QB(0), busy=4), {"f": "1", "o": "0"}, b"a"))
dt = lvship.ticks_diff(lvship.ticks_ms(), t0)
lvota.PIECE_MS = p0
check("phones that never pause: the piece goes ahead after PIECE_MS", 250 <= dt < 2000, dt)

# ---- 0.3.0 review R2 (group B): the radio budget, passing faults, late hails, the light
# M1: one dial per GAP across every crewmate (not per crewmate)
w, (a, b, c3) = fresh(60, 3, (True, True, True))
run(w, [a, b, c3], 300000, lambda: all([k in a.ble.peers for k in (1, 2)]))
dials = []
con0 = a.ble._connect


def con(p, now):
    if a.live.forced is not None and a.live.forced[0] is p:    # (a hail dial, not a sync)
        dials.append((now, p.ship))
    return con0(p, now)


a.ble._connect = con
api(a, "/api/live/hail", "POST", {"to": 1})
api(a, "/api/live/hail", "POST", {"to": 2})
t = run(w, [a, b, c3], 120000, lambda: not a.live.out and a.ble.state == "idle")
check("R2 M1: two crewmates: both delivered", t is not None and b.live.n["in"] == 1 and c3.live.n["in"] == 1,
      (t, a.live.n))
ts = [d[0] for d in dials]
check("R2 M1: dials to different ships at least GAP apart",
      all([ts[k + 1] - ts[k] >= lvlive.GAP for k in range(len(ts) - 1) if dials[k][1] != dials[k + 1][1]]), dials)
a.ble._connect = con0
# a waiting hail for a crewmate not heard lately costs no lvlivein import (the 5 s reload)
w.separate(a.radio, b.radio)
lvliveapi.GAP_MS, gap = 0, lvliveapi.GAP_MS
check("R2 M1: queued for a ship out of range", api(a, "/api/live/hail", "POST", {"to": 1, "ph": 3})[0] == 200)
lvliveapi.GAP_MS = gap
run(w, [a, b, c3], 60000)
imp = [0]
want0 = lvlive.Link.want


def want(self, now):
    r = want0(self, now)
    imp[0] += 1 if r else 0
    return r


lvlive.Link.want = want
run(w, [a, b, c3], 30000)
lvlive.Link.want = want0
check("R2 M1: nobody near: no lvlivein loads while it waits", imp[0] == 0 and len(a.live.out) == 1, imp)
# R2 m1: nearby, but its Hail paused (no cap bit): still no load (the probe saw 97 in 10 min)
pb = a.ble.peers[1]
i0, s0 = pb.info, pb.seen
pb.info, pb.seen = dict(i0, cap=0, off=64), w.now
check("R2 m1: a paused ship heard just now: not worth a load", not a.live.want(w.now))
pb.info = dict(i0, cap=32)
check("R2 m1: ... the same ship taking hails: worth one", a.live.want(w.now))
pb.info, pb.seen = i0, s0
w.rejoin(a.radio, b.radio)

# M2: an update arriving on the receiver: the hail is held (no ack, not taken), Hail stays
# on, and it lands once the update is done
w, (a, b) = fresh(61)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
b.ota_t = lvship.ticks_ms()
api(a, "/api/live/hail", "POST", {"to": 1})
run(w, [a, b], 5000, lambda: b.live.n["held"] >= 1)
check("R2 M2: held while an update arrives", b.live.n["held"] >= 1 and b.live.n["in"] == 0 and a.live.out,
      (a.live.n, b.live.n))
check("R2 M2: ... Hail still on", b.live is not None and b.live_why is None)
b.ota_t = lvship.ticks_ms() - lvlive.OTA_MS - 1
t = run(w, [a, b], 120000, lambda: not a.live.out and a.ble.state == "idle")
check("R2 M2: delivered after the update", t is not None and b.live.n["in"] == 1, (t, a.live.n, b.live.n))
# a MemoryError taking a trailer: no acks (the peer sends again), Hail stays on
class Ses:
    acks = None


ss = Ses()
ss.acks = [1, 2]
def oom(lk, s_, m, off):
    raise MemoryError("x")


class Fake:                       # (a stand-in lvlivein: MicroPython can't make modules)
    take = staticmethod(oom)


fake = Fake()
real = sys.modules.get("lvlivein")
sys.modules["lvlivein"] = fake
try:
    b.live.take(ss, bytes([lvlive.MARK, 0, 0]), 0)
finally:
    if real is not None:
        sys.modules["lvlivein"] = real
check("R2 M2: MemoryError taking: no acks, counted, on", ss.acks == [] and b.live.n["oom"] == 1 and b.live is not None,
      (ss.acks, b.live.n))
L2 = b.live
for k in range(lvlive.TRANSIENT):
    L2.fault(MemoryError("x"))
check("R2 M2: a few MemoryErrors in a row: Hail stays on", b.live is L2 and b.live_why is None, b.live_why)
L2.fault(MemoryError("x"))
check("R2 M2: ... but not forever", b.live is None and b.live_why == "fault: MemoryError", b.live_why)
lvlivein.load(b.data + "/live.json")

# M5: a hail its sender sent over a day ago is acked but not kept (no light, not listed);
# the arrival time is the ship's, and Hail back follows it
w, (a, b) = fresh(62)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
m = (lvlivein.mins(a.clock) - 1500) & 65535
lvlivein.send(a.live, 1, 1, bytes((2, 0, 0, m >> 8, m & 255)))
a.live.gap = 0
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
check("R2 M5: a day-old hail: acked", t is not None, a.live.n)
check("R2 M5: ... not kept, no light", b.live.n["old"] == 1 and b.live.n["in"] == 0 and b.live.lc[1] == 0, b.live.n)
check("R2 M5: ... not listed", not api(b, "/api/live")[1]["in"])
st, j = api(a, "/api/live/hail", "POST", {"to": 1, "ph": 1})
check("R2 M5: a fresh one queued", st == 200, (st, j))
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
check("R2 M5: ... delivered", t is not None and b.live.n["in"] == 1, (t, a.live.n, b.live.n))
e = lvliveapi._ep(b)
check("R2 M5: a fresh one: kept with its arrival time", b.live.inb and b.live.inb[0][2] is not None
      and abs(b.live.inb[0][2] - e) < 5000, b.live.inb)
j = api(b, "/api/live")[1]["in"][0]
check("R2 M5: sent time to the minute", j["sent"] is not None and abs(j["sent"] - j["t"]) <= 60000, j)
check("R2 M5: Hail back offered", j["can"] == 1, j)
# one that arrived 11 minutes ago (the phone only looks now): no Hail back
b.live.inb.append([0, b.live.out and b.live.out[0][1] or lvlivein.item(a.live, 1, 1, b"\x01\x00\x00\xff\xff", 0x778),
                   e - 660000, None])
b.live.inb[-1][1] = bytes([1, 1]) + bytes([0, 0x07, 0x78]) + bytes([1, 0, 0, 255, 255]) + bytes(12)
j = api(b, "/api/live")[1]["in"]
late = [h for h in j if h["id"] == "000778"]
check("R2 M5: 11 min after it arrived: no Hail back", late and late[0]["can"] == 0 and late[0]["t"] == e - 660000, j)
# arrived before the clock was known: from uptime
b.live.inb.append([0, bytes([1, 1, 0, 0x07, 0x79, 1, 0, 0, 255, 255]) + bytes(12), None, b.live.now - 30000])
j = api(b, "/api/live")[1]["in"]
x = [h for h in j if h["id"] == "000779"]
e = lvliveapi._ep(b)
check("R2 M5: arrival from uptime", x and abs(x[0]["t"] - (e - 30000)) < 2000 and x[0]["can"] == 1 and x[0]["sent"] is None, x)

# a hail still waiting when the day turns: out of the queue, "Didn't go" for a day
w, (a, b) = fresh(63)
w.separate(a.radio, b.radio)
api(a, "/api/live/hail", "POST", {"to": 1})
a.live.out[0][2] = "2026-10-24"
j = lvliveapi._hl(a)
j["d"] = "2026-10-24"
lvlivein.save(a.data + lvliveapi.F, j)
run(w, [a, b], 2000)
check("new day: the waiting item goes", not a.live.out and a.live.n["gone"] == 1, a.live.n)
j = api(a, "/api/live")[1]
check("new day: listed as Didn't go, not counted today", len(j["out"]) == 1 and j["out"][0]["st"] == 4 and j["today"] == 0, j)
check("new day: you can hail them again", api(a, "/api/live/hail", "POST", {"to": 1})[0] == 200)

# M6: a test or hail that takes the light over mid-pattern writes it dark at once
class L6:
    enabled = True
    seq = [1]
    mid = 1
    lit = 1
    w = []
    next = 0
    clock = Clock()

    def _write(self, v):
        self.w.append(v)
        self.lit = v


class S6:
    led = L6()


lvledtest._hold(S6)
check("R2 M6: held mid-breath: written dark", S6.led.w == [0] and not S6.led.lit and S6.led.seq is None, S6.led.w)

# M7: the hail light follows the Ship light unless set
w, (a, b) = fresh(64)
b.led.enabled = False
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
check("R2 M7: the page: light follows the Ship light (off)", api(b, "/api/live")[1]["light"] is False)
api(a, "/api/live/hail", "POST", {"to": 1})
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
check("R2 M7: Ship light off: no hail light", t is not None and b.live.n["in"] == 1 and b.live.lc[1] == 0, b.live.lc)
st, j = api(b, "/api/live/set", "POST", {"light": True})
check("R2 M7: set on in Settings", st == 200 and j["light"] is True, j)
lvliveapi.GAP_MS, gap = 0, lvliveapi.GAP_MS
api(a, "/api/live/hail", "POST", {"to": 1, "ph": 1})
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
lvliveapi.GAP_MS = gap
check("R2 M7: ... then it lights", t is not None and b.live.lc[1] == 1, b.live.lc)

# ---- 0.3.0 review group C
# R1 m2: the first boot of an update (a trial; often installed from safe mode, after the
# very crash that sent it there) doesn't turn Hail off for the old software's crash, nor
# does the boot after it
d = TMP + "/trial"
mkdir(d)
with open(d + "/fault.json", "w") as f:
    f.write('{"n": 2, "why": "MemoryError", "up": 70, "live": 1}')


class TrialSh(Sh):
    trial = True


s = TrialSh(bluetooth.World(70), 0, d)
check("R1 m2: a trial boot after a Hail crash: on", s.live is not None, s.live_why)
s = Sh(bluetooth.World(71), 0, d)
check("R1 m2: ... and the boot after the trial: still on", s.live is not None, s.live_why)
with open(d + "/fault.json", "w") as f:
    f.write('{"n": 1, "why": "ValueError", "up": 9, "live": 1}')
s = Sh(bluetooth.World(72), 0, d)
check("R1 m2: a new crash after the update: off", s.live is None, s.live_why)

# R2 m4: the page gets the day it paused, the reason in fixed words (no exception text)
st, j = api(s, "/api/live")
check("R2 m4: paused: why in fixed words, and the day", j["why"] == "restarted after a fault"
      and j["at"] == s.clock.date(), j)

# R3 m4: a sender's box made again (a new epoch): its old epoch's items, played back, are
# refused (not taken, not acked), the new epoch's go in
w, (a, b) = fresh(73)
run(w, [a, b], 300000, lambda: 0 in b.ble.peers and 1 in a.ble.peers)
api(a, "/api/live/hail", "POST", {"to": 1})
rec = a.live.out[0][1]
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
check("R3 m4: first epoch's hail in", t is not None and b.live.n["in"] == 1, b.live.n)
e1 = a.live.ep
a.live.ep, a.live.seq = (e1 + 1) & 255, 0           # (as lvlivex.setup does for a new box)
lvliveapi.GAP_MS, gap = 0, lvliveapi.GAP_MS
api(a, "/api/live/hail", "POST", {"to": 1, "ph": 1})
lvliveapi.GAP_MS = gap
t = run(w, [a, b], 60000, lambda: not a.live.out and a.ble.state == "idle")
check("R3 m4: the new epoch's hail in", t is not None and b.live.n["in"] == 2, b.live.n)
check("R3 m4: the old epoch kept", b.live.hw[0][0] == a.live.ep and e1 in b.live.hw[0][2:], b.live.hw)
bad0 = b.live.n["bad"]
a.live.out.append([1, rec, a.clock.date()])
a.live.nx[1], a.live.gap = [0, 0], 0
run(w, [a, b], 30000, lambda: b.live.n["bad"] > bad0 and a.ble.state == "idle")
check("R3 m4: the old epoch played back: refused", b.live.n["bad"] > bad0 and b.live.n["in"] == 2, b.live.n)
check("R3 m4: ... not acked", len(a.live.out) == 1, a.live.out)
del a.live.out[:]
lvlivein.keep(b.live)
x = lvlivein.load(b.data + "/livebox.json")["h"]["0"]
check("R3 m4: the epochs left behind survive a restart", x[0] == a.live.ep and e1 in x[2:], x)

rm_tree(TMP)
print("test_live: %d checks passed" % n[0])
