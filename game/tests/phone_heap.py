#!/usr/bin/env python3
"""Phones playing on a ship while it syncs over BLE, with the board's heap measured.
Starts tests/mp_sync_heap.py --phone under MicroPython (the board side, one process) and
plays two phones against it from here (tests/phone_flow.py over real sockets, so the
phones' buffers aren't on the board's heap). Every answer is checked; the heap line and
RESULT come from the board side, with the 110,000 B cap at 32-bit (mp_sync_heap.CAP).
  python3 tests/phone_heap.py MICROPYTHON [dir | frozen] [--led] [--bat] [--ota [--live]] [--everyone]  (from game/)
  python3 tests/phone_heap.py LV_FROZEN_MP --safe     safe mode (tests/mp_safe_heap.py) takes a whole update
--ota: a third phone uploads a signed update (the game firmware's own files as a newer
version, signed with a test key) in pieces while the two play, the way web/ota.js does:
a refused envelope first, a piece at a wrong offset, then everything; the board checks
the signature and each file, and the heap peak includes all of it. Then it cancels
(applying restarts the board: tests/test_ota.py covers that). The home-screen funnel's
/api/hello (board/lvfunnel.py, main.py's ota_route) is asked three times meanwhile, and a
fourth phone changes a crew code and back (board/lvcode.py, POST /api/code), and a fifth
taps Test light twice (board/lvledtest.py, POST /api/led/test: 10 s of blinks and
three software-PWM breaths on a counted pin, a tap meanwhile refused). With --bat
too, main.py's charger watch runs on the board and a phone asks /api/bat twelve times."""
import asyncio
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]
os.chdir(ROOT)
import phone_flow as F            # noqa: E402
# Every phone's clock, shifted together by LV_HEAP_CLOCK_SHIFT_MS (default 0) so a run
# can be pinned to another time of day or date; the board's other time is its uptime.
CLOCK_SHIFT = int(os.environ.get("LV_HEAP_CLOCK_SHIFT_MS") or 0)
PHONE_TIME = str(1793000000000 + CLOCK_SHIFT)
F.PHONE_TIME = str(int(F.PHONE_TIME) + CLOCK_SHIFT)
from lv import codes as K         # noqa: E402

DATA = "build/heap-data"
OTA_MOD = "build/heap-ota-mod"
OTA_DIR = "build/heap-ota"


def ota_setup():
    """board/lvota.py with a test key and its own staging dir, compiled like the board's
    modules; and a signed update of build/board-fw/'s files. -> (envelope bytes, [file bytes])."""
    import base64
    import hashlib
    import shutil
    sys.path.insert(0, os.path.join(ROOT, "tools", "ota"))
    import ed25519
    seed = hashlib.sha256(b"heap test key, not the release key").digest()
    pub = ed25519.public_key(seed)
    kid = hashlib.sha256(pub).hexdigest()[:8]
    src = open("board/lvota.py").read()
    a = src.index("KEYS = {")
    b = src.index("\n", a)
    src = src[:a] + 'KEYS = {"%s": unhexlify("%s")}' % (kid, pub.hex()) + src[b:]
    src = src.replace('OTA = "ota"\n', 'OTA = "%s"\n' % OTA_DIR, 1)
    shutil.rmtree(OTA_MOD, ignore_errors=True)
    shutil.rmtree(OTA_DIR, ignore_errors=True)
    os.makedirs(OTA_MOD)
    os.makedirs(OTA_DIR)
    open(OTA_MOD + "/lvota.py", "w").write(src)
    # lvotap (the upload, 0.3.0) stages under the same test dir
    src = open("board/lvotap.py").read()
    assert 'OTA = "ota"\n' in src
    open(OTA_MOD + "/lvotap.py", "w").write(src.replace('OTA = "ota"\n', 'OTA = "%s"\n' % OTA_DIR, 1))
    mpyc = os.environ.get("MPY_CROSS")
    if mpyc:
        for n in ("lvota", "lvotap"):
            subprocess.run([mpyc, "-O3", "-o", OTA_MOD + "/%s.mpy" % n, OTA_MOD + "/%s.py" % n], check=True)
            os.remove(OTA_MOD + "/%s.py" % n)
    files = []
    for dp, _, fs in os.walk("build/board-fw"):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, "build/board-fw").replace(os.sep, "/")
            if rel != "boot.py" and not rel.startswith("lvboot."):     # never over the air
                files.append((rel, open(p, "rb").read()))
    files.sort()
    core = json.load(open("build/frozen-core.json"))["core"]
    m = {"schema": 1, "project": "LongVoyage", "version": "9.9.9-heap", "channel": "test", "core": core,
         "files": [[p, len(b), hashlib.sha256(b).hexdigest()] for p, b in files], "delete": []}
    t = json.dumps(m, separators=(",", ":"))
    sig = ed25519.sign(seed, b"LV-OTA-1\n" + hashlib.sha256(t.encode()).digest())
    env = json.dumps({"m": t, "sig": base64.b64encode(sig).decode(), "kid": kid}).encode()
    bad = json.dumps({"m": t.replace("9.9.9-heap", "9.9.8-heap"), "sig": base64.b64encode(sig).decode(),
                      "kid": kid}).encode()
    return env, bad, [b for _, b in files]


