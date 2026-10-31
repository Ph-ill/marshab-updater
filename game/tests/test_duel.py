#!/usr/bin/env python3
# Two ships, real sync/ble, fake radio. Also runs on MicroPython unix ports.
import os
import sys
import json
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
import lvship

try:
    from time import ticks_add
except ImportError:  # Match lv.clock's CPython ticks_diff fallback.
    def ticks_add(t, delta):
        return (t + delta) & 0x3fffffff

TICKS_MAX = ticks_add(0, -1)
real_ticks = lvship.ticks_ms
elapsed = [0]
# Use the same period as lvship.ticks_diff (not always 2^30 on unix).
# Total simulated uptime can exceed ticks_add's signed half-period bound.
lvship.ticks_ms = lambda: (real_ticks() + elapsed[0]) & TICKS_MAX


def idle(s, ms):
    elapsed[0] += ms
    s.clock.t += ms

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


check("native tick wrap preserves elapsed time",
      lvship.ticks_diff(ticks_add(TICKS_MAX - 1000, 172801000),
                        TICKS_MAX - 1000) == 172801000)


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

# A full-state response defers a real radio SHOT without acknowledging or
# mutating it. The same durable envelope is retried after the stream releases.
w, a, b = fresh(161)
start(w, a, b)


class StateStream:
    busy = 1
    radio_hold = True


a.web = StateStream()
check("held shot queued", act(b, "fire", cell=0) == 200)
held_shot = b.live.out[0][1]
check("held shot core finishes", run(w, a, b, lambda: a.live.n["held"] > 0
      and a.ble.state == b.ble.state == "idle"))
check("held shot unchanged", game(a)["n"] == 0 and game(b)["p"] == 0
      and len(b.live.out) == 1 and b.live.out[0][1] == held_shot)
a.web.radio_hold = False
a.web.busy = 0
settled(w, a, b)
check("held shot retried exactly once", game(a)["n"] == game(b)["n"] == 1
      and game(b)["p"] is None and len(game(a)["h"]) == 2)

# Lost answer repaired by SYNC, using a new envelope rather than replaying seq.
w, a, b = fresh(3)
start(w, a, b)
check("pending shot", act(b, "fire", cell=0) == 200)
shot = b.live.out[0][1]
D.take(a.live, 1, 5, shot[5:16])
b.live.out[:] = []
a.live.out[:] = []             # simulate an acked-but-lost answer
# Simulate an hour of uptime, independently of the phone's epoch.
import lvship
old_tick = lvship.ticks_ms
tick = old_tick()
lvship.ticks_ms = lambda: ticks_add(tick, 3600001)
j = D.box(b.live)
D.sync(b.live, j["g"][0])
D.store(b.live, j)
lvship.ticks_ms = old_tick
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
old_tick = lvship.ticks_ms
tick = old_tick()
lvship.ticks_ms = lambda: ticks_add(tick, 3600001)
check("old ship warning", D.view(a.live)[0]["update"])
lvship.ticks_ms = old_tick
idle(a, 3 * 86400000)
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

# Equal wire IDs still represent opposing inviter roles, not duplicates.
w, a, b = fresh(17)
act(a, "new")
act(b, "new")
j = D.box(b.live)
j["g"][0]["id"] = game(a)["id"]
D.store(b.live, j)
act(a, "invite", layout=LAY)
act(b, "invite", layout=LAY)
settled(w, a, b)
check("equal ID roles", game(a)["s"] == "wait" and game(b)["s"] == "invited")
counts = (a.live.n["out"], b.live.n["out"])
run(w, a, b)
check("equal ID no unsolicited traffic", counts == (a.live.n["out"], b.live.n["out"]))

# Before either side has accepted, nobody joined a game: the inviter withdraws and the
# invitee declines, with no record (review 0.3.1-6 #3). Resign is refused on both
# ships until a game is joined (review 0.3.1-7 #1).
for resigning in (0, 1):
    w, a, b = fresh(8)
    act(a, "new")
    act(a, "invite", layout=LAY)
    settled(w, a, b)
    check("pre-accept resign refused", act(a, "resign") == 409 and act(b, "resign") == 409
          and game(a)["s"] == "wait" and game(b)["s"] == "invited")
    check("withdraw refused on the invited ship", act(b, "withdraw") == 409)
    check("pre-accept withdraw or decline", act(a, "withdraw") == 200 if resigning == 0 else act(b, "decline") == 200)
    settled(w, a, b)
    check("pre-accept both put away", game(a)["s"] == game(b)["s"] == ("called" if resigning == 0 else "declined"))
    check("pre-accept nothing recorded", D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {})

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

# Moves are append-only (review 0.3.1-4 #2). Reviewer's repro: ship 0 forges a SYNC
# for shot 1 while it is ship 1's turn, after ship 1 has sunk the 3-ship.
w, a, b = fresh(14)
start(w, a, b)
for k, cell in enumerate((0, 20, 1, 21, 2, 22)):
    check("append-only fire", act(b if k % 2 == 0 else a, "fire", cell=cell) == 200)
    settled(w, a, b)
before = game(b)["h"]
check("append-only setup", before == "AbUaBbVaCeWa" and D.view(b.live)[0]["turn"])
ga = game(a)
D.take(b.live, 0, 9, D.gid(ga) + bytes((1, 0, 1, 1)) + bytes(5))
check("forged deep SYNC keeps every move", game(b)["n"] == 6 and game(b)["h"] == before
      and D.view(b.live)[0]["turn"] and game(b)["s"] == "active")
D.take(b.live, 0, 5, D.gid(ga) + bytes((2, 25)) + bytes(7))
check("answered shot can't be fired again", game(b)["h"] == before)
# A SYNC whose move differs from the recorded one contradicts committed history.
D.take(b.live, 0, 9, D.gid(ga) + bytes((2, 25, 0, 1)) + bytes(5))
check("contradicting SYNC ends with no result", game(b)["s"] == "cheat" and not game(b).get("doubt"))
settled(w, a, b)
check("other ship is told neutrally", game(a)["s"] == "cheat" and game(a).get("doubt") == 1)
check("no record either side", D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {})

# The peer can't make up this ship's shot or its result (review 0.3.1-4 #3).
w, a, b = fresh(16)
start(w, a, b)
act(b, "fire", cell=0)
settled(w, a, b)
act(a, "fire", cell=20)
settled(w, a, b)
D.take(b.live, 0, 9, D.gid(game(a)) + bytes((3, 30, 0, 1)) + bytes(5))
check("forged own shot refused", game(b)["n"] == 2 and game(b)["h"] == "AbUa"
      and game(b).get("p") is None and D.view(b.live)[0]["turn"])
