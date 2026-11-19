# "Reset this ship" on the ship (board/lvcode.py reset, POST /api/reset through main.py's
# ota_route, which imports lvcode per request and drops it): refused without
# a signed-in crew session, refused without the right confirm (no number, a wrong one, a
# GET), and on success it deletes only the players' progress and the crash count in /data
# (lvcode.RESET, including duel.json) and restarts, leaving ship.json and crew.json (and
# their .bak) byte-for-byte as they were unless the request starts the voyage from today,
# and the installed software and ota/ (update state, rollback copy) untouched. from_today
# writes launch_date so a phone telling the time yields day 1 (yesterday if before
# day_start). The game's other requests and /api/ota* still go where they went. Runs on
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
sys.path.insert(1, HERE)                  # (lv/: lvlivein, for the hails that came in)
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
        "fault.json": b'{"n": 1, "why": "ValueError: x"}',        # 0.2.7: the crash count too
        "hail.json": b'{"d": 1, "o": [], "i": [["7f0003", 0, 0, 1, 0, 0, 0]]}',   # 0.3.0 R2 m10
        "duel.json": b'{"day": 12, "left": 3}'}                  # 0.3.11: game progress, goes too
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


# Hail's box (0.3.0 review R2 m10): what came in and no phone read yet goes, and this
# ship's own waiting items (FIXREVIEW2 minor 10: Reset says everyone's hails go); the
# epoch, sequence and each sender's highest taken (replay protection) stay
BOX = {"e": 7, "s": 3, "o": [[1, "aa", 20000]], "i": [[2, "bb", None]], "h": {"2": [5, 9]}, "l": [0, 0]}


def fixture():
    write("data/livebox.json", json.dumps(BOX).encode())
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
src = src[src.index("def http_admission"):src.index("\nasync def ota_ok")]
rebooted = []


class LS:
    # main.py's lvship as ota_route uses it: lvcode (Reset) is imported per request, dropped
    dropped = []

    @staticmethod
    def drop(n):
        LS.dropped.append(n)
        sys.modules.pop(n, None)


g = {"lvship": LS, "asyncio": asyncio}
exec(src, g)
g["reboot"] = lambda: rebooted.append(1)
import lvcode  # noqa: E402
RESET = lvcode.RESET
check("RESET is the progress files only", sorted(RESET) == sorted(GONE)
      and "ship.json" not in RESET and "crew.json" not in RESET, RESET)
check("RESET lives in lvcode now (0.3.0: out of main.py's resident code)", "RESET" not in g
      and "reset_ship" not in g)


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
    def __init__(self, method, path, body=b"", tok=None, time=None, tz=None):
        self.method, self.path, self.q, self.body = method, path, {}, body
        self.hdr = {}
        if tok:
            self.hdr["x-crew-token"] = tok
        if time is not None:
            self.hdr["x-phone-time"] = str(time)
        if tz is not None:
            self.hdr["x-phone-tz"] = str(tz)

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
check("reset: lvcode dropped after the request", "lvcode" in LS.dropped and "lvcode" not in sys.modules, LS.dropped)
for k in GONE:
    check("reset: data/%s deleted" % k, read("data/" + k) is None)
kept("reset")
check("reset: ship.json untouched", read("data/ship.json") == SHIP)
bx = json.loads(read("data/livebox.json"))
check("R2 m10: reset: hails that came in are gone", bx.get("i") == [], bx)
check("R2 m10: reset: replay protection kept",
      all([bx.get(k) == BOX[k] for k in ("e", "s", "h")]), bx)
check("FR2 minor 10: reset: own waiting hails gone too", bx.get("o") == [], bx)

# Again with the progress already gone (a second tap): still fine, still restarts.
n = len(rebooted)
c, j = http(Req("POST", "/api/reset", b'{"confirm": 4}', tok="tok"), wait=1.3)
check("reset twice: fine", c == 200 and len(rebooted) == n + 1)
kept("reset twice")