async def ota_upload(req, env, bad, files, fail, log):
    """What web/ota.js does: sign in, look, send the envelope and the files in pieces."""
    def js(b):
        return json.loads(b) if b else {}
    s, _, b = await req("POST", "/api/login", json.dumps({"crew": 3, "pin": "1234"}).encode(), {})
    tok = js(b).get("token")
    if s != 200 or not tok:
        return fail("ota: login %d %s" % (s, b))
    H = {"X-Crew-Token": tok}
    s, _, b = await req("GET", "/api/ota", None, {})
    st = js(b)
    if s != 200 or not st.get("ota") or not st.get("chunk"):
        return fail("ota: status %d %s" % (s, b))
    n = st["chunk"]
    s, _, b = await req("POST", "/api/ota/put?f=0&n=%d&o=0" % len(bad), bad[:n], {})
    if s != 401:
        fail("ota: put signed out: %d" % s)

    async def send(f, data, extra=""):
        o = 0
        while o < len(data) or (o == 0 and not data):
            s, _, b = await req("POST", "/api/ota/put?f=%d%s&o=%d" % (f, extra, o), data[o:o + n], H)
            j = js(b)
            if s == 409 and j.get("have") is not None:
                o = j["have"]
                continue
            if s != 200:
                return s, j
            o = j.get("have", o + n)
            if j.get("done") or not data:
                break
        return 200, j
    s, j = await send(0, bad, "&n=%d" % len(bad))
    if s != 403 or "signature" not in j.get("err", ""):
        fail("ota: a tampered envelope: %d %s" % (s, j))
    s, j = await send(0, env, "&n=%d" % len(env))
    if s != 200:
        return fail("ota: envelope %d %s" % (s, j))
    # a piece at the wrong offset: 409 with where to carry on
    s, _, b = await req("POST", "/api/ota/put?f=1&o=%d" % (n * 3), files[0][:n], H)
    if s != 409 or js(b).get("have") != 0:
        fail("ota: wrong offset %d %s" % (s, b))
    for i, data in enumerate(files):
        s, j = await send(i + 1, data)
        if s != 200:
            return fail("ota: file %d: %d %s" % (i + 1, s, j))
    s, _, b = await req("GET", "/api/ota", None, {})
    st = js(b).get("staged") or {}
    if st.get("v") != "9.9.9-heap" or st.get("have") != st.get("sizes"):
        fail("ota: staged %s" % st)
    s, _, b = await req("POST", "/api/ota/cancel", b"", H)
    if s != 200:
        fail("ota: cancel %d" % s)
    log("ota: uploaded %d files, %d B in %d B pieces, signature and checksums checked on the board" % (
        len(files), sum(len(x) for x in files), n))


