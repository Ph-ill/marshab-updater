# Over-the-air updates on the ship (board/lvota.py, lvboot.py, lvsig.py): signed envelopes
# accepted and refused (bad signature, unknown key, another core, a downgrade or replay,
# paths under data/ or ota/, boot.py, lvboot, ".."), the upload in pieces (wrong offset
# 409 + resume, a tampered file, too much), apply, the swap at boot, keeping it (good()),
# the rollback after two failed boots, a power cut at every step of the swap and of the
# rollback, the bench's maint/safe boots, the deadline timer, the HTTP side with and
# without a crew token, and /data byte-for-byte the same through all of it.
# Runs on CPython (signs the test updates with tools/ota/ed25519.py, a test key, and
# writes them to build/ota-fixtures.json) and on MicroPython (reads them):
#   python3 tests/test_ota.py && micropython tests/test_ota.py        (from game/)
import sys
import os
import json

CPY = sys.implementation.name == "cpython"
HERE = os.getcwd()
sys.path.insert(0, HERE + "/board")
sys.path.insert(0, HERE + "/tests")
import lvota   # noqa: E402
import lvboot  # noqa: E402

FIX = HERE + "/build/ota-fixtures.json"
ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


CORE = "2661c2144844"
OLD = {"main.py": b"# old main\nprint('old')\n", "www/app.html.gz": b"old page" * 50,
       "config.py": b"OLD = 1\n", "engage.bin": b"\x01\x02old",
       "version.json": b'{"schema":2,"project":"LongVoyage","version":"0.2.0-lv-test","channel":"test","frozen":"2661c2144844"}\n'}
DATA = {"data/ship.json": b'{"ship": 2}', "data/crew.json": b'{"crew": "placeholder"}',
        "data/log.bin": bytes(range(256)) * 3}


def vj(v):
    return ('{"schema":2,"project":"LongVoyage","version":"%s","channel":"test","frozen":"%s"}\n' % (v, CORE)).encode()


def update(v, extra=None):
    """The files of a test update: a new main.py (reports in), page, an added module."""
    f = {"main.py": ("# main %s\nimport lvota\n" % v).encode() * 3,
         "www/app.html.gz": ("page %s " % v).encode() * 700,       # several pieces
         "lvnew.mpy": ("new module %s" % v).encode(), "version.json": vj(v)}
    f.update(extra or {})
    return f


def manifest(v, files, core=CORE, delete=("config.py",), **kw):
    import hashlib
    m = {"schema": 1, "project": "LongVoyage", "version": v, "channel": "test", "core": core,
         "files": [[p, len(b), hashlib.sha256(b).hexdigest()] for p, b in sorted(files.items())],
         "delete": list(delete)}
    m.update(kw)
    return m


def b64(b):
    import binascii
    return str(binascii.b2a_base64(b), "ascii").strip()


def write_fixtures():
    sys.path.insert(0, HERE + "/tools/ota")
    import ed25519
    import hashlib
    seed = bytes(range(32))           # a test key, not the release key
    pub = ed25519.public_key(seed)
    kid = hashlib.sha256(pub).hexdigest()[:8]

    def env(m, key=seed, kid=kid):
        t = json.dumps(m, separators=(",", ":"))
        s = ed25519.sign(key, lvota.TAG + hashlib.sha256(t.encode()).digest())
        return {"m": t, "sig": b64(s), "kid": kid}
    fx = {"pub": pub.hex(), "kid": kid, "files": {}, "env": {}}
    for v in ("0.2.1-lv-test", "0.2.2-lv-test", "0.2.3-lv-test"):
        files = update(v, {"lvextra.mpy": b"added in 0.2.3"} if v == "0.2.3-lv-test" else None)
        fx["files"][v] = {p: b64(b) for p, b in files.items()}
        fx["env"][v] = env(manifest(v, files))
    f1 = update("0.2.1-lv-test")
    e = env(manifest("0.2.1-lv-test", f1))
    e["m"] = e["m"].replace("0.2.1-lv-test", "0.2.9-lv-test", 1)         # edited after signing
    fx["env"]["tampered"] = e
    fx["env"]["otherkey"] = env(manifest("0.2.1-lv-test", f1), key=bytes(32), kid=kid)
    fx["env"]["unknownkid"] = env(manifest("0.2.1-lv-test", f1), kid="00000000")
    fx["env"]["core"] = env(manifest("0.2.1-lv-test", f1, core="f1b383588e79"))
    fx["env"]["old"] = env(manifest("0.1.0-lv-test", f1))
    fx["env"]["same"] = env(manifest("0.2.0-lv-test", f1))
    for name, p in (("data", "data/crew.json"), ("ota", "ota/state.json"), ("boot", "boot.py"),
                    ("lvboot", "lvboot.mpy"), ("dots", "www/../data/crew.json"), ("abs", "/main.py")):
        fx["env"]["path_" + name] = env(manifest("0.2.1-lv-test", update("0.2.1-lv-test", {p: b"x"})))
    fx["env"]["del_data"] = env(manifest("0.2.1-lv-test", f1, delete=("data",)))
    huge = manifest("0.2.1-lv-test", f1)
    huge["files"].append(["big.bin", 900000, "0" * 64])
    fx["env"]["huge"] = env(huge)
    with open(FIX, "w") as f:
        json.dump(fx, f)
    return fx