check("own turn kept", act(b, "fire", cell=30) == 200)
settled(w, a, b)
check("real shot answered", game(b)["h"] == "AbUa_a" and game(a)["h"] == "AbUa_a")

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

# Review round 1: the fleet-ending answer and reveal are one durable reply group.
w, a, b = fresh(31)
start(w, a, b)
for k, cell in enumerate((0, 1, 2, 12, 13)):
    act(b, "fire", cell=cell)
    settled(w, a, b)
    act(a, "fire", cell=20 + k)
    settled(w, a, b)
for k in range(23):
    I.send(a.live, 8, 2, bytes((90, k, 3)))
ident = D.gid(game(a))
D.take(a.live, 1, 5, ident + bytes((11, 35)) + bytes(7))
check("23-slot reveal not falsely sent", not game(a).get("sent"))
check("23-slot reply group durable", len(game(a).get("q", [])) == 2)
# Peer verification must not make a still-unsent local reveal disappear.
peer = game(b)
D.take(a.live, 1, 7, ident + D.encode(LAY) + D.unhexlify(peer["salt"]))
check("terminal keeps unsent reveal", game(a)["s"] == "done" and not game(a).get("sent") and len(game(a)["q"]) == 2)
a.live.out[:] = []
I.keep(a.live)
D.maintain(a.live)
check("final answer and reveal retried", [o[1][0] for o in a.live.out] == [6, 7])

# Two saturated boxes must still acknowledge items, including later trailer ACKs.
class Trailer:
    def __init__(self, to):
        self.to, self.acks = to, []
w, a, b = fresh(32)
for k in range(24):
    I.send(a.live, 8, 1, bytes((70, k, 3)))
    I.send(b.live, 8, 0, bytes((80, k, 3)))
sa, sb = Trailer(1), Trailer(0)
a.live.take(sa, b.live.trailer(sb, True), 0)
check("saturated incoming END acknowledged", bool(sa.acks))
first = a.live.out[0][1]
incoming = I.item(b.live, 3, 0, bytes((1, 22, 33)) + bytes(8))
ack = I.item(b.live, 0, 0, first[2:5], 0)
a.live.take(sa, bytes((lvlive.MARK, 2)) + incoming + ack, 0)
check("ACK after full-box item processed", not any(o[1] == first for o in a.live.out))
# A known duplicate is acked even when no outgoing capacity is available.
a.live.take(sa, bytes((lvlive.MARK, 1)) + incoming, 0)
check("saturated duplicate acknowledged", a.live.n["dup"] > 0)
w, a, b = fresh(36)
for k in range(24):
    I.send(a.live, 2, 1, bytes((k,)))
    I.send(b.live, 2, 0, bytes((k,)))
sa, sb = Trailer(1), Trailer(0)
for k in range(80):
    a.live.take(sa, b.live.trailer(sb, True), 0)
    b.live.take(sb, a.live.trailer(sa, True), 0)
check("bidirectional saturation drains via ACKs", not a.live.out and not b.live.out and a.live.n["acked"] == b.live.n["acked"] == 24)

# Terminal cleanup must not depend on making the transition inside maintain().
w, a, b = fresh(33)
start(w, a, b)
act(b, "fire", cell=0)
idle(b, 3 * 86400000 + 1000)
for k in range(23):
    I.send(b.live, 2, 2, bytes((k,)))
check("call works with full outbox", act(b, "call") == 200)
check("called shot purged", not any(o[1][0] == 5 for o in b.live.out))
D.maintain(b.live)
check("call keeps bounded END", sum(o[1][0] == 8 for o in b.live.out) == 1)
# The END still owed to the absent crewmate keeps the rematch until it is delivered
# (review 0.3.1-7 #2): dropping it with the old game could strand the other ship.
r = D.action(b.live, {"action": "new", "to": 0})
check("absent peer rematch waits for the END", r[0] == 409 and "still on its way" in r[1]["err"]
      and sum(o[1][0] == 8 for o in b.live.out) == 1 and game(b)["s"] == "called")
b.live.out[:] = [o for o in b.live.out if o[1][0] != 8]
check("absent peer rematch", act(b, "new") == 200)
D.maintain(b.live)
check("orphan END swept", not any(3 <= o[1][0] <= 9 for o in b.live.out))
w, a, b = fresh(34)
start(w, a, b)
act(b, "fire", cell=0)
D.take(b.live, 0, 8, D.gid(game(b)) + bytes((3,)) + bytes(8))
check("received END purges shot", not any(o[1][0] == 5 for o in b.live.out))

# Fail before and after EVERY save in each publication path, then reload both
# files as after power loss. Check the durable state at the instant of enqueue.
import lvlivex
def persistence_case(which):
    w, a, b = fresh(35)
    if which == "invite":
        act(a, "new")
        return a, lambda: act(a, "invite", layout=LAY)
    if which == "accept":
        act(a, "new")
        act(a, "invite", layout=LAY)
        settled(w, a, b)
        return b, lambda: act(b, "accept", layout=LAY)
    start(w, a, b)
    if which in ("answer", "reveal"):
        # Ten legal alternating shots, one remaining fleet cell on either side.
        h = ""
        fired = []
        for k, cell in enumerate((0, 1, 2, 12, 13)):
            r = D.result(D.encode(LAY), fired, cell)
            fired.append(cell)
            h += chr(65 + cell) + chr(97 + r) + chr(85 + k) + "a"
        for s in (a, b):
            j = D.box(s.live)
            j["g"][0]["h"], j["g"][0]["n"] = h, 10
            D.store(s.live, j)
        if which == "answer":
            return a, lambda: D.take(a.live, 1, 5, D.gid(game(a)) + bytes((11, 35)) + bytes(7))
        j = D.box(b.live)
        j["g"][0]["p"] = 35
        D.store(b.live, j)
        return b, lambda: D.take(b.live, 0, 6, D.gid(game(b)) + bytes((11, 35, 10)) + bytes(6))
    if which == "shot":
        return b, lambda: act(b, "fire", cell=0)
    if which == "resign":
        return a, lambda: act(a, "resign")
    act(b, "fire", cell=0)
    idle(b, 3 * 86400000 + 1000)
    return b, lambda: act(b, "call") if which == "end" else D.take(b.live, 0, 8, D.gid(game(b)) + bytes((3,)) + bytes(8))


def durable_items(s, obj):
    from binascii import unhexlify
    g = game(s)
    for o in obj.get("o", []):
        b = unhexlify(o[1])
        if b[0] in (3, 4):
            check("commitment saved before publication", b[8:16] == D.commit(D.gid(g), unhexlify(g["l"]), unhexlify(g["salt"])))
        elif b[0] == 5:
            check("shot saved before publication", g.get("p") == b[8])
        elif b[0] == 6:
            check("answer saved before publication", g["n"] >= b[7])
        elif b[0] == 7:
            check("reveal state saved before publication", g["s"] in ("reveal", "done"))
        elif b[0] == 8:
            check("END state saved before publication", g["s"] not in ("draft", "wait", "invited", "active"))


