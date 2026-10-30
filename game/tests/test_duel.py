#!/usr/bin/env python3
# Two ships, real sync/ble, fake radio. Also runs on MicroPython unix ports.
import os
import sys
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except AttributeError:
    HERE = "tests"
ROOT = HERE.rsplit("/", 1)[0] if "/" in HERE else "."
sys.path[:0] = [ROOT, ROOT + "/board", HERE + "/fakeble"]
from lv import sync as S
from lv.ble import BleSync
from lv.chlog import ChoiceLog
from lv.clock import Clock
import bluetooth
import lvlive
import lvlivein as I
import lvduel as D

TMP = "/tmp/lvduel-test"
FK = b"generic-test-fleet"
LAY = [[0, 0], [12, 0], [35, 0]]
COUNT = [0]


def check(name, value):
    if not value:
        raise AssertionError(name)
    COUNT[0] += 1


def clean(path):
    try:
        for name in os.listdir(path):
            p = path + "/" + name
            try:
                os.remove(p)
            except OSError:
                clean(p)
        os.rmdir(path)
    except OSError:
        pass


class Clock0:
    def __init__(self):
        self.t = 1792936800000

    def known(self):
        return True

    def epoch_ms(self):
        return self.t

    def date(self):
        return self.t // 86400000

    def minute(self):
        return 600


class Ship:
    def __init__(self, w, n):
        self.data = TMP + "/s%d" % n
        os.mkdir(self.data)
        self.fk = FK
        self.node = S.Node(ChoiceLog(FK), n, FK, 3)
        self.radio = w.new()
        self.ble = BleSync(self.node, self.radio, {"scan_every_ms": 6000, "scan_ms": 3000})
        self.clock = Clock0()
        self.web = self.led = self.ledtest = None
        self.live = None
        self.live_why = None
        lvlive.install(self, self.data)
        self.live.cfg["dl"] = False

    def say(self, text):
        pass


def fresh(seed=1):
    clean(TMP)
    os.mkdir(TMP)
    w = bluetooth.World(seed)
    return w, Ship(w, 0), Ship(w, 1)


def run(w, a, b, pred=None, limit=400000):
    for t in range(0, limit, 10):
        w.step(10)
        a.ble.poll(w.now)
        b.ble.poll(w.now)
        if t % 100 == 0 and pred is not None and pred():
            return True
    return pred is None


def settled(w, a, b):
    ok = run(w, a, b, lambda: not a.live.out and not b.live.out and a.ble.state == b.ble.state == "idle")
    check("settled", ok)
    check("live stays on", a.live.hx is None and b.live.hx is None)


def act(s, action, **kw):
    kw["action"], kw["to"] = action, 1 - s.node.ship
    return D.action(s.live, kw)[0]


def game(s):
    return D.box(s.live)["g"][0]


def start(w, a, b):
    check("new", act(a, "new") == 200)
    check("lock invite", act(a, "invite", layout=LAY) == 200)
    settled(w, a, b)
    check("invited", game(b)["s"] == "invited")
    check("accept", act(b, "accept", layout=LAY) == 200)
    settled(w, a, b)
    check("active", game(a)["s"] == game(b)["s"] == "active")


check("packing high bits", D.encode(LAY) == bytes((0, 98, 48)))
check("roundtrip", D.fleet(D.encode(LAY)) == [[0, 1, 2], [12, 13], [35]])
for layout in ([[5, 0], [12, 0], [35, 0]], [[0, 0], [3, 0], [35, 0]], [[0, 0], [0, 1], [35, 0]]):
    try:
        D.encode(layout)
        check("illegal rejected", False)
    except ValueError:
        check("illegal rejected", True)

for seed, loss in ((2, 0), (9, 60)):
    w, a, b = fresh(seed)
    w.drop = loss
    start(w, a, b)
    check("inviter cannot fire first", act(a, "fire", cell=0) == 409)
    check("off field", act(b, "fire", cell=36) == 400)
    # The invitee sinks the fleet; the inviter fires harmless cells.
    for k, cell in enumerate((0, 1, 2, 12, 13, 35)):
        before = b.live.n["dial"]
        check("fire", act(b, "fire", cell=cell) == 200)
        check("repeat cell", act(b, "fire", cell=cell) == 400)
        check("unacked previous", act(b, "fire", cell=34) == 429)
        settled(w, a, b)
        check("shot and answer", game(a)["n"] == game(b)["n"] == 2 * k + 1)
        if not loss and k < 5:
            check("answer in same link", b.live.n["dial"] == before + 1)
        if k < 5:
            check("reply shot", act(a, "fire", cell=20 + k) == 200)
            settled(w, a, b)
    check("reveals checked", game(a)["s"] == game(b)["s"] == "done")
    check("record", D.box(a.live)["r"]["1"] == [0, 1] and D.box(b.live)["r"]["0"] == [1, 0])
    check("both fields", D.view(a.live)[0]["their"] == D.fleet(D.encode(LAY)))