FX = write_fixtures() if CPY else json.load(open(FIX))
import binascii   # noqa: E402
FILES = {v: {p: binascii.a2b_base64(b) for p, b in fs.items()} for v, fs in FX["files"].items()}
lvota.KEYS = {FX["kid"]: binascii.unhexlify(FX["pub"])}

# -- a ship's flash, in a directory of its own
W = HERE + "/build/ota-test-" + sys.implementation.name


def rm(p):
    lvota.rmtree(p)


rm(W)
lvota._mkdirs(W[len(HERE) + 1:])     # (relative: like every path on the board)
os.chdir(W)


def write(p, b):
    if "/" in p:
        lvota._mkdirs(p.rsplit("/", 1)[0])
    with open(p, "wb") as f:
        f.write(b)


def read(p):
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


for p, b in list(OLD.items()) + list(DATA.items()):
    write(p, b)


def data_same(name):
    for p, b in DATA.items():
        check(name + ": " + p + " untouched", read(p) == b)


def ship_runs(files, name):
    for p, b in files.items():
        check(name + ": " + p, read(p) == b, repr(read(p))[:60])


def send_env(env, piece=300):
    raw = json.dumps(env).encode()
    n = len(raw)
    r = None
    for o in range(0, n, piece):
        r = lvota.put({"f": "0", "n": str(n), "o": str(o)}, raw[o:o + piece])
        if r[0] != 200:
            return r
    return r


def send_files(v, piece=1024, skip=None):
    m = lvota.manifest()
    for i, (p, size, sha) in enumerate(m["files"]):
        b = FILES[v][p]
        for o in range(0, max(1, size), piece):
            if skip and skip(i + 1, o):
                continue
            r = lvota.put({"f": str(i + 1), "o": str(o)}, b[o:o + piece])
            if r[0] != 200:
                return r
    return 200, {}


# -- refused envelopes: nothing staged, nothing changed
for name, want in (("tampered", "signature"), ("otherkey", "signature"), ("unknownkid", "key"),
                   ("core", "firmware"), ("old", "newer"), ("same", "newer"),
                   ("path_data", "file"), ("path_ota", "file"), ("path_boot", "file"),
                   ("path_lvboot", "file"), ("path_dots", "file"), ("path_abs", "file"),
                   ("del_data", "delete"), ("huge", "file")):
    r = send_env(FX["env"][name])
    check("refused " + name, r[0] == 403 and want in r[1]["err"], r)
    check("refused %s: nothing staged" % name, lvota.manifest() is None and lvota.status()["staged"] is None)
r = lvota.put({"f": "0", "n": "20", "o": "0"}, b'{"m": "x", "sig": "!!"')
r = lvota.put({"f": "0", "n": "20", "o": "22"}, b"x")
check("envelope: past its size", r[0] == 400 or r[0] == 409, r)
check("files before the envelope", lvota.put({"f": "1", "o": "0"}, b"x")[0] == 409)
check("apply with nothing staged", lvota.apply()[0] == 409)
lvota.rmtree(lvota.NEW)
ship_runs(OLD, "after refusals")
data_same("after refusals")

