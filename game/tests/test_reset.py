# "Reset this ship" on the ship (board/main.py reset_ship, POST /api/reset): refused without
# a signed-in crew session, refused without the right confirm (no number, a wrong one, a
# GET), and on success it deletes only the players' progress and the crash count in /data
# (main.RESET) and restarts, leaving ship.json and crew.json (and their .bak) byte-for-byte
# as they were, and the installed software and ota/ (update state, rollback copy)
# untouched. The game's other requests and /api/ota* still go where they went. Runs on
# CPython and MicroPython:
#   python3 tests/test_reset.py && micropython tests/test_reset.py        (from game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE + "/board")
import lvweb  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


ROOT = HERE + "/build/reset-test"
DATA = ROOT + "/data"
SHIP = b'{"ship_id": 4, "hotspot_password": "placeholder-pass", "ota_src": "placeholder"}'
CREW = b'{"schema": 1, "salt": "00", "codes": []}'
GONE = {"log.bin": bytes(range(256)) * 2, "days.bin": b"\x01\x02\x03", "clock.json": b'{"t": 1}',
        "local.bin": b"\x05\x06", "funnel.bin": b"ip\x7f\x00\x00\x01\x03\x10" * 2,
        "fault.json": b'{"n": 1, "why": "ValueError: x"}'}        # 0.2.7: the crash count too
KEEP = {"data/ship.json": SHIP, "data/crew.json": CREW, "data/safe": b"",
        "data/ship.json.bak": SHIP, "data/crew.json.bak": CREW,      # lvsafe's backups stay
        "main.py": b"# main\n", "www/app.html.gz": b"page", "ota/state.json": b'{"phase": "ok"}',
        "ota/old/main.py": b"# old main\n"}


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


def write(rel, b):
    p = ROOT + "/" + rel
    mkdirs(p.rsplit("/", 1)[0])
    with open(p, "wb") as f:
        f.write(b)


def read(rel):
    try:
        with open(ROOT + "/" + rel, "rb") as f:
            return f.read()
    except OSError:
        return None


def fixture():
    for k, v in KEEP.items():
        write(k, v)
    for k, v in GONE.items():
        write("data/" + k, v)


def kept(name):
    for k, v in KEEP.items():
        check("%s: %s kept as it was" % (name, k), read(k) == v)


def progress_there(name):
    for k, v in GONE.items():
        check("%s: data/%s still there" % (name, k), read("data/" + k) == v)


# main.py's hooks as they are (main.py itself starts a board, so only that part)
src = open(HERE + "/board/main.py").read()
src = src[src.index("def ota_hooks"):src.index("\nasync def ota_ok")]
rebooted = []
g = {"lvship": None, "asyncio": asyncio}
exec(src, g)
g["reboot"] = lambda: rebooted.append(1)
check("RESET is the progress files only", sorted(g["RESET"]) == sorted(GONE)
      and "ship.json" not in g["RESET"] and "crew.json" not in g["RESET"], g["RESET"])


class FakeLvweb:
    MAX_BODY = 512
    send_json = staticmethod(lvweb.send_json)
    dns_answer = staticmethod(lambda q, ip: None)


class Ship:
    cfg = {"ship_id": 4}
    data = DATA


class Phone:
    def who(self, req):
        return 3 if req.header("x-crew-token") == "tok" else None


class Server:
    ship = Ship()
    routed = []

    def get_phone(self):
        return Phone()

    async def route(self, req, w):
        Server.routed.append(req.path)


class Req:
    def __init__(self, method, path, body=b"", tok=None):
        self.method, self.path, self.q, self.body = method, path, {}, body
        self.hdr = {"x-crew-token": tok} if tok else {}

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


def http(req, wait=0):
    w = Wr()

    async def go():
        await srv.route(req, w)
        if wait:
            await asyncio.sleep(wait)
    asyncio.run(go())
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)


fixture()
cases = (("no session", Req("POST", "/api/reset", b'{"confirm": 4}'), 401),
         ("a session nobody has", Req("POST", "/api/reset", b'{"confirm": 4}', tok="old"), 401),
         ("no confirm", Req("POST", "/api/reset", b"{}", tok="tok"), 403),
         ("no body", Req("POST", "/api/reset", b"", tok="tok"), 403),
         ("wrong ship number", Req("POST", "/api/reset", b'{"confirm": 5}', tok="tok"), 403),
         ("confirm not a number", Req("POST", "/api/reset", b'{"confirm": "four"}', tok="tok"), 403),
         ("not JSON", Req("POST", "/api/reset", b"confirm=4", tok="tok"), 403),
         ("GET", Req("GET", "/api/reset", tok="tok"), 404))
for name, req, want in cases:
    c, j = http(req, wait=1.3)
    check("refused, %s: %d" % (name, want), c == want, (c, j))
    check("refused, %s: no restart" % name, not rebooted)
    progress_there("refused, " + name)
    kept("refused, " + name)
check("refused: nothing reached the game", Server.routed == [])

c, j = http(Req("POST", "/api/reset", b'{"confirm": "4"}', tok="tok"))
check("reset: 200 before anything goes", c == 200 and j.get("ok") and j.get("restart_ms") == 1500, j)
check("reset: answered first, files still there until the restart", read("data/log.bin") == GONE["log.bin"])
c, j = http(Req("POST", "/api/reset", b'{"confirm": 4}', tok="tok"), wait=1.3)
check("reset: restarts", len(rebooted) >= 1, rebooted)
for k in GONE:
    check("reset: data/%s deleted" % k, read("data/" + k) is None)
kept("reset")
check("reset: ship.json untouched", read("data/ship.json") == SHIP)

# Again with the progress already gone (a second tap): still fine, still restarts.
n = len(rebooted)
c, j = http(Req("POST", "/api/reset", b'{"confirm": 4}', tok="tok"), wait=1.3)
check("reset twice: fine", c == 200 and len(rebooted) == n + 1)
kept("reset twice")

# The rest of the API is untouched by the hook.
for r in (Req("GET", "/api/state", tok="tok"), Req("POST", "/api/resets", b"{}", tok="tok")):
    asyncio.run(srv.route(r, Wr()))
check("other paths go to the game", Server.routed == ["/api/state", "/api/resets"], Server.routed)
print("reset: %d checks ok" % ok[0])