async def funnel_hello(req, fail, log):
    """What web/funnel.js does as a phone opens the page: /api/hello (board/lvfunnel.py,
    loaded and dropped per request): a Safari tab, then an icon launch, then a tab again."""
    seen = []
    for q in ("ctx=ios", "ctx=standalone&m=icon", "ctx=ios"):
        s, _, b = await req("GET", "/api/hello?" + q, None, {"X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"})
        if s != 200:
            return fail("funnel: hello %s: %d %s" % (q, s, b))
        seen.append(json.loads(b).get("installed"))
    if seen != [0, 1, 1]:
        return fail("funnel: installed after each hello %s" % seen)
    log("funnel: a tab, an icon launch, a tab again: the ship remembered the icon")


async def code_change(req, fail, log):
    """Change your code (board/lvcode.py, loaded and dropped per request) while the others
    play: crew 3 signs in, gets the current code wrong once, changes it, signs in with the
    new one, and changes it back (crew.json rewritten through crew.json.new each time)."""
    H = {"User-Agent": "heapC", "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"}

    async def call(path, obj, tok=None):
        h = dict(H)
        if tok:
            h["X-Crew-Token"] = tok
        for _ in range(50):
            # Four phones at once on the board's 4 connections: a busy board answers 503
            # and closes before reading the body, which can reach us as a reset instead.
            try:
                s, _, b = await req("POST", path, bytes(json.dumps(obj), "utf-8"), h)
            except OSError:
                s, b = 503, b"reset"
            if s != 503:
                break
            await asyncio.sleep(0.2)
        return s, b
    s, b = await call("/api/login", {"crew": 3, "pin": "1234"})
    if s != 200:
        return fail("code: sign-in %d %s" % (s, b))
    tok = json.loads(b)["token"]
    steps = ((("1111", "5678"), 403), (("1234", "5678"), 200), (("5678", "1234"), 200))
    s, _ = await call("/api/code", {"old": "1234", "new": "5678"})
    if s != 401:
        return fail("code: without a session %d, want 401" % s)
    for i, ((old, new), want) in enumerate(steps):
        s, b = await call("/api/code", {"old": old, "new": new}, tok)
        if s != want:
            return fail("code: step %d %d %s, want %d" % (i, s, b, want))
        if i == 1:
            s2, _ = await call("/api/login", {"crew": 3, "pin": "5678"})
            if s2 != 200:
                return fail("code: the new code didn't sign in (%d)" % s2)
    log("code: wrong current code refused, changed, signed in with the new one, changed back")


async def led_test(req, fail, log, hail=False, uploaded=None):
    """Test light (board/lvledtest.py, loaded per request; its pattern a task for 10 s) while
    the others play: crew 4 taps it, taps again while it plays (429), waits it out, and
    taps once more; a tap with no session is 401. The board counts the pin's writes."""
    H = {"User-Agent": "heapL", "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"}

    async def call(path, obj, tok=None):
        h = dict(H)
        if tok:
            h["X-Crew-Token"] = tok
        for _ in range(50):
            try:
                s, _, b = await req("POST", path, bytes(json.dumps(obj), "utf-8"), h)
            except OSError:
                s, b = 503, b"reset"
            if s != 503:
                break
            await asyncio.sleep(0.2)
        return s, b
    # After the two players have their page and data: the board takes 4 connections, and
    # their own requests don't retry a busy board's reset.
    await asyncio.sleep(3)
    s, b = await call("/api/login", {"crew": 4, "pin": "1234"})
    if s != 200:
        return fail("led test: sign-in %d %s" % (s, b))
    tok = json.loads(b)["token"]
    s, _ = await call("/api/led/test", {})
    if s != 401:
        return fail("led test: without a session %d, want 401" % s)
    # Hail owns the shared pin first; do not mistake its exclusion for a failed test.
    s, b = await call("/api/led/test", {}, tok)
    if hail and s != 429:
        return fail("led test: initial Hail ownership %d %s, want 429" % (s, b))
    for _ in range(120):
        if s != 429:
            break
        await asyncio.sleep(0.5)
        s, b = await call("/api/led/test", {}, tok)
        if s != 429:
            break
    else:
        return fail("led test: Hail never released the light")
    count = 3 if uploaded is not None and not hail else 2
    for i in range(count):
        if i == 2:
            # Preserve both concurrent patterns, then add a genuinely quiet
            # playback. A continuous upload correctly uses the busy blink,
            # which cannot demonstrate the separate >=200-write PWM check.
            await uploaded.wait()
        if i:
            for _ in range(120):
                s, b = await call("/api/led/test", {}, tok)
                if s != 429:
                    break
                # Another incoming Hail can acquire the pin between playbacks.
                await asyncio.sleep(0.5)
        if s != 200 or json.loads(b).get("ms") != 10000:
            return fail("led test: tap %d %d %s" % (i, s, b))
        await asyncio.sleep(0.5)
        s, b = await call("/api/led/test", {}, tok)
        if s != 429:
            return fail("led test: a tap while it plays %d %s, want 429" % (s, b))
        await asyncio.sleep(10.2)
    log("led test: played %d times, a tap meanwhile refused each time, none without a session" % count)