# 0.3.0 review R3 m2: only a signed-in phone's update request holds Hail off (ship.ota_t)
LS.ticks_ms = staticmethod(lambda: 777)
for name, tok, want in (("signed out", None, 0), ("a session nobody has", "old", 0), ("signed in", "tok", 777)):
    srv.ship.ota_t = 0
    try:
        asyncio.run(srv.route(Req("POST", "/api/ota/cancel", b"{}", tok=tok), Wr()))
    except Exception:
        pass                      # (lvota against the stand-in server: not what's checked)
    check("R3 m2: POST /api/ota, %s: ota_t %s" % (name, want), srv.ship.ota_t == want, srv.ship.ota_t)
for m in ("lvota", "lvotap", "lvotaq"):
    sys.modules.pop(m, None)
Server.routed = []

# The rest of the API is untouched by the hook.
for r in (Req("GET", "/api/state", tok="tok"), Req("POST", "/api/resets", b"{}", tok="tok")):
    asyncio.run(srv.route(r, Wr()))
check("other paths go to the game", Server.routed == ["/api/state", "/api/resets"], Server.routed)

# --- 0.3.11: start the voyage again from today ---------------------------------
import lvcal
from lv.clock import Clock
import lvledcfg

# Invert a few dates so launch_today's yesterday arithmetic is on a known mapping.
for y, m, d in ((2000, 1, 1), (2024, 2, 29), (2026, 11, 19), (2026, 3, 1), (2100, 12, 31)):
    z = lvcal.days_from_civil(y, m, d)
    check("civil_from_days %04d-%02d-%02d" % (y, m, d), lvcal.civil_from_days(z) == (y, m, d))
    check("date_str %04d-%02d-%02d" % (y, m, d), lvcal.date_str(z) == "%04d-%02d-%02d" % (y, m, d))


def epoch(y, m, d, minute, tz):
    return (lvcal.days_from_civil(y, m, d) * 1440 + minute - tz) * 60000


tz0 = -360
check("launch_today New Year before 06:00 is 31 Dec",
      lvcal.launch_today("2026-01-01", epoch(2026, 1, 1, 5 * 60 + 59, tz0), tz0) == "2025-12-31")
check("launch_today New Year at 06:00 is 1 Jan",
      lvcal.launch_today("2026-01-01", epoch(2026, 1, 1, 6 * 60, tz0), tz0) == "2026-01-01")
check("launch_today 31 Dec 23:59 stays 31 Dec",
      lvcal.launch_today("2025-12-31", epoch(2025, 12, 31, 23 * 60 + 59, tz0), tz0) == "2025-12-31")
check("launch_today leap day after 06:00",
      lvcal.launch_today("2028-02-29", epoch(2028, 2, 29, 10 * 60, tz0), tz0) == "2028-02-29")
check("launch_today rejects a boolean epoch",
      lvcal.launch_today("2026-11-19", True, tz0) is None)


def live_ship(launch="2026-09-01", day=20, start=None):
    # Placeholder secrets only: the tests assert they are not printed, never logged as real ones.
    c = {"ship_id": 4, "hotspot_password": "placeholder-pass", "ota_src": "placeholder",
         "fleet_key": "placeholder-fleet-key", "launch_date": launch, "day": day, "led_notify": False}
    if start is not None:
        c["day_start"] = start
    b = json.dumps(c).encode()
    write("data/ship.json", b)
    write("data/ship.json.bak", b)
    Ship.cfg = dict(c)
    Ship.cfg["ship_id"] = 4
    return c


def fresh(date="2026-11-19", minute=14 * 60 + 30, tz=-360, confirm=4, today=True, tok="tok",
          extra=None, start=None):
    y, m, d = int(date[0:4]), int(date[5:7]), int(date[8:10])
    body = {"confirm": confirm, "date": date}
    if today is True:
        body["from_today"] = True
    elif today is not None:
        body["from_today"] = today
    if extra:
        body.update(extra)
    return Req("POST", "/api/reset", json.dumps(body).encode(), tok=tok,
               time=epoch(y, m, d, minute, tz), tz=tz)