for which in ("invite", "accept", "shot", "answer", "reveal", "end", "resign", "received_end"):
    # Discover the actual save count instead of assuming a fixed implementation.
    s, operation = persistence_case(which)
    original_d, original_i = D.save, I.save
    events = []
    def record(path, obj, parts=None):
        events.append(path)
        if path == s.live.f:
            durable_items(s, json.loads("".join(parts)) if parts is not None else obj)
            parts = I.boxparts(s.live)
        original_d(path, obj, parts)
    D.save = I.save = record
    try:
        operation()
    finally:
        D.save, I.save = original_d, original_i
    for boundary in range(len(events)):
        for after in (False, True):
            for restart in (False, True):
                s, operation = persistence_case(which)
                calls = [0]
                def fail(path, obj, parts=None):
                    n = calls[0]
                    calls[0] += 1
                    if path == s.live.f:
                        durable_items(s, json.loads("".join(parts)) if parts is not None else obj)
                        parts = I.boxparts(s.live)
                    if n == boundary and not after:
                        raise MemoryError("injected persistence failure")
                    original_d(path, obj, parts)
                    if n == boundary and after:
                        raise MemoryError("injected persistence failure")
                D.save = I.save = fail
                try:
                    operation()
                    check("injected boundary reached", False)
                except MemoryError:
                    pass
                finally:
                    D.save, I.save = original_d, original_i
                lock = (game(s).get("l"), game(s).get("salt"))
                if restart:
                    lvlivex.setup(s.live, s, s.data, s.live.cfg)
                D.maintain(s.live)
                # Retrying a failed pre-intent action is allowed; later retries are
                # idempotent or refused, but must never mint a second commitment.
                operation()
                D.maintain(s.live)
                if lock[0]:
                    check("recovered immutable lock", lock == (game(s).get("l"), game(s).get("salt")))
                durable_items(s, I.load(s.live.f))
                check("recovery obligations drained", not game(s).get("q"))

# Include the trailer's final high-water save: a failure there must not roll
# back an already-published final reveal to an older in-memory outbox.
for boundary in range(5):
    for after in (False, True):
        s, unused = persistence_case("answer")
        # Continue the peer's accepted epoch, rather than randomly colliding
        # with it and having replay protection skip the injected save fault.
        epoch, previous = s.live.hw[1][:2]
        sequence = previous + 1
        body = bytes((5, 0, epoch, sequence >> 8, sequence & 255)) + D.gid(game(s)) + bytes((11, 35)) + bytes(7)
        frame = bytes((lvlive.MARK, 1)) + body + I.mac(s.live, 1, body)
        session = Trailer(1)
        calls = [0]
        original_d, original_i = D.save, I.save
        def fail_trailer(path, obj, parts=None):
            n = calls[0]
            calls[0] += 1
            if n == boundary and not after:
                raise MemoryError("injected trailer persistence failure")
            original_d(path, obj, parts)
            if n == boundary and after:
                raise MemoryError("injected trailer persistence failure")
        D.save = I.save = fail_trailer
        sys.modules["lvlivein"], sys.modules["lvduel"] = I, D
        try:
            s.live.take(session, frame, 0)
        finally:
            D.save, I.save = original_d, original_i
        check("trailer fault reached", calls[0] > boundary and not session.acks)
        D.maintain(s.live)
        sys.modules["lvlivein"], sys.modules["lvduel"] = I, D
        s.live.take(Trailer(1), frame, 0)
        D.maintain(s.live)
        check("trailer rollback retains final reply group", all(any(o[1][0] == kind for o in s.live.out) for kind in (6, 7)))

# Recovery uses uptime, never a learned epoch or a saved pre-reboot tick value.
import lvship
saved_ticks, saved_diff = lvship.ticks_ms, lvship.ticks_diff
uptime = [1000]
lvship.ticks_ms = lambda: uptime[0] & 0x3fffffff
lvship.ticks_diff = lvlive.dt
try:
    w, a, b = fresh(37)
    start(w, a, b)
    a.clock.known = lambda: False
    a.live.out[:] = []
    I.keep(a.live)
    j = D.box(a.live)
    j["g"][0].pop("sync", None)
    D.sync(a.live, j["g"][0])
    D.store(a.live, j)
    a.live.out[:] = []
    I.keep(a.live)
    uptime[0] += 3600001
    j = D.box(a.live)
    D.sync(a.live, j["g"][0])
    D.store(a.live, j)
    check("unknown-clock SYNC retries on uptime", any(o[1][0] == 9 for o in a.live.out))
    a.live.out[:] = []
    I.keep(a.live)
    a.clock.known = lambda: True
    a.clock.t += 20 * 86400000
    j = D.box(a.live)
    D.sync(a.live, j["g"][0])
    D.store(a.live, j)
    check("learning epoch cannot bypass throttle", not a.live.out)
    a.clock.t -= 40 * 86400000
    uptime[0] += 3600001
    j = D.box(a.live)
    D.sync(a.live, j["g"][0])
    D.store(a.live, j)
    check("backward epoch cannot suppress retry", bool(a.live.out))
    a.clock.known = lambda: False
    a.live.out[:] = []
    I.keep(a.live)
    uptime[0] += 21600001
    D.maintain(a.live)
    check("six-hour recovery without phone", any(o[1][0] == 9 for o in a.live.out))
    # A reboot discards throttle stamps, even if the persisted stamp is ahead.
    a.live.out[:] = []
    I.keep(a.live)
    lvlivex.setup(a.live, a, a.data, a.live.cfg)
    uptime[0] = 10
    D.maintain(a.live)
    check("restart can recover without epoch", any(o[1][0] == 9 for o in a.live.out))
    a.live.out[:] = []
    I.keep(a.live)
    # Accumulate across the MicroPython tick wrap, without a wall clock.
    for delta in (400000000, 400000000, 300000000):
        uptime[0] += delta
        D.maintain(a.live)
        a.live.out[:] = []
        I.keep(a.live)
    uptime[0] += 3600001
    D.maintain(a.live)
    check("wrapped uptime recovery", any(o[1][0] == 9 for o in a.live.out))
finally:
    lvship.ticks_ms, lvship.ticks_diff = saved_ticks, saved_diff

# Rejections exist only while their durable reply cannot enter the shared box.
w, a, b = fresh(41)
for k in range(24):
    I.send(a.live, 2, 1, bytes((1, 0, k)))
for sender in range(1, 8):
    D.take(a.live, sender, 3, bytes((2, sender, 99)) + bytes(8))