async def bat_look(req, fail, log):
    """The page's battery look (web/batt.js: GET /api/bat every 5 s while showing), faster:
    twelve looks while the others play, each [percent, mV, charging] from main.py."""
    n = 0
    for _ in range(12):
        await asyncio.sleep(0.5)
        try:
            s, _, b = await req("GET", "/api/bat", None, {})
        except OSError:
            continue
        if s == 503:
            continue
        j = json.loads(b) if s == 200 else None
        if not j or not j.get("bat") or j["bat"][0] != 72 or j["bat"][2] is not True:
            return fail("bat: /api/bat %d %s" % (s, b))
        n += 1
    if n < 6:
        return fail("bat: only %d of 12 looks answered" % n)
    log("bat: /api/bat answered %d looks, 72%% and charging" % n)


async def live_hail(req, fail, log):
    """--live: crew 5 opens the ship-to-ship page (GET /api/live), waits for ship 2 to show up
    able to take hails, hails it (POST /api/live/hail), and polls until the peer's ship has
    it ("Delivered"), taking the peer's hail meanwhile and marking it seen; /api/coex is asked
    too, without a session (401) and with one. lvliveapi loads per request through main.py's ota_route."""
    H = {"User-Agent": "heapV", "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"}

    async def call(method, path, obj=None, tok=None):
        h = dict(H)
        if tok:
            h["X-Crew-Token"] = tok
        for _ in range(50):
            try:
                s, _, b = await req(method, path, bytes(json.dumps(obj), "utf-8") if obj is not None else b"", h)
            except OSError:
                s, b = 503, b"reset"
            if s != 503:
                break
            await asyncio.sleep(0.2)
        return s, b
    await asyncio.sleep(4)
    s, b = await call("POST", "/api/login", {"crew": 5, "pin": "1234"})
    if s != 200:
        return fail("live: sign-in %d %s" % (s, b))
    tok = json.loads(b)["token"]
    s, b = await call("GET", "/api/coex")
    if s != 401:
        return fail("live: /api/coex without a session %d, want 401 (0.3.0 R3 m3)" % s)
    s, b = await call("GET", "/api/coex", None, tok)
    if s != 200 or "ble" not in json.loads(b):
        return fail("live: /api/coex %d %s" % (s, b))
    s, _ = await call("GET", "/api/live")
    if s != 401:
        return fail("live: /api/live without a session %d, want 401" % s)
    j = None
    for _ in range(600):
        s, b = await call("GET", "/api/live", None, tok)
        if s != 200:
            return fail("live: /api/live %d %s" % (s, b))
        j = json.loads(b)
        if any(p["s"] == 1 and p.get("cap") for p in j["peers"]):
            break
        await asyncio.sleep(0.5)
    else:
        return fail("live: ship 2 never heard able to take hails: %s" % j)
    s, b = await call("POST", "/api/live/hail", {"to": 1, "ph": 0}, tok)
    if s != 200:
        return fail("live: hail %d %s" % (s, b))
    hid = json.loads(b)["id"]
    s, b = await call("POST", "/api/live/hail", {"to": 1, "ph": 1}, tok)
    if s != 429:
        return fail("live: a second hail while the first is on its way %d %s, want 429" % (s, b))
    got = sent = False
    for _ in range(1200):
        s, b = await call("GET", "/api/live", None, tok)
        j = json.loads(b) if s == 200 else {}
        for o in j.get("out", ()):
            if o["id"] == hid and o["st"] >= 2:
                sent = True
        for i in j.get("in", ()):
            if i["from"] == 1 and not got:
                got = True
                s2, b2 = await call("POST", "/api/live/seen", {"id": i["id"]}, tok)
                if s2 != 200:
                    return fail("live: seen %d %s" % (s2, b2))
        if sent and got:
            break
        await asyncio.sleep(0.5)
    else:
        return fail("live: hail delivered %s, peer's hail in %s: %s" % (sent, got, j))
    # The radio test's probes, 4 KB each (streamed by lvliveapi.ping), while the sync runs.
    for k in range(6):
        s, b = await call("GET", "/api/coex/ping?kb=4", None, tok)
        if s != 200 or len(b) != 4096:
            return fail("live: /api/coex/ping %d %d B" % (s, len(b)))
    log("live: hailed ship 2 (delivered), a second refused while on its way, ship 2's hail in and seen,"
        " 6 radio-test probes of 4 KB")