def kept_soft(name):
    for k, v in KEEP.items():
        if k in ("data/ship.json", "data/ship.json.bak"):
            continue
        check("%s: %s kept as it was" % (name, k), read(k) == v)


# Validation: nothing moves.
rebooted[:] = []
before = live_ship()
fixture()
live_ship()
val_cases = [
    ("from_today without date",
     Req("POST", "/api/reset", b'{"confirm": 4, "from_today": true}', tok="tok",
         time=epoch(2026, 11, 19, 14 * 60 + 30, -360), tz=-360)),
    ("from_today without phone time",
     Req("POST", "/api/reset",
         b'{"confirm": 4, "from_today": true, "date": "2026-11-19"}', tok="tok")),
    ("date does not match the clock",
     Req("POST", "/api/reset",
         b'{"confirm": 4, "from_today": true, "date": "2026-11-19"}', tok="tok",
         time=epoch(2026, 11, 18, 14 * 60 + 30, -360), tz=-360)),
    ("not a date", fresh(extra={"date": "19/11/2026"})),
    ("impossible day", fresh(extra={"date": "2026-02-29"})),
    ("month 13", fresh(extra={"date": "2026-13-01"})),
    ("year too early",
     Req("POST", "/api/reset",
         b'{"confirm": 4, "from_today": true, "date": "1999-12-31"}', tok="tok",
         time=epoch(1999, 12, 31, 14 * 60 + 30, -360), tz=-360)),
    ("from_today as a string", fresh(today="true")),
    ("from_today as 1", fresh(today=1)),
]
nboot = len(rebooted)
for name, req in val_cases:
    c, j = http(req, wait=0)
    check("refused, %s: 400" % name, c == 400, (c, j))
    check("refused, %s: no restart" % name, len(rebooted) == nboot)
    check("refused, %s: ship.json untouched" % name,
          read("data/ship.json") == json.dumps(before).encode())
    check("refused, %s: bak untouched" % name,
          read("data/ship.json.bak") == json.dumps(before).encode())
    check("refused, %s: no .new" % name, read("data/ship.json.new") is None)
    progress_there("refused, " + name)
    kept_soft("refused, " + name)

# Auth still required when from_today is set: 401/403, not 400, and nothing writes.
for name, req, want in (
        ("from_today, no session", fresh(tok=None), 401),
        ("from_today, stale token", fresh(tok="old"), 401),
        ("from_today, wrong ship number", fresh(confirm=5), 403),
        ):
    c, j = http(req, wait=0)
    check("refused, %s: %d" % (name, want), c == want, (c, j))
    check("refused, %s: no restart" % name, len(rebooted) == nboot)
    check("refused, %s: ship.json untouched" % name,
          read("data/ship.json") == json.dumps(before).encode())
    progress_there("refused, " + name)

# Failed atomic write: rename fails, original files stay, 500, no .new, no restart.
def boom_rename(where):
    if where == "rename":
        raise OSError("no")


lvledcfg.fail = boom_rename
c, j = http(fresh(), wait=0)
lvledcfg.fail = None
check("write rename fails: 500", c == 500, (c, j))
check("write rename fails: no restart", len(rebooted) == nboot)
check("write rename fails: ship.json as it was",
      read("data/ship.json") == json.dumps(before).encode())
check("write rename fails: bak as it was",
      read("data/ship.json.bak") == json.dumps(before).encode())
check("write rename fails: no .new", read("data/ship.json.new") is None)
progress_there("write rename fails")