check("seven pending rejections", len(D.box(a.live).get("e", [])) == 7)
a.live.out[:] = []
I.keep(a.live)
D.maintain(a.live)
check("all rejection replies survive", len(a.live.out) == 7 and all(o[1][0] == 8 for o in a.live.out))
for to, item, date in list(a.live.out):
    ack = I.item(a.live, 0, 0, item[2:5], 0)
    frame = bytes((lvlive.MARK, 1)) + ack[:16] + I.mac(a.live, to, ack[:16])
    sys.modules["lvlivein"], sys.modules["lvduel"] = I, D
    a.live.take(Trailer(to), frame, 0)
D.maintain(a.live)
check("rejections retire after durable delivery", not D.box(a.live).get("e") and not a.live.out)

# Unsent drafts can be discarded under pressure without protocol traffic.
w, a, b = fresh(42)
for to in (1, 2, 3):
    check("abandon draft", D.action(a.live, {"action": "new", "to": to})[0] == 200)
check("discard draft", act(a, "discard") == 200)
check("discard is silent", not a.live.out and len(D.box(a.live)["g"]) == 2)
check("fourth after discard", D.action(a.live, {"action": "new", "to": 4})[0] == 200)
idle(a, 4 * 86400000)
D.maintain(a.live)
check("stale drafts removed silently", not D.box(a.live)["g"] and not a.live.out)
check("fourth after expiry", D.action(a.live, {"action": "new", "to": 5})[0] == 200)

# Terminal recovery uses the same acknowledged-but-lost model as above.
for early in (False, True):
    w, a, b = fresh(43)
    start(w, a, b)
    for k, cell in enumerate((0, 1, 2, 12, 13)):
        act(b, "fire", cell=cell)
        settled(w, a, b)
        act(a, "fire", cell=20 + k)
        settled(w, a, b)
    act(b, "fire", cell=35)
    D.take(a.live, 1, 5, b.live.out[0][1][5:16])
    answer = next(o[1][5:16] for o in a.live.out if o[1][0] == 6)
    proof = next(o[1][5:16] for o in a.live.out if o[1][0] == 7)
    a.live.out[:] = []
    b.live.out[:] = []
    I.keep(a.live)
    I.keep(b.live)
    if early:
        D.take(b.live, 0, 7, proof)
        D.take(b.live, 0, 6, answer)
        settled(w, a, b)
        check("early reveal strands only until recovery", game(a)["s"] == "done" and game(b)["s"] == "reveal")
        D.maintain(b.live)
        saved_tick = lvship.ticks_ms
        tick = saved_tick()
        lvship.ticks_ms = lambda: ticks_add(tick, 21600001)
        try:
            D.maintain(b.live)
        finally:
            lvship.ticks_ms = saved_tick
        check("reveal periodically requests recovery", any(o[1][0] == 9 for o in b.live.out))
        b.live.out[:] = []
        I.keep(b.live)
    g = game(b)
    state = 3 if early else 2
    # As lvduel.sync sends it: the last recorded move, then the state.
    last = (ord(g["h"][-2]) - 65, ord(g["h"][-1]) - 97)
    D.take(a.live, 1, 9, D.gid(g) + bytes((g["n"],) + last + (state,)) + bytes(5))
    check("terminal recovery bounded group", [o[1][0] for o in a.live.out] == [6, 7])
    settled(w, a, b)
    check("terminal recovery verifies both", game(a)["s"] == game(b)["s"] == "done")
    check("terminal recovery counts once", D.box(a.live)["r"]["1"] == [0, 1] and D.box(b.live)["r"]["0"] == [1, 0])
    D.take(a.live, 1, 7, D.gid(g) + D.unhexlify(g["l"]) + D.unhexlify(g["salt"]))
    check("verified reveal has no echo loop", not a.live.out)

# Review round 4 item 2: crossing resignations keep each local loss immutable,
# but deterministically void this game's record in either END delivery order.
for first in (0, 1):
    for delayed in (False, True):
        w, a, b = fresh(44)
        start(w, a, b)
        ships = (a, b)
        for s in ships:
            j = D.box(s.live)
            j["r"][str(1 - s.node.ship)] = [2, 3]
            D.store(s.live, j)
            check("crossing resign accepted", act(s, "resign") == 200)
        ends = [next(o[1][5:16] for o in s.live.out if o[1][0] == 8) for s in ships]
        proofs = [next(o[1][5:16] for o in s.live.out if o[1][0] == 7) for s in ships]
        if delayed:
            # Verification can beat the other END, including across reboot.
            s = ships[first]
            D.take(s.live, 1 - first, 7, proofs[1 - first])
            check("loss counted before delayed END", game(s).get("counted") == 1
                  and D.box(s.live)["r"][str(1 - first)] == [2, 4])
            lvlivex.setup(s.live, s, s.data, s.live.cfg)
        for receiver in (first, 1 - first):
            s = ships[receiver]
            D.take(s.live, 1 - receiver, 8, ends[1 - receiver])
            check("local resignation never reversed", game(s)["win"] is False)
        settled(w, a, b)
        for s in ships:
            check("crossing resign done without result", game(s)["s"] == "done"
                  and game(s).get("mutual") and not game(s).get("counted")
                  and D.box(s.live)["r"][str(1 - s.node.ship)] == [2, 3])
            check("mutual second-person phone status", D.view(s.live)[0]["status"]
                  == "Your game ended with both ships standing down. No result.")
            check("mutual status survives streamed phone snapshot", lvliveapi.state(s, 0)["duel"][0]["status"]
                  == "Your game ended with both ships standing down. No result.")
            # Fresh-envelope semantic duplicates cannot subtract twice or restart.
            D.take(s.live, 1 - s.node.ship, 8, ends[1 - s.node.ship])
            D.take(s.live, 1 - s.node.ship, 7, proofs[1 - s.node.ship])
            check("mutual duplicates keep prior record", D.box(s.live)["r"][str(1 - s.node.ship)] == [2, 3]
                  and not game(s).get("counted") and game(s)["s"] == "done")

# Crossing withdrawal and decline before acceptance: nothing is counted on either
# ship, and each keeps its own ending (review 0.3.1-6 #3).
w, a, b = fresh(45)
act(a, "new")
act(a, "invite", layout=LAY)
settled(w, a, b)
check("pre-accept crossing inviter withdraws", act(a, "withdraw") == 200)
check("pre-accept withdrawal counts nothing", not game(a).get("counted") and game(a)["s"] == "called")
check("pre-accept crossing invitee declines", act(b, "decline") == 200)
settled(w, a, b)
check("pre-accept crossing no records", not D.box(a.live)["r"] and not D.box(b.live)["r"]
      and game(a)["s"] in ("called", "declined") and game(b)["s"] == "declined")