async def duel_phone(req, who, fire, fail, log):
    """Two independent phones stream /api/live as a duel shot is taken and answered.
    This workload never signs an update; --ota remains a separate optional fixture."""
    h = {"User-Agent": "duel-heap-%d" % who, "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"}
    s, _, raw = await req("POST", "/api/login", json.dumps({"crew": who, "pin": "1234"}).encode(), h)
    if s != 200:
        return fail("duel: sign-in %d" % s)
    h["X-Crew-Token"] = json.loads(raw)["token"]
    fired = False
    stage = 0
    started = time.monotonic()
    observed = None
    async def phase(name):
        with open(DATA + "/duel-phase", "w") as f:
            f.write(name)
        for _ in range(400):
            try:
                with open(DATA + "/duel-phase-ack") as f:
                    if f.read() == name:
                        return
            except OSError:
                pass
            await asyncio.sleep(.05)
        raise RuntimeError("duel phase was not observed: " + name)
    for k in range(400):
        s, headers, raw = await req("GET", "/api/live", None, h)
        if s != 200:
            return fail("duel: live status %d" % s)
        try:
            games = json.loads(raw).get("duel", [])
        except ValueError:
            log("duel: malformed live response headers=%r body=%r" % (headers, raw))
            raise
        # The page also lists the fixture's owed stubs for crewmates with no game here
        # (lvduelview.view, review 0.3.1-9 #1): exactly crewmates 4-7, never 1-3.
        stubs = [x for x in games if x.get("stub")]
        games = [x for x in games if not x.get("stub")]
        g = next((g for g in games if g["to"] == 1), None)
        progress = (stage, g.get("s"), g.get("n"), g.get("pending")) if g else None
        if progress != observed:
            log("duel: phone %d after %.1f s: %r" % (who, time.monotonic() - started, progress))
            observed = progress
        # Both phones must actually receive all three long histories. Seeded
        # n=68 is not success: require the injected 69th + phone's 70th answer.
        if len(games) != 3 or {x["to"] for x in games} != {1, 2, 3} or any(
                len(x["shots"]) + len(x["incoming"]) != x["n"] for x in games) or any(
                x["n"] != 70 or x["s"] != "active" for x in games if x["to"] in (2, 3)):
            return fail("duel: missing or truncated worst-case histories")
        if sorted(x["to"] for x in stubs) != [4, 5, 6, 7] or any(
                x["s"] != "done" or x["pending"] is not True or x["record"] != [123, 123] or
                set(x) != {"to", "id", "s", "stub", "pending", "record"} for x in stubs):
            return fail("duel: owed stubs of crewmates 4-7 missing or changed: %r" % (stubs,))
        if not fire:
            if g["s"] == "draft" and g["n"] == 0:
                log("duel: observer saw terminal/rematch flow with both other long histories intact")
                return
        elif stage == 0 and g["s"] == "done" and g["n"] == 71:
            if len(g["their"] or []) != 3 or g["win"] is not False:
                return fail("duel: terminal reveal was not verified")
            log("duel: 71st shot and mutual reveal with complete transcript replay")
            open(DATA + "/duel-rematch", "w").close()
            stage = 1
        elif stage == 1 and g["s"] == "invited":
            await phase("accept")
            s, _, raw = await req("POST", "/api/live/duel", json.dumps({"action": "accept", "to": 1, "layout": [[0, 0], [12, 0], [35, 0]]}).encode(), h)
            if s != 200:
                return fail("duel: accept %d %s" % (s, raw))
            stage = 2
        elif stage == 2 and g["s"] == "active" and not g["pending"]:
            await phase("resign")
            s, _, raw = await req("POST", "/api/live/duel", json.dumps({"action": "resign", "to": 1}).encode(), h)
            if s != 200:
                return fail("duel: resign %d %s" % (s, raw))
            stage = 3
        elif stage == 3 and g["s"] == "done" and not g["pending"]:
            await phase("new")
            s, _, raw = await req("POST", "/api/live/duel", json.dumps({"action": "new", "to": 1}).encode(), h)
            if s != 200:
                return fail("duel: new %d %s" % (s, raw))
            log("duel: phone accept/resign/new with two other 70-shot games")
            return
        if fire and stage == 0 and not fired and g and g["turn"] and not g["pending"]:
            s, _, raw = await req("POST", "/api/live/duel", json.dumps({"action": "fire", "to": 1, "cell": 34}).encode(), h)
            if s != 200:
                return fail("duel: fire %d %s" % (s, raw))
            fired = True
        await asyncio.sleep(.1)
    fail("duel: moves did not finish for phone %d" % who)


