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
# Simulate an hour of uptime, independently of the phone's epoch.
import lvship
old_tick = lvship.ticks_ms
tick = old_tick()
lvship.ticks_ms = lambda: (tick + 3600001) & 0x3fffffff
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
lvship.ticks_ms = lambda: (tick + 3600001) & 0x3fffffff
check("old ship warning", D.view(a.live)[0]["update"])
lvship.ticks_ms = old_tick
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
b.clock.t += 3 * 86400000 + 1
for k in range(23):
    I.send(b.live, 2, 2, bytes((k,)))
check("call works with full outbox", act(b, "call") == 200)
check("called shot purged", not any(o[1][0] == 5 for o in b.live.out))
D.maintain(b.live)
check("call keeps bounded END", sum(o[1][0] == 8 for o in b.live.out) == 1)
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
    b.clock.t += 3 * 86400000 + 1
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
        body = bytes((5, 0, 77, 0, 1)) + D.gid(game(s)) + bytes((11, 35)) + bytes(7)
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
a.clock.t += 4 * 86400000
D.maintain(a.live)
check("stale drafts removed silently", not D.box(a.live)["g"] and not a.live.out)
check("fourth after expiry", D.action(a.live, {"action": "new", "to": 5})[0] == 200)

print("duel: %d checks passed" % COUNT[0])
clean(TMP)