# Real final-shot histories: END can arrive before or after the fleet-ending
# SHOT/ANSWER. The first local terminal decision wins; later END cannot rewrite
# fleet win/loss, including after reveal verification has counted the result.
for receiver in (0, 1):
    for end_first in (False, True):
        w, a, b = fresh(46)
        start(w, a, b)
        for k, cell in enumerate((0, 1, 2, 12, 13)):
            act(b, "fire", cell=cell)
            settled(w, a, b)
            act(a, "fire", cell=20 + k)
            settled(w, a, b)
        check("race final shot queued", act(b, "fire", cell=35) == 200)
        ident = D.gid(game(a))
        shot = next(o[1][5:16] for o in b.live.out if o[1][0] == 5)
        s = (a, b)[receiver]
        ending = ident + bytes((2,)) + bytes(8)
        if receiver == 1:
            D.take(a.live, 1, 5, shot)
            move = next(o[1][5:16] for o in a.live.out if o[1][0] == 6)
        else:
            move = shot
        if end_first:
            D.take(s.live, 1 - receiver, 8, ending)
        D.take(s.live, 1 - receiver, 5 if receiver == 0 else 6, move)
        expected = True if end_first else bool(receiver)
        check("race first terminal outcome", game(s)["win"] is expected)
        if not end_first:
            check("fleet ending refuses local resign", act(s, "resign") == 409)
        for reason in (1, 2, 3, 4, 5):
            D.take(s.live, 1 - receiver, 8, ident + bytes((reason,)) + bytes(8))
            check("unverified terminal outcome is immutable", game(s)["s"] == "reveal"
                  and game(s)["win"] is expected
                  and game(s).get("why") == (2 if end_first else None))
        peer = game((b, a)[receiver])
        D.take(s.live, 1 - receiver, 7, ident + D.unhexlify(peer["l"]) + D.unhexlify(peer["salt"]))
        check("race verified terminal counts", game(s)["s"] == "done" and game(s).get("counted") == 1)
        record = D.box(s.live)["r"]
        for reason in (1, 2, 3, 4, 5):
            D.take(s.live, 1 - receiver, 8, ident + bytes((reason,)) + bytes(8))
            check("late END preserves terminal cause and record", game(s)["s"] == "done"
                  and game(s)["win"] is expected and D.box(s.live)["r"] == record
                  and game(s).get("why") == (2 if end_first else None))

# A locally submitted resignation also wins against an in-flight final SHOT or
# ANSWER, not just against another END. No transcript advances after resigning.
for receiver in (0, 1):
    s, operation = persistence_case("answer" if receiver == 0 else "reveal")
    check("in-flight local resignation", act(s, "resign") == 200)
    before = game(s)["h"]
    operation()
    check("in-flight fleet result cannot reverse resignation", game(s)["win"] is False
          and game(s)["why"] == 2 and game(s)["h"] == before)

# One idle policy for drafts, invitations and pending shots, even without epoch.
for state in ("draft", "wait", "invited", "pending"):
    for correction in (None, 10 * 86400000, -10 * 86400000):
        w, a, b = fresh(46)
        if state == "pending":
            start(w, a, b)
            s = b
            s.clock.known = lambda: False
            act(s, "fire", cell=0)
        else:
            s = a
            a.clock.known = b.clock.known = lambda: False
            act(a, "new")
            if state != "draft":
                act(a, "invite", layout=LAY)
            if state == "invited":
                settled(w, a, b)
                s = b
        idle(s, 86400000)
        D.maintain(s.live)
        check("unknown clock preserves one day idle", D.maint_call("age", s.live, game(s)) >= 86400)
        if correction is not None:
            s.clock.t += correction
            s.clock.known = lambda: True
            D.maintain(s.live)
            g = game(s)
            check("learned epoch preserves actual idle", abs(D.now(s.live) - g["t"] - 86400) <= 1)
            # Another correction in the opposite direction cannot reset age.
            s.clock.t -= 2 * correction
            D.maintain(s.live)
            check("corrected epoch preserves actual idle", abs(D.now(s.live) - game(s)["t"] - 86400) <= 1)
        if state == "pending":
            check("one day cannot Call it", act(s, "call") == 409)
        else:
            check("fresh corrected deadline not expired", game(s)["s"] == state)
        # Restart with an unknown clock: checkpointed idle survives, raw ticks do not.
        s.clock.known = lambda: False
        lvlivex.setup(s.live, s, s.data, s.live.cfg)
        D.maintain(s.live)
        check("reboot retains checkpointed idle", D.maint_call("age", s.live, game(s)) >= 86400)
        idle(s, 2 * 86400000 + 1000)
        D.maintain(s.live)
        if state == "pending":
            check("unknown clock Call it after three days", act(s, "call") == 200)
        elif state == "draft":
            check("unknown clock draft expires", not D.box(s.live)["g"])
        else:
            check("unknown clock invitation expires", game(s)["s"] == "called")

# Known-clock downtime counts after reboot, and ticks wrap without changing age.
w, a, b = fresh(47)
act(a, "new")
act(a, "invite", layout=LAY)
a.clock.t += 2 * 86400000
lvlivex.setup(a.live, a, a.data, a.live.cfg)
D.maintain(a.live)
check("known clock reboot counts downtime", D.maint_call("age", a.live, game(a)) >= 2 * 86400)
idle(a, 86400000 + 1000)
D.maintain(a.live)
check("known reboot expires at total three days", game(a)["s"] == "called")
old_tick = lvship.ticks_ms
wrap = [TICKS_MAX - 1000]
lvship.ticks_ms = lambda: wrap[0]
try:
    w, a, b = fresh(48)
    a.clock.known = lambda: False
    act(a, "new")
    wrap[0] = ticks_add(wrap[0], 86400000)
    D.maintain(a.live)
    check("wrapped tick preserves one day", D.maint_call("age", a.live, game(a)) == 86400)
    wrap[0] = ticks_add(wrap[0], 2 * 86400000)
    D.maintain(a.live)
    check("wrapped tick expires draft", not D.box(a.live)["g"])
finally:
    lvship.ticks_ms = old_tick

# END 6 carries no evidence (review 0.3.1-4 #4). Reviewer's repro: ship 1 wins a
# verified game, then ship 0 sends END 6.
w, a, b = fresh(50)
start(w, a, b)
for k, cell in enumerate((0, 1, 2, 12, 13)):
    act(b, "fire", cell=cell)
    settled(w, a, b)
    act(a, "fire", cell=20 + k)
    settled(w, a, b)