async def safe_looks(req, fail, log):
    """--safe: another phone on the safe-mode ship meanwhile: the crew list, a reload's
    /api/me, the story's 503 {safe} once signed in, the version poll (board/lvsafe.py)."""
    H = {"User-Agent": "heapS", "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-360"}
    s, _, b = await req("GET", "/api/crew", None, H)
    if s != 200 or not json.loads(b).get("safe"):
        return fail("safe: /api/crew %d %s" % (s, b))
    s, _, b = await req("POST", "/api/login", json.dumps({"crew": 2, "pin": "1234"}).encode(), H)
    if s != 200:
        return fail("safe: sign-in %d %s" % (s, b))
    h = dict(H, **{"X-Crew-Token": json.loads(b)["token"]})
    n = 0
    for _ in range(40):
        for path, want in (("/api/state", 503), ("/api/v", 200), ("/api/me", 200), ("/api/ota", 200)):
            try:
                s, _, b = await req("GET", path, None, h)
            except OSError:
                continue
            if s == 503 and path != "/api/state":
                continue            # busy: the board's 4 connections
            if s != want:
                return fail("safe: %s %d %s" % (path, s, b[:80]))
            n += 1
        await asyncio.sleep(0.2)
    log("safe: %d looks answered by safe mode while the update came in" % n)


