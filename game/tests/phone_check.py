# The board's phone server (board/lvweb.py + board/lvphone.py) on fake sockets, under
# CPython and the MicroPython unix port. From game/:
#
#   python3 tests/phone_check.py [day]
#   micropython -X heapsize=320k tests/phone_check.py [day]
#
# A ship at flight day `day` (default 8) with the reference season's records from before
# that day, crew codes 1234 (crew 7 not set up), and the phone page's files. Two phones
# sign in and play through tests/phone_flow.py at the same time; then the edges: the
# captive-portal redirect and DNS, lockout, "not set up", a phone that connects and says
# nothing (timed out, never blocks the others), more phones than MAX_CONN, what phones
# opened surviving a restart, and the story the state sends matching the ship's.
import sys
import os
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/fakeble")
sys.path.append("board")
sys.path.append(".")

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio
from binascii import a2b_base64

import lvship
import lvweb
import lvdays
import lvphone
import phone_flow as F
from lv import codes as K
from lv import record as R

DAY = int(sys.argv[1]) if len(sys.argv) > 1 else 8
ROOT = "build/phone-root/"
DATA = "build/phone-data"
FAILS = []


def fail(msg):
    FAILS.append(msg)
    print("FAIL", msg)


def mkdir(p):
    try:
        os.mkdir(p)
    except OSError:
        pass


def copy(src, dst):
    with open(src, "rb") as f:
        b = f.read()
    with open(dst, "wb") as f:
        f.write(b)
    return b


def rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


# The board's file layout (tools/board_build.sh build/board-fw/), built from build/.
mkdir(ROOT)
mkdir(ROOT + "www")
mkdir(DATA)
ASSETS = {}
for n in ("app.html.gz", "text.json.gz", "engage.json.gz"):
    ASSETS[n] = copy("build/" + n, ROOT + "www/" + n)
copy("build/pack.bin", ROOT + "pack.bin")
copy("build/engage.bin", ROOT + "engage.bin")
for n in ("log.bin", "local.bin", "crew.json"):
    rm(DATA + "/" + n)
import json  # noqa: E402
with open(DATA + "/crew.json", "w") as f:
    f.write(json.dumps(K.make_config(["1234"] * 7 + [None], b"bench-salt-16-by")))
with open("build/season_log.bin", "rb") as f:
    RAW = f.read()
with open(DATA + "/log.bin", "wb") as f:
    for i in range(0, len(RAW), R.LEN):
        r = RAW[i:i + R.LEN]
        if R.day(r) < DAY:
            f.write(r)
RAW = None

cfg = lvship.load_config("/nonexistent")
cfg["day"] = DAY
cfg["ship_id"] = 3
quiet = lambda s: None  # noqa: E731
ship = lvship.Ship(cfg, root=ROOT, data=DATA, say=quiet, radio=False,
                   days=lvdays.Days(DATA + "/days.bin"))
srv = lvweb.Server(ship, root=ROOT, say=quiet)
n0 = len(ship.log)


# Phone A plays someone with a private dilemma open today, if anyone has one.
CA = 2
for it in ship.st.pend:
    if it[0] == 4 and it[4] < 7 and it[4] != 5:
        CA = it[4]
        break
CB = 5