# Missing or unusable ship.json: 500, nothing else happens (including no .bak rewrite).
# (lvcode is imported fresh per request, so a fail hook on the test's copy wouldn't run.)
os.remove(DATA + "/ship.json")
c, j = http(fresh(), wait=0)
check("ship.json missing: 500", c == 500, (c, j))
check("ship.json missing: still missing", read("data/ship.json") is None)
check("ship.json missing: bak as it was",
      read("data/ship.json.bak") == json.dumps(before).encode())
check("ship.json missing: no restart", len(rebooted) == nboot)
progress_there("ship.json missing")
write("data/ship.json", json.dumps(before).encode())

# A ship.json that isn't a whole identity (password too short) is left exactly as it is.
# (A missing password is still a whole identity: lvledcfg.valid allows pw is None.)
bad = b'{"ship_id": 4, "hotspot_password": "short"}'
write("data/ship.json", bad)
c, j = http(fresh(), wait=0)
check("ship.json not a whole identity: 500", c == 500, (c, j))
check("ship.json not a whole identity: file left as it was",
      read("data/ship.json") == bad)
check("ship.json not a whole identity: bak as it was",
      read("data/ship.json.bak") == json.dumps(before).encode())
check("ship.json not a whole identity: no restart", len(rebooted) == nboot)
progress_there("ship.json not a whole identity")
write("data/ship.json", json.dumps(before).encode())

# Wipe only (no from_today), even with a date and phone time in the request: launch stays.
# (A client that omits from_today, or unchecks the box, keeps the original start date.)
fixture()
before = live_ship()
c, j = http(Req("POST", "/api/reset",
                b'{"confirm": 4, "date": "2026-11-19"}', tok="tok",
                time=epoch(2026, 11, 19, 14 * 60 + 30, -360), tz=-360), wait=1.3)
check("wipe only: 200", c == 200 and j.get("ok"), j)
check("wipe only: restarted", len(rebooted) == nboot + 1)
check("wipe only: ship.json bytes unchanged",
      read("data/ship.json") == json.dumps(before).encode())
check("wipe only: bak unchanged",
      read("data/ship.json.bak") == json.dumps(before).encode())
for k in GONE:
    check("wipe only: data/%s deleted" % k, read("data/" + k) is None)
kept_soft("wipe only")
nboot = len(rebooted)

# Fresh start after 06:00: launch_date is today, day is 1, bak matches, progress gone,
# duel gone, then Calendar + the same phone time yields day 1. Nothing secret is printed.
fixture()
before = live_ship()
# lvcode never prints ship.json (the file holds the hotspot password and fleet key).
req = fresh(date="2026-11-19", minute=14 * 60 + 30, tz=-360)
c, j = http(req, wait=1.3)
check("fresh start: 200", c == 200 and j.get("ok"), j)
check("fresh start: restarted", len(rebooted) == nboot + 1)
got = json.loads(read("data/ship.json"))
check("fresh start: launch_date is today", got.get("launch_date") == "2026-11-19", got.get("launch_date"))
check("fresh start: day is 1", got.get("day") == 1, got.get("day"))
check("fresh start: identity kept", got.get("ship_id") == 4 and got.get("hotspot_password") == before["hotspot_password"]
      and got.get("fleet_key") == before["fleet_key"] and got.get("ota_src") == before["ota_src"])
check("fresh start: bak matches ship.json", json.loads(read("data/ship.json.bak")) == got)
check("fresh start: no .new", read("data/ship.json.new") is None)
for k in GONE:
    check("fresh start: data/%s deleted" % k, read("data/" + k) is None)
kept_soft("fresh start")
clock = Clock()
clock.learn(epoch(2026, 11, 19, 14 * 60 + 30, -360), -360)
cal = lvcal.Calendar(got, clock, 42, DATA)
check("fresh start: clock.json is gone, so the saved day can't come back",
      read("data/clock.json") is None)
check("fresh start: a phone telling the time yields day 1", cal.poll() == 1, cal.poll())
nboot = len(rebooted)