# Lost answer repaired by SYNC, using a new envelope rather than replaying seq.
w, a, b = fresh(3)
start(w, a, b)
check("pending shot", act(b, "fire", cell=0) == 200)
shot = b.live.out[0][1]
D.take(a.live, 1, 5, shot[5:16])
b.live.out[:] = []
a.live.out[:] = []             # simulate an acked-but-lost answer
b.clock.t += 3600001           # SYNC is limited to once per hour per game
D.sync(b.live, game(b))
settled(w, a, b)
check("sync repaired answer", game(b)["n"] == 1 and game(b)["p"] is None)
# Day changes do not erase a duel move.
check("next move", act(a, "fire", cell=20) == 200)
a.clock.t += 86400000
I.expire(a.live)
check("one day retained", any(o[1][0] == 5 for o in a.live.out))
settled(w, a, b)
check("resign", act(a, "resign") == 200)
settled(w, a, b)
check("resign verified record", game(a)["s"] == game(b)["s"] == "done")

# Changed field is caught by the previously exchanged commitment.
w, a, b = fresh(4)
start(w, a, b)
j = D.box(a.live)
j["g"][0]["l"] = I.hexlify(D.encode([[6, 0], [24, 0], [35, 0]])).decode()
D.store(a.live, j)
check("cheating resign", act(a, "resign") == 200)
settled(w, a, b)
check("cheat caught", game(b)["s"] == "cheat")
check("no false record", not D.box(b.live)["r"])

w, a, b = fresh(5)
act(a, "new")
act(a, "invite", layout=LAY)
settled(w, a, b)
check("early call", act(a, "call") == 409)
check("decline", act(b, "decline") == 200)
settled(w, a, b)
check("decline arrived", game(a)["s"] == "declined")
act(a, "new")
act(a, "invite", layout=LAY)
settled(w, a, b)
a.clock.t += 3600001
check("old ship warning", D.view(a.live)[0]["update"])
a.clock.t += 3 * 86400000
D.view(a.live)
check("invite timeout", game(a)["s"] == "called")
# Unknown versions are rejected, future kinds do not enter the Hail inbox.
w, a, b = fresh(6)
D.take(a.live, 1, 3, bytes((2, 1, 2)) + bytes(8))
check("version END", a.live.out[-1][1][0] == 8 and a.live.out[-1][1][7] == 4)
for kind in range(10, 256):
    I._in(a.live, 1, I.item(b.live, kind, 0, bytes(11)))
check("future kinds dropped", not a.live.inb)
# Authenticated random bodies: no exceptions, regardless of kind or game id.
for k in range(1200):
    body = os.urandom(11)
    D.take(a.live, 1, 3 + k % 7, body)
check("fuzz", True)
check("fuzz queue bounded", len(a.live.out) <= 24)

# Crossing invites consistently keep ship zero's game, not two half-games.
w, a, b = fresh(7)
act(a, "new")
act(b, "new")
act(a, "invite", layout=LAY)
act(b, "invite", layout=LAY)
settled(w, a, b)
ga = [g for g in D.box(a.live)["g"] if g["s"] in D.ACTIVE]
gb = [g for g in D.box(b.live)["g"] if g["s"] in D.ACTIVE]
check("crossing invitation id", len(ga) == len(gb) == 1 and ga[0]["id"] == gb[0]["id"])
check("crossing invitation roles", ga[0]["s"] == "wait" and gb[0]["s"] == "invited")

# Resign before either side has accepted, in both directions.
for resigning in (0, 1):
    w, a, b = fresh(8)
    act(a, "new")
    act(a, "invite", layout=LAY)
    settled(w, a, b)
    check("pre-accept resign", act(a if resigning == 0 else b, "resign") == 200)
    settled(w, a, b)
    check("pre-accept both recorded", game(a)["s"] == game(b)["s"] == "done")
    check("pre-accept loss counted", D.box((a if resigning == 0 else b).live)["r"][str(1 - resigning)] == [0, 1])

# Capacity and validation do not mutate locked games.
w, a, b = fresh(11)
for to in (1, 2, 3):
    check("three games allowed", D.action(a.live, {"action": "new", "to": to})[0] == 200)
check("fourth refused", D.action(a.live, {"action": "new", "to": 4})[0] == 409)
check("same peer refused", act(a, "new") == 409)
check("accept cannot invite", act(a, "accept", layout=LAY) == 409)
check("bad layout action", act(a, "invite", layout=[[0, 0], [1, 0], [2, 0]]) == 400)
check("invite", act(a, "invite", layout=LAY) == 200)
check("locked cannot move", act(a, "lock", layout=LAY) == 409)
before = len(D.box(a.live)["g"])
for k in range(6):
    D.take(a.live, 4, 3, bytes((1, 55, k)) + bytes(8))
check("inbound capacity", len(D.box(a.live)["g"]) == before)