async def main():
    # Two phones at once: different crew, different phones.
    a, b = await asyncio.gather(
        F.session(F.fake(srv, "10.0.0.2"), "phoneA", CA, "1234", fail, ASSETS, log=print),
        F.session(F.fake(srv, "10.0.0.3"), "phoneB", CB, "1234", fail, ASSETS, log=print))
    print("phones did: %s" % ", ".join([k for k in ("vote", "answer", "gift") if k in a or k in b]))
    if a.get("first") is not True:
        fail("first sign-in should say first: %s" % a.get("first"))
    # The story the page got is the ship's, day by day.
    st = a["state2"]
    story = a2b_base64(st["story"])
    want = b"".join([ship.days.get(d) or b"" for d in range(1, DAY + 1)])
    if story != want or len(story) % 8:
        fail("story: %d bytes, ship has %d" % (len(story), len(want)))
    if st["day"] != DAY or st["season"] != ship.pack.season or st["here"] != ship.me:
        fail("state day/season/here: %s %s %s" % (st["day"], st["season"], st["here"]))
    # Taps became signed records for today by the crew member who made them.
    mine = [r for r in ship.log.values() if R.day(r) == DAY and R.ship(r) in (CA, CB)]
    kinds = sorted(set([R.kind(r) for r in mine]))
    want_kinds = [R.ACTION, R.GIFT] + ([R.VOTE] if "vote" in a or "vote" in b else []) + \
        ([R.DILEMMA] if "answer" in a or "answer" in b else [])
    if [k for k in want_kinds if k not in kinds]:
        fail("records authored: kinds %s" % kinds)
    with open(DATA + "/log.bin", "rb") as f:
        kept = len(f.read()) // R.LEN
    if kept < len(ship.log) or len(ship.log) <= n0:
        fail("log.bin keeps %d records, log has %d (was %d)" % (kept, len(ship.log), n0))

    req = F.fake(srv, "10.0.0.9")
    H = {"User-Agent": "x"}
    for path in ("/generate_204", "/connecttest.txt", "/nothing/here"):
        s, h, _ = await req("GET", path, None, H)
        if s != 302 or h.get("location") != "http://192.168.4.1/":
            fail("captive %s: %d %s" % (path, s, h.get("location")))
    s, h, b = await req("GET", "/status", None, H)
    if s != 200 or not b.startswith(b"STAT ship=3"):
        fail("status: %d %s" % (s, b[:40]))
    s, _, b = await req("POST", "/api/login", b'{"crew":7,"pin":"1234"}', H)
    if s != 409:
        fail("not set up: %d %s" % (s, b))
    for i in range(4):
        s, _, b = await req("POST", "/api/login", b'{"crew":4,"pin":"9999"}', H)
    s, _, b = await req("POST", "/api/login", b'{"crew":4,"pin":"9999"}', H)
    if s != 429 or F.js(b).get("wait") != 300:
        fail("lockout: %d %s" % (s, b))
    s, _, b = await req("POST", "/api/login", b'not json', H)
    if s != 400:
        fail("bad login body: %d" % s)
    s, _, b = await req("POST", "/api/vote", b'{"card":1,"opt":0}', H)
    if s != 401:
        fail("vote signed out: %d" % s)
    s, _, b = await req("POST", "/api/login", b"x" * 600, H)
    if s != 413:
        fail("oversized body: %d" % s)

    # A phone that connects and says nothing is timed out; meanwhile the others are served.
    lvweb.READ_MS = 300
    stuck = [F.FakeWriter() for _ in range(lvweb.MAX_CONN)]
    tasks = [asyncio.create_task(srv.handle(F.StuckReader(), w)) for w in stuck]
    await asyncio.sleep(0.05)
    s, _, b = await req("GET", "/api/v", None, H)
    if s != 503:
        fail("more than MAX_CONN at once: want 503, got %d" % s)
    for t in tasks:
        await t
    if not all(w.closed for w in stuck) or srv.busy != 0:
        fail("stuck phones not closed: busy %d" % srv.busy)
    s, _, b = await req("GET", "/api/v", None, H)
    if s != 200:
        fail("after the timeouts: %d" % s)

    # What phones opened survives a restart.
    srv.phone.save()
    p2 = lvphone.Phone(ship, ROOT, quiet)
    if not p2.local.is_open(CA, DAY):
        fail("opened drop not kept in local.bin")
    # Records arriving over BLE move v (the page then refreshes).
    v = ship.v
    ship._new([])
    if ship.v != v + 1:
        fail("v on new records")

q = b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07captive\x05apple\x03com\x00\x00\x01\x00\x01"
a = lvweb.dns_answer(q, "192.168.4.1")
if a is None or a[-4:] != bytes([192, 168, 4, 1]) or a[6:8] != b"\x00\x01":
    fail("dns A answer")
q6 = q[:-4] + b"\x00\x1c\x00\x01"
a = lvweb.dns_answer(q6, "192.168.4.1")
if a is None or a[6:8] != b"\x00\x00":
    fail("dns AAAA: want no answer")
if lvweb.dns_answer(b"\x00" * 5, "192.168.4.1") is not None:
    fail("dns junk")

asyncio.run(main())
print("phone server on %s, day %d: %s" % (sys.implementation.name, DAY, "ok" if not FAILS else "%d FAILED" % len(FAILS)))
if FAILS:
    sys.exit(1)
