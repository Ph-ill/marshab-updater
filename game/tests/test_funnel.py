# The home-screen funnel on the ship (board/lvfunnel.py, and main.py's GET /api/hello):
# what the ship remembers about each phone (the page's web/funnel.js asks before the game
# loads), by address with 24 h freshness or by MAC where the firmware lists its leases;
# only an icon launch marks a phone installed; the store's size, eviction, atomic save; and
# main.py's hook (loaded per request, dropped after, the clock learned). Runs on CPython
# and MicroPython:   python3 tests/test_funnel.py && micropython tests/test_funnel.py  (game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE + "/board")
sys.path.append(HERE)
import lvfunnel as F  # noqa: E402
import lvweb  # noqa: E402
from lv import clock as C  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


def rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def mkdirs(p):
    cur = ""
    for part in p.split("/"):
        if not part:
            cur = "/"
            continue
        cur = cur + part if cur.endswith("/") else cur + "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


DATA = HERE + "/build/funnel-test"
mkdirs(DATA)
DB = DATA + "/funnel.bin"
H = 3600000
T0 = 1792843200000                      # a phone's clock (ms since 1970)


class FakeAP:
    def __init__(self, leases):
        self.l = leases

    def status(self, k):
        if k != "leases":
            raise ValueError("unknown status param")
        return self.l


class StockAP:                          # MicroPython 1.29 on the Pico W: no "leases"
    def status(self, k):
        raise ValueError("unknown status param")


def hello(ctx, peer, now=T0, ap=None, m=None, path=DB):
    q = {"ctx": ctx}
    if m:
        q["m"] = m
    fn = F.Funnel(path, F.stamp(now), ap)
    r = fn.hello(q, peer)
    fn.save()
    return r


def size():
    try:
        return os.stat(DB)[6]
    except OSError:
        return None


A, B = "192.168.4.16", "192.168.4.17"

# 1. By address (stock firmware): a phone's path through the funnel.
rm(DB)
r = hello("sheet", A, ap=StockAP())
check("pop-up seen", r == {"installed": 0, "tab": 0, "sheet": 1, "key": "ip"}, r)
check("the store is 32 phones x 8 B", size() == 256, size())
r = hello("ios", A)
check("then the browser tab", r == {"installed": 0, "tab": 1, "sheet": 1, "key": "ip"}, r)
r = hello("ios", B)
check("another phone is its own record", r == {"installed": 0, "tab": 1, "sheet": 0, "key": "ip"}, r)
r = hello("other", A)
check("a computer's ask changes nothing", r["installed"] == 0 and r["tab"] == 1, r)
r = hello("ios", A, m="icon")
check("a marked address from a browser is a launch (Android's icon)", r["installed"] == 1, r)
rm(DB)
for ctx in ("ios", "iosx", "and", "sam", "sheet", "awv", "other", "", "bogus"):
    r = hello(ctx, A)
    check("%s: never installed without the icon" % (ctx or "no ctx"), r["installed"] == 0, r)
r = hello("bogus", A, m="icon")
check("an unknown ctx with the marker: not a launch", r["installed"] == 0, r)
r = hello("standalone", A)
check("standalone (the iOS icon): installed", r["installed"] == 1, r)
r = hello("ios", A, now=T0 + 2 * H)
check("the next browser visit: installed", r == {"installed": 1, "tab": 1, "sheet": 1, "key": "ip"}, r)
r = hello("sheet", A, now=T0 + 3 * H)
check("the pop-up again: installed (LEAVE_KNOWN)", r["installed"] == 1 and r["sheet"] == 1, r)
r = hello("ios", B)
check("not the other phone", r["installed"] == 0, r)

# 2. Freshness: an address is a 24 h lease, so an address record goes stale within a day.
rm(DB)
hello("standalone", A)
r = hello("other", A, now=T0 + 20 * H)
check("20 h on: still this phone", r["installed"] == 1, r)
r = hello("other", A, now=T0 + 30 * H)
check("30 h on: maybe another phone now", r["installed"] == 0, r)
r = hello("ios", A, now=T0 + 30 * H)
check("30 h on, a tab: a new record", r == {"installed": 0, "tab": 1, "sheet": 0, "key": "ip"}, r)
rm(DB)
hello("standalone", A)
for i in range(1, 20):                  # a phone that keeps coming back keeps its record
    r = hello("ios", A, now=T0 + i * 20 * H)
check("visits every 20 h for 16 days: still installed", r["installed"] == 1, r)
r = hello("ios", A, now=None)
check("no clock yet: trusted as is", r["installed"] == 1, r)
check("stamps wrap (a byte of 4 h units, ~43 days)", F.stamp(T0) == F.stamp(T0 + 256 * 4 * H))

# 3. MAC mode: firmware that lists its leases keys phones by MAC (private per network),
# across address changes, and those records don't go stale.
MAC_A = b"\x02\xaa\x00\x00\x00\x01"
MAC_B = b"\x02\xbb\x00\x00\x00\x02"
ap = FakeAP([(MAC_A, A), (MAC_B, B)])
rm(DB)
r = hello("sheet", A, ap=ap)
check("mac: keyed by MAC", r == {"installed": 0, "tab": 0, "sheet": 1, "key": "mac"}, r)
hello("standalone", A, ap=ap)
ap2 = FakeAP([(MAC_A, B), (MAC_B, A)])  # the next day, addresses swapped
r = hello("ios", B, ap=ap2, now=T0 + 40 * H)
check("mac: the same phone on a new address, days later", r["installed"] == 1, r)
r = hello("ios", A, ap=ap2, now=T0 + 40 * H)
check("mac: the other phone on the old address isn't", r["installed"] == 0, r)
r = hello("ios", "192.168.4.30", ap=ap2)
check("mac: no lease for the address: by address", r["key"] == "ip" and r["installed"] == 0, r)