# -- 0.2.1 in pieces: a wrong offset says where to carry on; a bad file is thrown away
V1 = "0.2.1-lv-test"
raw = json.dumps(FX["env"][V1]).encode()
n = str(len(raw))
check("env piece 1", lvota.put({"f": "0", "n": n, "o": "0"}, raw[:300])[0] == 200)
r = lvota.put({"f": "0", "n": n, "o": str(len(raw) - 50)}, raw[-50:])
check("env: wrong offset -> 409 have", r[0] == 409 and r[1]["have"] == 300, r)
r = send_env(FX["env"][V1])     # starts again from 0
check("env accepted", r[0] == 200 and r[1]["v"] == V1, r)
st = lvota.status()
check("status: staged, nothing yet", st["staged"]["v"] == V1 and sum(st["staged"]["have"]) == 0, st)
m = lvota.manifest()
idx = [f[0] for f in m["files"]].index("www/app.html.gz") + 1
size = m["files"][idx - 1][1]
r = send_files(V1, skip=lambda i, o: i == idx and o >= 2048)
check("all but the page's tail", r[0] == 200)
st = lvota.status()
check("status: the page part-way", st["staged"]["have"][idx - 1] == 2048, st["staged"])
check("apply refused while a file is missing", lvota.apply()[0] == 409)
r = lvota.put({"f": str(idx), "o": "4096"}, b"x" * 10)
check("file: wrong offset -> 409 have", r[0] == 409 and r[1]["have"] == 2048, r)
r = lvota.put({"f": str(idx), "o": "2048"}, b"y" * (size - 2048 + 1))
check("file: more than its size", r[0] == 400, r)
good_tail = FILES[V1]["www/app.html.gz"][2048:]
r = lvota.put({"f": str(idx), "o": "2048"}, b"Z" + good_tail[1:])
check("file: tampered -> 400, thrown away", r[0] == 400 and "checksum" in r[1]["err"] and r[1]["have"] == 0, r)
r = send_files(V1)
check("file: sent again", r[0] == 200, r)
r = lvota.put({"f": str(idx), "o": "0"}, b"again")
check("file: already done", r[0] == 200 and r[1].get("done"), r)
ship_runs(OLD, "staged, not applied")
r = lvota.apply()
check("apply", r[0] == 200 and r[1]["v"] == V1, r)
check("state ready", lvota.read_json(lvota.STATE)["phase"] == "ready")
ship_runs(OLD, "applied, before the restart")

# -- the restart: boot.py swaps it in, on trial
check("boot: swap -> trial", lvboot.run() == "trial")
s = lvota.read_json(lvota.STATE)
check("trial, boot 1", s["phase"] == "trial" and s["boots"] == 1 and s["prev"] == "0.2.0-lv-test", s)
ship_runs(FILES[V1], "0.2.1 running")
check("config.py deleted (kept in ota/old)", read("config.py") is None and read("ota/old/config.py") == OLD["config.py"])
check("installed() is 0.2.1", lvota.installed()["v"] == V1)
data_same("0.2.1 on trial")
check("a second update while on trial", send_env(FX["env"]["0.2.2-lv-test"])[0] == 200)
lvota.rmtree(lvota.NEW)
check("good(): kept", lvota.good() is True)
check("last: installed", lvota.read_json(lvota.LAST)["result"] == "installed")
check("cleaned up", read(lvota.STATE) is None and lvota.os.listdir("ota") == ["last.json"], lvota.os.listdir("ota"))
check("boot after keeping: nothing to do", lvboot.run() is None)
check("good() again: nothing", lvota.good() is False)
ship_runs(FILES[V1], "0.2.1 kept")
check("replay of 0.2.1 refused", send_env(FX["env"][V1])[0] == 403)
data_same("0.2.1 kept")


def stage(v):
    lvota.rmtree(lvota.NEW)
    check("stage %s env" % v, send_env(FX["env"][v])[0] == 200)
    check("stage %s files" % v, send_files(v)[0] == 200)
    check("stage %s apply" % v, lvota.apply()[0] == 200)


# -- 0.2.2 never comes up: two counted boots, the third puts 0.2.1 back
V2 = "0.2.2-lv-test"
stage(V2)
check("2: boot 1", lvboot.run() == "trial")
ship_runs(FILES[V2], "0.2.2 on trial")
write("data/maint", b"")
check("bench boot (maint): not counted", lvboot.run() == "trial" and lvota.read_json(lvota.STATE)["boots"] == 1)
os.remove("data/maint")
check("2: boot 2", lvboot.run() == "trial" and lvota.read_json(lvota.STATE)["boots"] == 2)
check("2: boot 3 -> rolled back", lvboot.run() == "undo")
ship_runs(FILES[V1], "rolled back to 0.2.1")
check("rollback: last", lvota.read_json(lvota.LAST)["result"] == "rolled back"
      and lvota.read_json(lvota.LAST)["v"] == V2)