act(b, "fire", cell=35)
settled(w, a, b)
check("clean win recorded", game(b)["s"] == "done" and D.box(b.live)["r"] == {"0": [1, 0]})
D.take(b.live, 0, 8, D.gid(game(b)) + bytes((6,)) + bytes(8))
check("END 6 after a verified finish keeps the win", game(b)["s"] == "done" and game(b)["win"] is True
      and D.box(b.live)["r"] == {"0": [1, 0]})
check("END 6 after a finish is shown neutrally", D.view(b.live)[0]["doubt"] == 1)
D.take(b.live, 0, 7, D.gid(game(a)) + bytes(9))
check("REVEAL after a verified finish changes nothing", game(b)["s"] == "done"
      and D.box(b.live)["r"] == {"0": [1, 0]})
# Mid-game, with no result decided: no result, no empty record.
w, a, b = fresh(51)
start(w, a, b)
act(b, "fire", cell=0)
settled(w, a, b)
j = D.box(b.live)
j["r"]["0"] = [0, 0]
D.store(b.live, j)
D.take(b.live, 0, 8, D.gid(game(b)) + bytes((6,)) + bytes(8))
check("mid-game END 6 ends with no result", game(b)["s"] == "cheat" and game(b).get("doubt") == 1)
check("no [0, 0] record", D.box(b.live)["r"] == {})
# After the final hit but before the reveal: this ship's own answers are no proof of
# the other field (review 0.3.1-5 #1). Only a verified REVEAL decides the result.
w, a, b = fresh(52)
start(w, a, b)
for k, cell in enumerate((0, 1, 2, 12, 13)):
    act(b, "fire", cell=20 + k)
    settled(w, a, b)
    act(a, "fire", cell=cell)
    settled(w, a, b)
act(b, "fire", cell=30)
settled(w, a, b)
act(a, "fire", cell=35)
D.take(b.live, 0, 5, a.live.out[0][1][5:16])
a.live.out[:] = []
b.live.out[:] = []
check("loser in reveal", game(b)["s"] == "reveal" and game(b)["win"] is False)
import lvduellayout as real_layout
calls = []


class LayoutSpy:
    def __getattr__(self, name):
        calls.append(name)
        return getattr(real_layout, name)


sys.modules["lvduellayout"] = LayoutSpy()
try:
    D.take(b.live, 0, 8, D.gid(game(b)) + bytes((6,)) + bytes(8))
finally:
    lvship.drop("lvduellayout")
check("END 6 in reveal ends with no result", game(b)["s"] == "cheat"
      and game(b).get("doubt") == 1 and not game(b).get("verified") and D.box(b.live)["r"] == {})
check("END 6 in reveal runs no layout rules (review 0.3.1-5 #2)", calls == [])
D.take(b.live, 0, 7, D.gid(game(b)) + bytes.fromhex(game(a)["l"]) + bytes.fromhex(game(a)["salt"]))
check("a REVEAL after END 6 can't revive a result", game(b)["s"] == "cheat" and D.box(b.live)["r"] == {})

# Review 0.3.1-5 #1 repro: a winner answers "miss" to five real hits, sinks the
# loser's fleet, then sends END 6 instead of its REVEAL. The honest loser records
# nothing; with the honest REVEAL instead, the lie is caught the same way.
for final in ("reveal", "end6"):
    w, a, b = fresh(60)
    start(w, a, b)
    ident = D.gid(game(b))
    a.live.out[:] = []
    b.live.out[:] = []
    for k, (mine_b, theirs) in enumerate(zip((0, 1, 2, 12, 13, 30), (0, 1, 2, 12, 13, 35))):
        n = 2 * k + 1
        check("lying winner: fire", act(b, "fire", cell=mine_b) == 200)
        D.take(b.live, 0, 6, ident + bytes((n, mine_b, 0)) + bytes(6))
        D.take(b.live, 0, 5, ident + bytes((n + 1, theirs)) + bytes(7))
        b.live.out[:] = []
    check("lying winner: loser in reveal", game(b)["s"] == "reveal" and game(b)["win"] is False)
    if final == "reveal":
        D.take(b.live, 0, 7, ident + bytes.fromhex(game(a)["l"]) + bytes.fromhex(game(a)["salt"]))
        check("lying winner's REVEAL is caught", game(b)["s"] == "cheat"
              and not game(b).get("doubt") and D.box(b.live)["r"] == {})
    else:
        D.take(b.live, 0, 8, ident + bytes((6,)) + bytes(8))
        check("lying winner's END 6 records no loss", game(b)["s"] == "cheat"
              and game(b).get("doubt") == 1 and D.box(b.live)["r"] == {})
        x = D.view(b.live)[0]
        check("lying winner: no field shown as revealed", x["their"] is None and x["s"] == "cheat")

# A real resignation keeps its result through END 6, on either side.
for side in ("loser", "winner"):
    w, a, b = fresh(61)
    start(w, a, b)
    act(b, "fire", cell=20)
    settled(w, a, b)
    a.live.out[:] = []
    b.live.out[:] = []
    if side == "loser":
        check("resign", act(b, "resign") == 200)
    else:
        D.take(b.live, 0, 8, D.gid(game(b)) + bytes((2,)) + bytes(8))
    b.live.out[:] = []
    g = game(b)
    want = {"0": [0, 1]} if side == "loser" else {"0": [1, 0]}
    if g["s"] != "done":
        D.take(b.live, 0, 8, D.gid(game(b)) + bytes((6,)) + bytes(8))
    check("END 6 after a real resignation (%s) keeps the result" % side, game(b)["s"] == "done"
          and D.box(b.live)["r"] == want)

# A ship that answers every shot impossibly is caught without a reveal (review 0.3.1-4 #5).
for answer, shots in ((0, 31), (1, 6)):
    w, a, b = fresh(53)
    start(w, a, b)
    ident = D.gid(game(b))
    theirs = [c for c in range(36) if c not in (0, 1, 2, 12, 13, 35)]
    for k in range(shots):
        n = 2 * k + 1
        check("liar fire", act(b, "fire", cell=k) == 200)
        D.take(b.live, 0, 6, ident + bytes((n, k, answer)) + bytes(6))
        if k < shots - 1:
            check("liar game still open", game(b)["s"] == "active")
            D.take(b.live, 0, 5, ident + bytes((n + 1, theirs[k])) + bytes(7))
        b.live.out[:] = []
    check("impossible answers end with no result", game(b)["s"] == "cheat"
          and not game(b).get("doubt") and D.box(b.live)["r"] == {})

# Call it is never for your own turn (review 0.3.1-4 #8).
w, a, b = fresh(54)
start(w, a, b)
code, body = D.action(b.live, {"action": "call", "to": 0})
check("own turn: It's your move", code == 409 and body["err"].startswith("It's your move."))
act(b, "fire", cell=0)
settled(w, a, b)
code, body = D.action(b.live, {"action": "call", "to": 0})
check("their turn: three days", code == 409 and "three days" in body["err"])