# 4. A full store: 32 phones; a new one takes the stalest record that isn't installed.
rm(DB)
for i in range(32):
    hello("standalone" if i < 4 else "ios", "10.0.0.%d" % i, now=T0 + i * H // 8)
for i in range(4):
    check("full: installed phone %d kept" % i, hello("other", "10.0.0.%d" % i)["installed"] == 1)
r = hello("ios", "10.0.1.1", now=T0 + 8 * H)
check("full: a newcomer gets a record", r["tab"] == 1, r)
check("full: still 256 B", size() == 256)
for i in range(4):
    check("full: installed %d still there" % i, hello("other", "10.0.0.%d" % i, now=T0 + 8 * H)["installed"] == 1)
check("full: the stalest tab-only record went", hello("other", "10.0.0.4", now=T0 + 8 * H)["tab"] == 0)
check("full: a fresher one stayed", hello("other", "10.0.0.31", now=T0 + 8 * H)["tab"] == 1)

# 5. Writes: only when something changes; a whole file via .new and a rename; a bad file.
rm(DB)
hello("ios", A)
st = open(DB, "rb").read()
fn = F.Funnel(DB, F.stamp(T0), None)
fn.hello({"ctx": "ios"}, A)
check("the same ask again: nothing to write", not fn.dirty)
check("no .new left behind", ".new" not in " ".join(os.listdir(DATA)), os.listdir(DATA))
with open(DB, "wb") as f:
    f.write(b"\x01\x02")                # cut short: read what's there
r = hello("ios", A)
check("a short file: still answers", r["tab"] == 1 and size() == 256, r)
fn = F.Funnel(DATA + "/no/such/dir/funnel.bin", F.stamp(T0), None)
check("no /data: a fresh store", fn.hello({"ctx": "ios"}, A)["tab"] == 1)
check("peer '?': a key anyway", F.ip_key("?") == b"ip\0\0\0\0" and F.ip_key("1.2.3.999") == b"ip\0\0\0\0")

# 6. main.py's hook: GET /api/hello, loaded per request and dropped, clock headers learned.
src = open(HERE + "/board/main.py").read()
src = src[src.index("def ota_hooks"):src.index("\nasync def ota_ok")]
dropped = []


class LvShip:
    @staticmethod
    def drop(n):
        dropped.append(n)
        sys.modules.pop(n, None)


g = {"lvship": LvShip, "asyncio": asyncio}
exec(src, g)
check("RESET deletes the funnel's store", "funnel.bin" in g["RESET"], g["RESET"])


class FakeLvweb:
    MAX_BODY = 512
    send_json = staticmethod(lvweb.send_json)
    dns_answer = staticmethod(lambda q, ip: None)


class Ship:
    data = DATA
    days = 0

    def __init__(self):
        self.clock = C.Clock()

    def day_check(self):
        Ship.days += 1


class Server:
    ship = Ship()
    routed = []

    async def route(self, req, w):
        Server.routed.append(req.path)


class Req:
    def __init__(self, method, path, q, peer, hdr=None):
        self.method, self.path, self.q, self.peer, self.body = method, path, q, peer, b""
        self.hdr = hdr or {}

    def header(self, k):
        return self.hdr.get(k)


class Wr:
    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


srv = Server()
g["ota_hooks"](FakeLvweb, srv)


def http(req):
    w = Wr()
    asyncio.run(srv.route(req, w))
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body) if body else None


rm(DB)
c, j = http(Req("GET", "/api/hello", {"ctx": "ios"}, A, {"x-phone-time": str(T0), "x-phone-tz": "-300"}))
check("hook: 200 and the record", c == 200 and j == {"installed": 0, "tab": 1, "sheet": 0, "key": "ip"}, (c, j))
check("hook: the phone's clock learned", srv.ship.clock.epoch_ms() is not None and Ship.days == 1)
check("hook: lvfunnel dropped after", dropped == ["lvfunnel"] and "lvfunnel" not in sys.modules, dropped)
c, j = http(Req("GET", "/api/hello", {"ctx": "standalone"}, A))
c, j = http(Req("GET", "/api/hello", {"ctx": "ios"}, A))
check("hook: an icon launch, then the tab knows", j["installed"] == 1, j)
srv.ap = FakeAP([(MAC_A, A)])
c, j = http(Req("GET", "/api/hello", {"ctx": "ios"}, A))
check("hook: web.ap (main.py) gives MAC mode", j["key"] == "mac" and j["installed"] == 0, j)
srv.ap = None
for r in (Req("POST", "/api/hello", {}, A), Req("GET", "/api/hellos", {}, A), Req("GET", "/api/me", {}, A)):
    asyncio.run(srv.route(r, Wr()))
check("hook: other paths and methods go to the game", Server.routed == ["/api/hello", "/api/hellos", "/api/me"],
      Server.routed)
print("funnel: %d checks ok" % ok[0])