def safe_main(mp, mode):
    """--safe: tests/mp_safe_heap.py (safe mode on the game firmware) takes a whole signed
    update while another phone looks around; its heap peak must stay under the cap."""
    os.makedirs(DATA, exist_ok=True)
    ota = ota_setup()
    with open(DATA + "/crew.json", "w") as f:
        json.dump(K.make_config(["1234"] * 7 + [None], b"bench-salt-16-by"), f)
    p = subprocess.Popen([mp, "-X", "heapsize=512k", "tests/mp_safe_heap.py", "frozen"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    port = None
    for line in p.stdout:
        if line.startswith("PORT "):
            port = int(line.split()[1])
            break
        print(line, end="")
    if port is None:
        print(p.stdout.read())
        sys.exit("safe mode never started its server")
    fails = []

    async def phones():
        req = F.tcp(port)
        return await asyncio.gather(ota_upload(req, ota[0], ota[1], ota[2], fails.append, print),
                                    safe_looks(req, fails.append, print))
    try:
        asyncio.run(phones())
    except Exception as e:
        fails.append("phones: %r" % (e,))
    finally:
        open(DATA + "/done", "w").close()
    out = p.stdout.read()
    p.wait()
    print(out, end="")
    try:
        os.remove(DATA + "/fault.json")
    except OSError:
        pass
    for f in fails:
        print("PHONE FAIL", f)
    if fails or p.returncode or "RESULT PASS" not in out:
        sys.exit(1)


def board_current():
    """Measure today's board code (fix round 0.3.1-11): tools/fw/src_stamp.ensure rebuilds
    a build/board-fw older than the sources, or refuses."""
    sys.path.insert(0, "tools/fw")
    import src_stamp
    src_stamp.ensure()


def main(argv):
    mp, mode = argv[0], argv[1:]
    board_current()
    if "--safe" in mode:
        return safe_main(mp, mode)
    os.makedirs(DATA, exist_ok=True)
    for name in ("duel-rematch", "duel-phase", "duel-phase-ack"):
        try:
            os.remove(DATA + "/" + name)
        except OSError:
            pass
    try:
        os.remove(DATA + "/funnel.bin")      # the phones the last run's ship remembered
    except OSError:
        pass
    ota = ota_setup() if "--ota" in mode else None
    with open(DATA + "/crew.json", "w") as f:
        json.dump(K.make_config(["1234"] * 7 + [None], b"bench-salt-16-by"), f)
    p = subprocess.Popen([mp, "-X", "heapsize=512k", "tests/mp_sync_heap.py"] + mode + ["--phone"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    port = None
    for line in p.stdout:
        if line.startswith("PORT "):
            port = int(line.split()[1])
            break
        print(line, end="")
    fails = []
    if port is None:
        print(p.stdout.read())
        sys.exit("board side never started its server")
    assets = {n: open("build/" + n, "rb").read() for n in ("app.html.gz", "text.json.gz", "engage.json.gz", "app.webmanifest.gz", "icon.png.gz")}

    async def phones():
        tcp = F.tcp(port)

        async def req(method, path, body=None, headers=None):
            # Admission can refuse before reading a request; read-only clients retry
            # resets too, just as a phone's next poll does. Never replay a POST reset.
            for _ in range(1000):
                try:
                    answer = await tcp(method, path, body, headers)
                    if answer[0] != 503:
                        return answer
                except OSError:
                    if p.poll() is not None:
                        raise RuntimeError("board process exited during " + path)
                    if method != "GET":
                        raise
                await asyncio.sleep(0.2)
            raise RuntimeError("board stayed busy: " + path)

        jobs = [F.session(req, "heapA", 1, "1234", fails.append, assets, log=print),
                F.session(req, "heapB", 6, "1234", fails.append, assets, log=print)]
        if "--duel" in mode:
            jobs.append(duel_phone(req, 2, True, fails.append, print))
            jobs.append(duel_phone(req, 4, False, fails.append, print))
        if ota:
            uploaded = asyncio.Event()

            async def upload():
                try:
                    return await ota_upload(req, ota[0], ota[1], ota[2], fails.append, print)
                finally:
                    uploaded.set()

            jobs.append(upload())
            jobs.append(funnel_hello(req, fails.append, print))
            jobs.append(code_change(req, fails.append, print))
            jobs.append(led_test(req, fails.append, print, "--live" in mode, uploaded))
            if "--live" in mode:
                jobs.append(live_hail(req, fails.append, print))
            if "--bat" in mode:
                jobs.append(bat_look(req, fails.append, print))
        return await asyncio.gather(*jobs)
    try:
        asyncio.run(phones())
    except Exception as e:           # a phone's own error: still show what the board said
        fails.append("phones: %r" % (e,))
    finally:
        open(DATA + "/done", "w").close()
    out = p.stdout.read()
    p.wait()
    print(out, end="")
    for f in fails:
        print("PHONE FAIL", f)
    if fails or p.returncode or "RESULT PASS" not in out:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