# Time switched off counts once the clock is known again (review 0.3.1-4 #6), and
# only as much as really passed.
for days, ok in ((4, True), (1, False)):
    w, a, b = fresh(55)
    start(w, a, b)
    act(b, "fire", cell=0)
    settled(w, a, b)
    b.clock.known = lambda: False
    lvlivex.setup(b.live, b, b.data, b.live.cfg)
    D.maintain(b.live)
    idle(b, 60000)
    D.maintain(b.live)
    b.clock.t += days * 86400000
    b.clock.known = lambda: True
    D.maintain(b.live)
    check("switched-off days count toward Call it", (act(b, "call") == 200) == ok)
    if not ok:
        # A backward clock jump afterwards still can't add or remove idle time.
        b.clock.t -= 10 * 86400000
        D.maintain(b.live)
        check("backward jump after the gap keeps idle", 86400 <= D.maint_call("age", b.live, game(b)) < 86400 + 120)

# A move received with the clock unknown (no phone since a boot) must not erase the
# saved stamp (review 0.3.1-5 #3), but its wall time is unknown, so time switched off
# after it is never credited from that stamp (review 0.3.1-6 #1): the ship falls back
# to uptime plus the hourly checkpoint, which only under-counts. A move heard with
# the clock known keeps crediting switched-off days.
for unknown in (False, True):
    w, a, b = fresh(70)
    start(w, a, b)
    act(b, "fire", cell=0)
    if unknown:
        b.clock.known = lambda: False
        lvlivex.setup(b.live, b, b.data, b.live.cfg)
        D.maintain(b.live)
    settled(w, a, b)
    check("answer with the clock %s keeps a stamp" % ("unknown" if unknown else "known"),
          game(b)["n"] == 1 and game(b)["t"] is not None and bool(game(b).get("tu")) == unknown)
    if unknown:
        check("a stamp from before the move never reaches the page",
              I.load(b.data + "/duel.json")["g"][0]["t"] is not None and D.view(b.live)[0]["t"] is None)
    idle(b, 2 * 3600 * 1000)
    D.maintain(b.live)
    b.clock.known = lambda: False
    lvlivex.setup(b.live, b, b.data, b.live.cfg)
    D.maintain(b.live)
    idle(b, 60000)
    D.maintain(b.live)
    b.clock.t += 4 * 86400000
    b.clock.known = lambda: True
    D.maintain(b.live)
    age = D.maint_call("age", b.live, game(b))
    if unknown:
        check("no switched-off credit after a move heard with the clock unknown",
              3600 <= age < 3 * 3600 and act(b, "call") == 409)
        check("an exact stamp from same-boot idle clears the unknown mark",
              not game(b).get("tu") and abs(D.now(b.live) - game(b)["t"] - age) <= 2)
    else:
        check("switched-off days count after a move heard with the clock known",
              age >= 3 * 86400 and act(b, "call") == 200)

# ...and play before the move, with no phone, isn't counted as idle after the next boot.
w, a, b = fresh(71)
start(w, a, b)
act(b, "fire", cell=0)
b.clock.known = lambda: False
lvlivex.setup(b.live, b, b.data, b.live.cfg)
D.maintain(b.live)
for hour in range(48):
    idle(b, 3600000)
    D.maintain(b.live)
settled(w, a, b)
check("answer after two days with no phone", game(b)["n"] == 1)
idle(b, 3600000)
D.maintain(b.live)
lvlivex.setup(b.live, b, b.data, b.live.cfg)
D.maintain(b.live)
b.clock.t += 86400000
b.clock.known = lambda: True
D.maintain(b.live)
age = D.maint_call("age", b.live, game(b))
check("uptime before the move isn't idle", age < 2 * 3600 and act(b, "call") == 409)

# Review 0.3.1-6 #1 repro: time switched off *before* the boot that heard the move
# is not idle time after it. Ship 1 fires, is off for D days, boots with no phone,
# hears the ANSWER, runs an hour into the crewmate's turn, reboots, then a phone connects.
for off_days in (0, 2.9, 3.0, 10):
    w, a, b = fresh(72)
    start(w, a, b)
    act(b, "fire", cell=0)
    b.clock.t += int(off_days * 86400000)
    b.clock.known = lambda: False
    lvlivex.setup(b.live, b, b.data, b.live.cfg)
    D.maintain(b.live)
    idle(b, 60000)
    D.maintain(b.live)
    settled(w, a, b)
    check("answer heard with the clock unknown", game(b)["n"] == 1)
    idle(b, 3600000)
    D.maintain(b.live)
    lvlivex.setup(b.live, b, b.data, b.live.cfg)
    D.maintain(b.live)
    idle(b, 60000)
    D.maintain(b.live)
    b.clock.known = lambda: True
    D.maintain(b.live)
    age = D.maint_call("age", b.live, game(b))
    check("off %s days before the boot isn't idle after the move" % off_days,
          age < 2 * 3600 and act(b, "call") == 409)
    view = D.view(b.live)[0]
    check("the page's arrival time is no earlier than the hour before",
          view["t"] is not None and D.now(b.live) - view["t"] < 2 * 3600)

# Same rule for an invitation heard with the clock unknown (review 0.3.1-6 #4): no
# stamp, so no switched-off credit; the 3-day put-away runs on uptime alone.
w, a, b = fresh(73)
check("new", act(a, "new") == 200)
check("invite", act(a, "invite", layout=LAY) == 200)
b.clock.known = lambda: False
lvlivex.setup(b.live, b, b.data, b.live.cfg)
D.maintain(b.live)
settled(w, a, b)
check("invitation heard with the clock unknown", game(b)["s"] == "invited" and game(b)["t"] is None)
lvlivex.setup(b.live, b, b.data, b.live.cfg)
D.maintain(b.live)
b.clock.t += 5 * 86400000
b.clock.known = lambda: True
D.maintain(b.live)
check("switched-off days don't put away an invitation heard with the clock unknown",
      game(b)["s"] == "invited" and D.maint_call("age", b.live, game(b)) < 3600)

# Before anyone joined (review 0.3.1-6 #3), withdraw or decline: no record.
w, a, b = fresh(90)
check("new", act(a, "new") == 200)
check("invite", act(a, "invite", layout=LAY) == 200)
settled(w, a, b)
check("waiting / invited", game(a)["s"] == "wait" and game(b)["s"] == "invited")
check("withdraw while waiting", act(a, "withdraw") == 200 and a.live.out[-1][1][0] == 8
      and a.live.out[-1][1][7] == 3)
settled(w, a, b)
check("withdrawn invitation records nothing",
      game(a)["s"] == game(b)["s"] == "called" and D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {})