# Before 06:00: launch_date is yesterday, and the same instant is already day 1 (not 0).
fixture()
live_ship()
req = fresh(date="2026-11-19", minute=5 * 60 + 59, tz=-360)
c, j = http(req, wait=1.3)
check("before 06:00: 200", c == 200, (c, j))
got = json.loads(read("data/ship.json"))
check("before 06:00: launch_date is yesterday", got.get("launch_date") == "2026-11-18",
      got.get("launch_date"))
clock = Clock()
clock.learn(epoch(2026, 11, 19, 5 * 60 + 59, -360), -360)
cal = lvcal.Calendar(got, clock, 42, DATA)
check("before 06:00: the same instant is day 1, not 0", cal.poll() == 1, cal.poll())
# And using today instead would have been pre-launch (day 0): the reason we pick yesterday.
check("before 06:00: today would have been day 0",
      lvcal.flight_day(clock.local_minutes(), lvcal.parse_date("2026-11-19"), 42) == 0)
nboot = len(rebooted)

# Exactly 06:00: today, and day 1.
fixture()
live_ship()
c, j = http(fresh(date="2026-11-19", minute=6 * 60, tz=-360), wait=1.3)
got = json.loads(read("data/ship.json"))
check("at 06:00: launch_date is today", c == 200 and got.get("launch_date") == "2026-11-19")
clock = Clock()
clock.learn(epoch(2026, 11, 19, 6 * 60, -360), -360)
cal = lvcal.Calendar(got, clock, 42, DATA)
check("at 06:00: day is 1", cal.poll() == 1, cal.poll())
nboot = len(rebooted)

# Custom day_start 08:00: 07:59 uses yesterday; 08:00 uses today.
fixture()
live_ship(start="08:00")
c, j = http(fresh(date="2026-11-19", minute=7 * 60 + 59, tz=-360), wait=1.3)
got = json.loads(read("data/ship.json"))
check("before custom 08:00: yesterday", c == 200 and got.get("launch_date") == "2026-11-18",
      got.get("launch_date"))
nboot = len(rebooted)
fixture()
live_ship(start="08:00")
c, j = http(fresh(date="2026-11-19", minute=8 * 60, tz=-360), wait=1.3)
got = json.loads(read("data/ship.json"))
check("at custom 08:00: today", c == 200 and got.get("launch_date") == "2026-11-19",
      got.get("launch_date"))
nboot = len(rebooted)

# Time zone bounds: +14 and -12, dates consistent with the clock, still day 1.
for tz, label in ((840, "+14"), (-720, "-12")):
    fixture()
    live_ship()
    c, j = http(fresh(date="2026-11-19", minute=14 * 60, tz=tz), wait=1.3)
    got = json.loads(read("data/ship.json"))
    check("tz %s: 200, launch today" % label,
          c == 200 and got.get("launch_date") == "2026-11-19", (c, got.get("launch_date")))
    clock = Clock()
    clock.learn(epoch(2026, 11, 19, 14 * 60, tz), tz)
    cal = lvcal.Calendar(got, clock, 42, DATA)
    check("tz %s: day 1" % label, cal.poll() == 1, cal.poll())
    nboot = len(rebooted)

# epoch out of range (before EPOCH_MIN): 400, nothing written.
fixture()
before = live_ship()
# 2023-06-01 is before EPOCH_MIN (2024-01-01). parse_date would accept it; the clock must not.
c, j = http(Req("POST", "/api/reset",
                b'{"confirm": 4, "from_today": true, "date": "2023-06-01"}', tok="tok",
                time=epoch(2023, 6, 1, 14 * 60, 0), tz=0), wait=0)
check("epoch too early: 400", c == 400, (c, j))
check("epoch too early: ship.json untouched",
      read("data/ship.json") == json.dumps(before).encode())
check("epoch too early: no restart", len(rebooted) == nboot)

print("reset: %d checks ok" % ok[0])