check("rollback: cleaned up", read(lvota.STATE) is None and read("ota/old/main.py") is None)
data_same("after the rollback")

# -- the deadline: still on trial when it fires -> machine.reset(); kept -> nothing


class FakeMachine:
    resets = 0

    @staticmethod
    def reset():
        FakeMachine.resets += 1


real_machine = sys.modules.get("machine")
sys.modules["machine"] = FakeMachine
stage(V2)
lvboot.run()
lvboot._deadline()
check("deadline on trial: reset", FakeMachine.resets == 1)
lvota.good()
lvboot._deadline()
check("deadline after good(): no reset", FakeMachine.resets == 1)
if real_machine is not None:
    sys.modules["machine"] = real_machine
else:
    del sys.modules["machine"]
ship_runs(FILES[V2], "0.2.2 kept")


# -- a power cut at every step of the swap, then of the rollback: the next boot finishes it


class Cut(BaseException):     # like pulling the plug: nothing in lvboot catches it
    pass


real_mv = lvboot._mv
real_save = lvboot._save


def cut_after(k):
    left = [k]

    def step(real):
        def f(a, b=None):
            if left[0] == 0:
                raise Cut()
            left[0] -= 1
            return real(a) if b is None else real(a, b)
        return f
    lvboot._mv, lvboot._save = step(real_mv), step(real_save)


def restore():
    lvboot._mv, lvboot._save = real_mv, real_save


V3 = "0.2.3-lv-test"
cuts = 0
for k in range(60):
    stage(V3)
    cut_after(k)
    try:
        lvboot.run()
        hit = False
    except Cut:
        hit = True
    restore()
    if not hit:          # the whole swap took fewer than k steps: every cut point tried
        ship_runs(FILES[V3], "swap without a cut")
        lvota.good()
        break
    cuts += 1
    check("cut %d: the next boot finishes the swap" % k, lvboot.run() == "trial")
    ship_runs(FILES[V3], "cut %d in the swap" % k)
    data_same("cut %d in the swap" % k)
    # the third boot rolls back; cut it at the same step, the boot after finishes it
    s = lvboot._load()
    s["boots"] = lvboot.MAX_BOOTS
    real_save(s)
    cut_after(k)
    try:
        lvboot.run()
        hit = False
    except Cut:
        hit = True
    restore()
    if hit:
        check("cut %d in the rollback: the next boot finishes it" % k, lvboot.run() == "undo")
    ship_runs(FILES[V2], "cut %d, rolled back" % k)
    check("cut %d: cleaned up" % k, read(lvota.STATE) is None and read("ota/old/main.py") is None)
    check("cut %d: the file 0.2.3 added is gone again" % k, read("lvextra.mpy") is None)
    data_same("cut %d, rolled back" % k)
check("power cuts tried", cuts >= 8, cuts)

# -- a broken state file: boot puts back what it can and carries on
write(lvota.STATE, b"{not json")
check("broken state: boot carries on", lvboot.run() is None)
ship_runs(FILES[V3], "after a broken state file")

# -- boot.py itself (as the board runs it, in its own namespace) on a staged update; it
# leaves lvboot loaded only while on trial (its deadline timer)
boot_src = open(HERE + "/board/boot.py").read()
lvota.good()
# (0.2.3 runs and nothing newer is signed: a trial state as lvboot leaves it after a swap)
lvota.write_json(lvota.STATE, {"phase": "trial", "v": V3, "prev": V2, "boots": 0,
                               "put": [], "had": [], "gone": []})
sys.modules.pop("lvboot", None)
exec(boot_src, {"__name__": "__main__"})
check("boot.py on trial: lvboot stays", "lvboot" in sys.modules
      and lvota.read_json(lvota.STATE)["boots"] == 1)
lvota.good()
sys.modules.pop("lvboot", None)
exec(boot_src, {"__name__": "__main__"})
check("boot.py with nothing pending: lvboot not loaded", "lvboot" not in sys.modules)
import lvboot  # noqa: E402,F811
lvboot._mv, lvboot._save = real_mv, real_save