# Both pages can tell a withdrawal from a 3-day put-away (review 0.3.1-7 #3).
check("withdrawal marked on both ships", D.view(a.live)[0]["wd"] == 1 and D.view(b.live)[0]["wd"] == 2)
check("withdrawal mark reaches the page", lvliveapi.state(a, 0)["duel"][0]["wd"] == 1
      and lvliveapi.state(b, 0)["duel"][0]["wd"] == 2)
check("withdrawing again refused", act(a, "withdraw") == 409)
w, a, b = fresh(92)
act(a, "new"); act(a, "invite", layout=LAY); settled(w, a, b)
check("resign on an unanswered invitation refused", act(b, "resign") == 409 and game(b)["s"] == "invited")
check("decline an unanswered invitation", act(b, "decline") == 200)
settled(w, a, b)
check("declined invitation records nothing",
      game(a)["s"] == "declined" and game(b)["s"] == "declined" and D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {})
# An END 2 from an inviter that resigned before anyone joined (a 0.3.1 build) is a
# withdrawal on the invited ship, never a win.
w, a, b = fresh(93)
act(a, "new"); act(a, "invite", layout=LAY); settled(w, a, b)
j = D.box(b.live)
D.take(b.live, 0, 8, D.gid(j["g"][0]) + bytes((2,)) + bytes(8))
check("END 2 heard in invited is called off", game(b)["s"] == "called" and not game(b).get("win") and D.box(b.live)["r"] == {})
# The reveal screen's Resign is gone; the board still refuses it there.
w, a, b = fresh(91)
start(w, a, b)
act(b, "fire", cell=20); settled(w, a, b)
check("resign in a joined game", act(b, "resign") == 200 and game(b)["s"] == "reveal")
check("resign in reveal still refused", act(b, "resign") == 409)
check("withdraw in reveal refused", act(b, "withdraw") == 409 and act(a, "withdraw") == 409)

# Review 0.3.1-7 #1: the page showed "wait", then the crewmate's ACCEPT landed before
# the confirm was tapped. The stale withdraw is refused and records nothing; it never
# turns into a resignation.
w, a, b = fresh(301)
act(a, "new"); act(a, "invite", layout=LAY); settled(w, a, b)
check("stale page showed wait", D.view(a.live)[0]["s"] == "wait")
check("accept lands", act(b, "accept", layout=LAY) == 200)
settled(w, a, b)
check("joined before the tap", game(a)["s"] == game(b)["s"] == "active")
check("stale withdraw refused", act(a, "withdraw") == 409)
settled(w, a, b)
check("stale withdraw records nothing and keeps the game", game(a)["s"] == game(b)["s"] == "active"
      and D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {} and not a.live.out)
r = D.action(a.live, {"action": "withdraw", "to": 1})
check("stale withdraw says why", r[0] == 409 and "already joined" in r[1]["err"])

# Review 0.3.1-7 #2: a withdrawal crossing the invitee's accept-then-resign. Neither
# ship records a result, the invitee never waits on "Checking both fields", and both
# are free for a new invitation. The "fires" variant puts the game away on the invitee.
for variant in ("resigns", "fires"):
    w, a, b = fresh(300)
    act(a, "new"); act(a, "invite", layout=LAY); settled(w, a, b)
    check("cross accept", act(b, "accept", layout=LAY) == 200)
    check("cross withdraw before ACCEPT heard", act(a, "withdraw") == 200 and game(a)["s"] == "called")
    if variant == "resigns":
        check("cross invitee resigns", act(b, "resign") == 200 and game(b)["s"] == "reveal")
    else:
        act(b, "fire", cell=0)
    settled(w, a, b)
    for k in range(4):
        idle(a, 6 * 3600000 + 1000); idle(b, 6 * 3600000 + 1000); D.maintain(a.live); D.maintain(b.live)
        run(w, a, b, lambda: not a.live.out and not b.live.out and a.ble.state == b.ble.state == "idle")
    check("cross no records", D.box(a.live)["r"] == {} and D.box(b.live)["r"] == {})
    check("cross inviter put away", game(a)["s"] == "called")
    if variant == "resigns":
        check("cross invitee stands down", game(b)["s"] == "done" and game(b).get("mutual")
              and not game(b).get("counted"))
        check("cross invitee page", D.view(b.live)[0]["status"] == "Your game ended with both ships standing down. No result.")
    else:
        check("cross invitee put away", game(b)["s"] == "called")
    check("cross new invitation", act(a, "new") == 200 and act(a, "invite", layout=LAY) == 200)
    settled(w, a, b)
    check("cross new invitation reaches the invitee", game(a)["s"] == "wait" and game(b)["s"] == "invited")
# A rematch waits for the last duel's REVEAL to go out (review 0.3.1-7 #2, found by
# fuzz2.py): the winner counted the resignation, and the resigner still needs the
# winner's REVEAL to count it too.
w, a, b = fresh(303)
start(w, a, b)
act(b, "fire", cell=20); settled(w, a, b)
check("resign before the rematch", act(a, "resign") == 200)
for o in [o for o in a.live.out if o[1][0] in (7, 8)]:
    D.take(b.live, 0, o[1][0], o[1][5:16])
a.live.out[:] = []
check("winner counted, its REVEAL still queued", game(b)["s"] == "done" and D.box(b.live)["r"] == {"0": [1, 0]}
      and any(o[1][0] == 7 for o in b.live.out) and game(a)["s"] == "reveal")
check("rematch waits for the REVEAL", act(b, "new") == 409 and game(b)["s"] == "done")
settled(w, a, b)
check("both ships count the resignation", game(a)["s"] == "done" and D.box(a.live)["r"] == {"1": [0, 1]})
check("rematch once the REVEAL went", act(b, "new") == 200 and act(b, "invite", layout=LAY) == 200)
settled(w, a, b)
check("rematch reaches the resigner", game(a)["s"] == "invited")

# The same stand-down when the inviter's 3-day put-away crosses an accept-then-resign.
w, a, b = fresh(302)
act(a, "new"); act(a, "invite", layout=LAY); settled(w, a, b)
act(b, "accept", layout=LAY); act(b, "resign")
j = D.box(b.live)
D.take(b.live, 0, 8, D.gid(j["g"][0]) + bytes((3,)) + bytes(8))
check("put-away crossing a resignation stands down", game(b)["s"] == "done" and game(b).get("mutual")
      and D.box(b.live)["r"] == {})
D.take(b.live, 0, 8, D.gid(j["g"][0]) + bytes((3,)) + bytes(8))
check("repeat END keeps the stand-down", game(b)["s"] == "done" and D.box(b.live)["r"] == {})

print("duel: %d checks passed" % COUNT[0])
clean(TMP)