# All 71 global shot numbers are needed when the invitee's last hit is last.
w, a, b = fresh(12)
start(w, a, b)
cells = [c for c in range(36) if c != 35] + [35]
for k, cell in enumerate(cells):
    check("long game invitee fire", act(b, "fire", cell=cell) == 200)
    settled(w, a, b)
    if k < 35:
        check("long game inviter fire", act(a, "fire", cell=cell) == 200)
        settled(w, a, b)
check("71 shots finish", game(a)["n"] == game(b)["n"] == 71 and game(a)["s"] == game(b)["s"] == "done")
check("compact complete history", len(game(a)["h"]) == 142)
check("full replay record", D.box(b.live)["r"]["0"] == [1, 0])

# Preserve the original commitment but lie about an answer: replay catches it.
w, a, b = fresh(13)
start(w, a, b)
act(b, "fire", cell=0)
settled(w, a, b)
j = D.box(b.live)
j["g"][0]["h"] = "Aa"           # claim the hit was answered as a miss
D.store(b.live, j)
act(a, "resign")
settled(w, a, b)
check("full answer replay caught lie", game(b)["s"] == "cheat")

# Equal-authority conflict: both think it is their turn. Lower ship wins.
w, a, b = fresh(14)
start(w, a, b)
j = D.box(a.live)
j["g"][0]["h"], j["g"][0]["n"] = "Ab", 1
D.store(a.live, j)
ga = game(a)
D.take(b.live, 0, 9, D.gid(ga) + bytes((1, 0, 1, 1)) + bytes(5))
check("lower view wins", game(b)["n"] == 1 and not D.view(b.live)[0]["turn"])
# A higher ship that has extra history rewinds to the authoritative prefix.
j = D.box(b.live)
j["g"][0]["h"], j["g"][0]["n"] = "AbUa", 2
D.store(b.live, j)
D.take(b.live, 0, 9, D.gid(ga) + bytes((1, 0, 1, 1)) + bytes(5))
check("higher view rewinds", game(b)["n"] == 1 and game(b)["h"] == "Ab")

# The board API is signed-in just like Hail, and the Settings switch persists.
import lvliveapi
class Request:
    method, path, body, q = "POST", "/api/live/duel", b'{"action":"new","to":1}', {}
    def header(self, key):
        return None
class Phone:
    signed = False
    def who(self, req):
        return 0 if self.signed else None
class Web:
    def __init__(self, ship):
        self.ship, self.phone = ship, Phone()
    def get_phone(self):
        return self.phone
w, a, b = fresh(15)
web = Web(a)
check("duel auth", lvliveapi.api(web, Request())[0] == 401)
web.phone.signed = True
# The simple clock fixture has no header learner: API learns through the real clock.
a.clock = Clock()
a.clock.learn(1792936800000, -300)
check("duel signed in", lvliveapi.api(web, Request())[0] == 200)
check("dl defaults on", lvliveapi.state(a, 0)["dl"] is True)
lvliveapi.setting(a, {"dl": False})
check("dl persisted", I.load(a.data + "/live.json")["dl"] is False)
check("hail switch independent", lvliveapi.state(a, 0)["light"] is True)

# Turn light guards share the Hail allowance, with their own switch.
import lvflick
old_start = lvflick.start
lvflick.start = lambda sh, duel=False: True
a.clock = Clock0()
check("duel light off", not lvflick.maybe(a.live, True))
a.live.cfg["dl"] = True
check("duel light on", lvflick.maybe(a.live, True))
check("shared allowance", a.live.lc[1] == 1)
a.clock.minute = lambda: 1400
check("quiet hours", not lvflick.maybe(a.live, True))
a.clock.minute = lambda: 600
a.live.lc[1] = 12
check("allowance exhausted", not lvflick.maybe(a.live, True))
lvflick.start = old_start

# Exercise the actual software-PWM coroutine on a virtual clock. Every sleep
# advances time, so this is deterministic on both unix MicroPython and CPython.
import lvship
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
ticks = [0]
saved_time = lvship.ticks_ms, lvship.ticks_diff, lvship.sleep_ms
async def virtual_sleep(ms):
    ticks[0] += ms
lvship.ticks_ms = lambda: ticks[0]
lvship.ticks_diff = lambda x, y: x - y
lvship.sleep_ms = virtual_sleep
class Pin:
    def __init__(self):
        self.writes = []
    def value(self, v):
        self.writes.append((ticks[0], v))
class Light:
    def _hold(self, sh, release=False):
        pass
    def _busy(self, sh):
        return 1200 <= ticks[0] < 2000
pin = Pin()
try:
    asyncio.run(lvflick.play(a, pin, Light(), True))
finally:
    lvship.ticks_ms, lvship.ticks_diff, lvship.sleep_ms = saved_time
high = [t for t, v in pin.writes if v]
check("software PWM exercised", len(high) > 200)
check("two-pulse on windows", all(t % 1000 < 600 for t in high))
check("link stays dark", not any(1200 <= t < 2000 for t in high))
check("eight second pattern", 8000 <= ticks[0] <= 8020)
check("pin released dark", pin.writes[-1][1] == 0 and a.ledtest is None)

print("duel: %d checks passed" % COUNT[0])
clean(TMP)