# -- main.py's hooks: /api/ota* to lvota (dropped after), GitHub refused by the DNS, every
# other name still the board
main_src = open(HERE + "/board/main.py").read()
main_src = main_src[main_src.index("def ota_hooks"):main_src.index("\nasync def ota_ok")]


class FakeLvweb:
    MAX_BODY = 512

    @staticmethod
    def dns_answer(q, ip):
        # the board's answer: header, question, one A record when asked for one
        r = q[:2] + b"\x81\x80" + q[4:6] + b"\x00\x01\x00\x00\x00\x00" + q[12:]
        return r + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + bytes(ip)


class FakeServer:
    routed = []

    async def route(self, req, w):
        FakeServer.routed.append(req.path)


class FakeShip:
    @staticmethod
    def drop(name):
        sys.modules.pop(name, None)


g = {"lvship": FakeShip, "asyncio": None}
exec(main_src, g)
srv = FakeServer()
g["ota_hooks"](FakeLvweb, srv)
check("MAX_BODY for the update pieces", FakeLvweb.MAX_BODY == lvota.CHUNK)


def q(name):
    out = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    for part in name.split("."):
        out += bytes([len(part)]) + part.encode()
    return out + b"\x00\x00\x01\x00\x01"


for name, refused in (("raw.githubusercontent.com", True), ("api.github.com", True), ("github.com", True),
                      ("captive.apple.com", False), ("connectivitycheck.gstatic.com", False),
                      ("notgithub.company.com", False)):
    r = FakeLvweb.dns_answer(q(name), [192, 168, 4, 1])
    rc = r[3] & 15
    if refused:
        check("dns %s: REFUSED, no answer" % name, rc == 5 and r[6:8] == b"\x00\x00" and r[:2] == b"\x12\x34"
              and r[12:] == q(name)[12:], r)
    else:
        check("dns %s: the board" % name, rc == 0 and r.endswith(bytes([192, 168, 4, 1])), r)

# -- HTTP: GET is open, every write needs a signed-in crew member
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
import lvweb  # noqa: E402


class Req:
    def __init__(self, method, path, q=None, body=b"", tok=None):
        self.method, self.path, self.q, self.body = method, path, q or {}, body
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


class Phone:
    def who(self, req):
        return 3 if req.header("x-crew-token") == "tok" else None


class Web:
    def get_phone(self):
        return Phone()


def http(req):
    w = Wr()
    asyncio.run(lvota.api(Web(), req, w))
    head, _, body = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(body)



class Web2(Web):
    ship = None


asyncio.run(srv.route(Req("GET", "/api/state"), Wr()))
check("main.py route: the game's own requests go on", FakeServer.routed == ["/api/state"])
w = Wr()
srv_web = Web2()
g2 = {"lvship": FakeShip, "asyncio": None}
exec(main_src, g2)
srv2 = FakeServer()
srv2.get_phone = srv_web.get_phone
g2["ota_hooks"](FakeLvweb, srv2)
FakeServer.routed = []
asyncio.run(srv2.route(Req("GET", "/api/ota"), w))
check("main.py route: /api/ota to lvota, dropped after", FakeServer.routed == [] and b" 200 " in w.out[:20]
      and "lvota" not in sys.modules, w.out[:40])
import lvota  # noqa: E402,F811
lvota.KEYS = {FX["kid"]: binascii.unhexlify(FX["pub"])}
c, j = http(Req("GET", "/api/ota"))
check("GET status", c == 200 and j["v"] == V3 and j["core"] == CORE and j["chunk"] == lvota.CHUNK
      and j["last"]["result"] == "installed", j)
c, j = http(Req("POST", "/api/ota/put", {"f": "0", "n": "10", "o": "0"}, b"x"))
check("put signed out: 401", c == 401)
c, j = http(Req("POST", "/api/ota/cancel", tok="tok"))
check("cancel", c == 200)
c, j = http(Req("POST", "/api/ota/apply", tok="tok"))
check("apply, nothing staged: 409", c == 409)
c, j = http(Req("POST", "/api/ota/nope", tok="tok"))
check("unknown: 404", c == 404)
data_same("end")

print("test_ota on %s: %d checks ok (%d power cuts in the swap and the rollback)" % (
    sys.implementation.name, ok[0], cuts))
os.chdir(HERE)
rm(W)
