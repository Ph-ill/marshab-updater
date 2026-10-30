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
import hashlib

CPY = sys.implementation.name == "cpython"
HERE = os.getcwd()
sys.path.insert(0, HERE)
sys.path.insert(0, HERE + "/board")
sys.path.insert(0, HERE + "/tests")
import lvota   # noqa: E402
import lvboot  # noqa: E402
REAL_KEYS = dict(lvota.KEYS)      # the release key as shipped (the tests sign with a test key)

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
                    ("lvboot", "lvboot.mpy"), ("dots", "www/../data/crew.json"), ("abs", "/main.py"),
                    ("lv", "lv/engine.mpy"), ("lvmpy", "lv.mpy")):
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
                   ("path_lv", "file"), ("path_lvmpy", "file"),
                   ("del_data", "delete"), ("huge", "file")):
    r = send_env(FX["env"][name])
    check("refused " + name, r[0] == 403 and want in r[1]["err"], r)
    check("refused %s: nothing staged" % name, lvota.manifest() is None and lvota.status()["staged"] is None)
# review #3 m4: nothing that would shadow the frozen core (lv/, lv.py, lv.mpy); lvx/ (the
# core's own one-module override) and names that only start with lv are fine
for p, bad in (("lv/engine.mpy", True), ("lv", True), ("lv.py", True), ("lv.mpy", True),
               ("lvx/engine.mpy", False), ("lvota.mpy", False), ("lvweb.mpy", False), ("www/lv/x", False)):
    check("bad_path %r: %s" % (p, bad), lvota.bad_path(p) is bad)
# ... but a release may delete them (every partial release deletes lv and lvx: a shadow
# left by a USB install of the stock layout), and still nothing protected
for p, bad in (("lv", False), ("lvx", False), ("lv.py", False), ("lv.mpy", False), ("data", True),
               ("ota", True), ("boot.py", True), ("lvboot.mpy", True)):
    check("bad_path %r as a delete: %s" % (p, bad), lvota.bad_path(p, True) is bad)
r = lvota.put({"f": "0", "n": "20", "o": "0"}, b'{"m": "x", "sig": "!!"')
r = lvota.put({"f": "0", "n": "20", "o": "22"}, b"x")
check("envelope: past its size", r[0] == 400 or r[0] == 409, r)
check("files before the envelope", lvota.put({"f": "1", "o": "0"}, b"x")[0] == 409)
check("apply with nothing staged", lvota.apply()[0] == 409)
lvota.rmtree(lvota.NEW)
ship_runs(OLD, "after refusals")
data_same("after refusals")

# The split duel payload has 43 files; retain an explicit bounded file count.
for count, accepted in ((43, True), (48, True), (49, False)):
    m = manifest("0.2.1-lv-test", dict(("lvpart%d.mpy" % i, b"x") for i in range(count)))
    why = lvota.check_manifest(m)
    check("split payload: %d files accepted %s" % (count, accepted),
          why is None if accepted else why == "bad file list", why)

# -- 0.2.1 in pieces: a wrong offset says where to carry on; a bad file is thrown away
V1 = "0.2.1-lv-test"
raw = json.dumps(FX["env"][V1]).encode()
n = str(len(raw))
check("env piece 1", lvota.put({"f": "0", "n": n, "o": "0"}, raw[:300])[0] == 200)
r = lvota.put({"f": "0", "n": n, "o": str(len(raw) - 50)}, raw[-50:])
check("env: wrong offset -> 409 have", r[0] == 409 and r[1]["have"] == 300, r)
r = send_env(FX["env"][V1])     # starts again from 0
check("env accepted", r[0] == 200 and r[1]["v"] == V1, r)
check("src: main unless ship.json says", lvota.status()["src"] is None)
with open(lvota.SHIP, "rb") as f:
    ship0 = f.read()
for val, want in (("ota-phonetest", "ota-phonetest"), ("feature/x.y_2", "feature/x.y_2"),
                  ("", None), ("../main", None), ("a..b", None), ("/main", None), ("-x", None),
                  ("https://example.invalid/x", None), ("a b", None), ("x" * 65, None), (7, None),
                  (["main"], None)):
    with open(lvota.SHIP, "w") as f:
        json.dump({"ship": 2, "ota_src": val}, f)
    check("src %r -> %r" % (val, want), lvota.src() == want and lvota.status()["src"] == want)
with open(lvota.SHIP, "w") as f:
    f.write("{broken")
check("src: broken ship.json -> main", lvota.src() is None)
with open(lvota.SHIP, "wb") as f:
    f.write(ship0)
st = lvota.status()
check("status: staged, nothing yet", st["staged"]["v"] == V1 and sum(st["staged"]["have"]) == 0, st)
# review R2 (0.3.0): the phone carries on only with the very envelope it would send now
check("status: staged h = sha256 of the envelope's bytes", st["staged"]["h"] == binascii.hexlify(hashlib.sha256(raw).digest()).decode(), st["staged"].get("h"))
_eh = read(lvota.NEW + "/eh")
rm(lvota.NEW + "/eh")
check("status: staged by 0.2.7 (no eh): h is None", lvota.status()["staged"]["h"] is None)
write(lvota.NEW + "/eh", _eh)
check("status: h back", lvota.status()["staged"]["h"] == binascii.hexlify(hashlib.sha256(raw).digest()).decode())
# 0.3.0 review R1 m1: the envelope's check runs out of heap -> 503 (the phone's otaPut
# tries again after a pause), not 403 "unreadable update", and nothing is thrown away: the
# envelope stays on flash, and its last piece sent again (off == have == n) checks it.
import lvotap  # noqa: E402


def _oom(*a):
    raise MemoryError("memory allocation failed")


for _where in ("_verify", "_env_m"):
    _mod = lvotap if _where == "_verify" else lvota
    _real = getattr(_mod, _where)
    setattr(_mod, _where, _oom)
    try:
        r = send_env(FX["env"][V1])
    finally:
        setattr(_mod, _where, _real)
    check("R1 m1: envelope check out of heap (%s) -> 503" % _where, r[0] == 503 and r[1]["have"] is None, r)
    check("R1 m1: ... envelope kept, not ok (%s)" % _where, read(lvota.NEW + "/env") == raw
          and read(lvota.NEW + "/ok") is None and lvota.status()["staged"] is None)
    _o = (len(raw) - 1) // 300 * 300
    r = lvota.put({"f": "0", "n": n, "o": str(_o)}, raw[_o:])
    check("R1 m1: its last piece again checks it (%s)" % _where, r[0] == 200 and r[1]["v"] == V1, r)
    check("R1 m1: ... staged as before (%s)" % _where, lvota.status()["staged"]["h"] ==
          binascii.hexlify(hashlib.sha256(raw).digest()).decode())
# 0.3.0 fix review FR1 m2: the envelope kept for lvboot ({"m": ...}) is written to env.new
# and swapped in only after ok. A memory error (or a power cut) after it is written but
# before ok leaves the whole envelope as it came: the phone's 503 retry of the last piece
# checks it again (before: env was already the shorter rewrite, the phone got 409 have=<its
# size>, appended from there, and a good release ended in 403 "unreadable update").
import json as _json  # noqa: E402


class _DumpThenOom:
    loads, load = staticmethod(_json.loads), staticmethod(_json.load)

    @staticmethod
    def dump(o, f):
        _json.dump(o, f)
        raise MemoryError("memory allocation failed")


lvota.rmtree(lvota.NEW)
lvota.json = _DumpThenOom
try:
    r = send_env(FX["env"][V1])
finally:
    lvota.json = _json
check("FR1 m2: out of heap after env.new is written -> 503", r[0] == 503 and r[1]["have"] is None, r)
check("FR1 m2: ... the envelope still whole, not ok", read(lvota.NEW + "/env") == raw
      and read(lvota.NEW + "/ok") is None and lvota.status()["staged"] is None)
_o = (len(raw) - 1) // 300 * 300
r = lvota.put({"f": "0", "n": n, "o": str(_o)}, raw[_o:])
check("FR1 m2: its last piece again checks it -> 200", r[0] == 200 and r[1]["v"] == V1, r)
check("FR1 m2: ... env is the kept {m} form, no env.new left", read(lvota.NEW + "/env.new") is None
      and _json.loads(read(lvota.NEW + "/env"))["m"] == FX["env"][V1]["m"]
      and "sig" not in _json.loads(read(lvota.NEW + "/env")))
# cut between ok and the rename: env is still the whole envelope, which reads the same way
# (manifest(), lvboot's prepare(): json.load(f)["m"]) and the phone carries on with the files


class _RenameOom:
    def __getattr__(self, k):
        return getattr(os, k)

    @staticmethod
    def rename(a, b):
        if a.endswith("env.new"):
            raise MemoryError("memory allocation failed")
        return os.rename(a, b)


lvota.rmtree(lvota.NEW)
lvota.os = _RenameOom()
try:
    r = send_env(FX["env"][V1])
finally:
    lvota.os = os
check("FR1 m2: cut after ok, before the rename -> 503", r[0] == 503, r)
check("FR1 m2: ... staged all the same (ok, whole env)", read(lvota.NEW + "/ok") is not None
      and read(lvota.NEW + "/env") == raw and lvota.manifest()["version"] == V1
      and lvota.status()["staged"]["h"] == binascii.hexlify(hashlib.sha256(raw).digest()).decode())
r = lvota.put({"f": "0", "n": n, "o": str(_o)}, raw[_o:])
check("FR1 m2: ... the phone's retry is told it's all there (409 have=n)", r[0] == 409
      and r[1]["have"] == len(raw), r)
lvota.rmtree(lvota.NEW)
check("FR1 m2: staged afresh", send_env(FX["env"][V1])[0] == 200 and read(lvota.NEW + "/env.new") is None)
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
# 0.3.0: the last piece's bytes land but its check never runs (no heap for the hash, the
# connection dropped): status shows it one byte short, and sending that piece again (or any
# piece of it) checks it then, instead of a 409 that ends the phone's loop with the file
# never marked done (apply would refuse forever, and "Install" again would skip the file)
import lvotap  # noqa: E402
_sf = lvotap.sha_file


def _no_heap(p):
    raise MemoryError("memory allocation failed")


_page = FILES[V1]["www/app.html.gz"]
for o in (0, 1024):
    lvota.put({"f": str(idx), "o": str(o)}, _page[o:o + 1024])
lvotap.sha_file = _no_heap
try:
    lvota.put({"f": str(idx), "o": "2048"}, good_tail)
    died = False
except MemoryError:
    died = True
lvotap.sha_file = _sf
check("file: its check died after the write", died)
st = lvota.status()
check("status: written but unchecked shows one byte short", st["staged"]["have"][idx - 1] == size - 1, st["staged"]["have"][idx - 1])
r = lvota.put({"f": str(idx), "o": "2048"}, good_tail)
check("file: the same piece again checks it -> done", r[0] == 200 and r[1].get("done") and r[1]["have"] == size, r)
check("status: now all there", lvota.status()["staged"]["have"][idx - 1] == size)
r = send_files(V1)
check("file: sent again", r[0] == 200, r)
r = lvota.put({"f": str(idx), "o": "0"}, b"again")
check("file: already done", r[0] == 200 and r[1].get("done"), r)
ship_runs(OLD, "staged, not applied")
r = lvota.apply()
check("apply", r[0] == 200 and r[1]["v"] == V1, r)
check("state ready", lvota.read_json(lvota.STATE)["phase"] == "ready")
# 0.3.0 review R3 M1: between apply() and the restart, lvboot will read ota/new/env as it is
# then; a short envelope sent in that window (never checked: it isn't complete) used to
# replace it, and lvboot swapped out its delete list (data/). Now every envelope piece, a
# whole one too, and a cancel are refused while the state is ready (or swap).
_env0, _ok0, _ix0 = read(lvota.NEW + "/env"), read(lvota.NEW + "/ok"), read(lvota.NEW + "/ix")
_evil = b'{"m":"{\\"files\\":[],\\"delete\\":[\\"data\\"]}"}'
for _ph in ("ready", "swap"):
    _st = lvota.read_json(lvota.STATE)
    lvota.write_json(lvota.STATE, dict(_st, phase=_ph))
    r = lvota.put({"f": "0", "n": str(len(_evil) + 100), "o": "0"}, _evil)
    check("R3 M1: a partial envelope after apply (%s) -> 409" % _ph, r[0] == 409 and r[1]["have"] is None, r)
    r = lvota.put({"f": "0", "n": str(len(_evil)), "o": "0"}, _evil)
    check("R3 M1: a whole one too (%s) -> 409" % _ph, r[0] == 409, r)
    r = lvota.put({"f": "0", "n": str(len(_env0)), "o": "100"}, _env0[100:200])
    check("R3 M1: a later piece too (%s) -> 409" % _ph, r[0] == 409, r)
    check("R3 M1: the staged update untouched (%s)" % _ph, read(lvota.NEW + "/env") == _env0
          and read(lvota.NEW + "/ok") == _ok0 and read(lvota.NEW + "/ix") == _ix0)
    lvota.write_json(lvota.STATE, _st)
check("R3 M1: installing() while ready", lvota.installing() is True)
ship_runs(OLD, "applied, before the restart")

# -- the restart: boot.py swaps it in, on trial
check("boot: swap -> trial", lvboot.run() == "trial")
s = lvota.read_json(lvota.STATE)
check("trial, boot 1", s["phase"] == "trial" and s["boots"] == 1 and s["prev"] == "0.2.0-lv-test", s)
check("R3 M1: lvboot swapped the signed set (nothing went to ota/old/data)", read("ota/old/data") is None
      and read("ota/old/data/log.bin") is None and "config.py" in s.get("gone", ["config.py"]), s)
check("R3 M1: on trial, no longer installing (but busy: FR1 m5)", lvota.installing() is False
      and lvota.phase() == "trial")
ship_runs(FILES[V1], "0.2.1 running")
check("config.py deleted (kept in ota/old)", read("config.py") is None and read("ota/old/config.py") == OLD["config.py"])
check("installed() is 0.2.1", lvota.installed()["v"] == V1)
data_same("0.2.1 on trial")
# Review #3 M2 (rv3/good_cut.py): a power cut anywhere inside good() (keeping the update)
# never leaves a mix: the next boot is either still on trial with every old copy there
# (lvboot can still put it all back) or the update is kept and lvboot has nothing to do.
# What's left of ota/old/ is cleared when the next update is staged, never by lvboot.


def snap(d="."):
    out = {}
    for n in os.listdir(d):
        p = n if d == "." else d + "/" + n
        if os.stat(p)[0] & 0x4000:
            out[p] = None
            out.update(snap(p))
        else:
            out[p] = read(p)
    return out


def unsnap(t):
    for n in os.listdir("."):
        rm(n)
    for p in sorted(t):
        if t[p] is None:
            lvota._mkdirs(p)
        else:
            write(p, t[p])


class CutOs:
    # lvota's os with the power going at the k-th change on the flash
    def __init__(self, k):
        self.left = k

    def __getattr__(self, n):
        f = getattr(os, n)
        if n not in ("remove", "rmdir", "rename"):
            return f

        def g(*a):
            if self.left == 0:
                raise Cut()
            self.left -= 1
            return f(*a)
        return g


class Cut(BaseException):     # like pulling the plug: nothing in lvota or lvboot catches it
    pass


before = snap()
olds = sorted(p for p in before if p.startswith("ota/old/") and before[p] is not None)
check("M2: a trial with old copies to keep", len(olds) >= 2, olds)
write(lvota.STATE + ".tmp", read(lvota.STATE))         # a stale one of lvboot's, as a cut _save leaves
before = snap()
kept = trial = 0
for k in range(80):
    unsnap(before)
    lvota.os = CutOs(k)
    try:
        lvota.good()
        hit = False
    except Cut:
        hit = True
    lvota.os = os
    r = lvboot.run()
    tag = "M2 cut %d in good()" % k
    if r == "trial":
        trial += 1
        check(tag + ": still on trial, every old copy there", all(read(p) == before[p] for p in olds))
        ship_runs(FILES[V1], tag)
        check(tag + ": kept next time", lvota.good() is True and read(lvota.STATE) is None)
    else:
        kept += 1
        check(tag + ": kept, nothing for lvboot", r is None and lvota.read_json(lvota.LAST)["result"] == "installed")
        ship_runs(FILES[V1], tag)
    data_same(tag)
    check(tag + ": no state left", read(lvota.STATE) is None and read(lvota.STATE + ".tmp") is None)
    if not hit:
        break
check("M2: cut points tried both sides of keeping", trial >= 1 and kept >= 3 and not hit, (trial, kept, k))
# the last cut left ota/old/ part-deleted: staging the next update clears it (no state
# file: nothing could need it), and no boot ever looks at it
unsnap(before)
# LAST, .tmp, the state file, what's left of ota/new/ (env, ok, eh and the directory), then
# half the old copies (counted, not assumed: 0.3.0 added ota/new/eh)
news = [p for p in before if p.startswith(lvota.NEW + "/")]
lvota.os = CutOs(3 + len(news) + 1 + max(1, len(olds) // 2))
try:
    lvota.good()
except Cut:
    pass
lvota.os = os
left = [p for p in olds if read(p) is not None]
check("M2: cut part-way through ota/old/", 0 < len(left) < len(olds), left)
check("M2: ... the next boot does nothing", lvboot.run() is None)
ship_runs(FILES[V1], "M2: leftovers")
check("M2: staging the next update clears ota/old/", send_env(FX["env"]["0.2.2-lv-test"])[0] == 200
      and not [p for p in olds if read(p) is not None])
lvota.rmtree(lvota.NEW)
# 0.3.0 fix review FR1 m5 / FR3 f3: while on trial nothing new is staged or applied (lvboot
# keeps ota/old/ for this trial's rollback; a second update swapped in over it would roll
# back to a mix of three sets): every envelope piece, every file piece and apply answer 409
# "busy, try again in a couple of minutes", and ota/old/ and ota/new/ stay as they are.
unsnap(before)
rm(lvota.STATE + ".tmp")
check("f3: on trial", lvota.phase() == "trial" and lvota.installing() is False)
_news = dict((p, read(p)) for p in before if p.startswith(lvota.NEW + "/"))
_e2 = json.dumps(FX["env"]["0.2.2-lv-test"]).encode()
r = lvota.put({"f": "0", "n": str(len(_e2)), "o": "0"}, _e2[:300])
check("f3: a second update's envelope while on trial -> 409 busy", r[0] == 409 and r[1]["have"] is None
      and r[1]["err"] == lvota.BUSY == "busy, try again in a couple of minutes", r)
r = lvota.put({"f": "0", "n": str(len(_e2)), "o": "0"}, _e2)
check("f3: ... a whole one too", r[0] == 409 and r[1]["err"] == lvota.BUSY, r)
r = lvota.put({"f": "0", "n": str(len(_e2)), "o": "300"}, _e2[300:600])
check("f3: ... a later piece too", r[0] == 409 and r[1]["err"] == lvota.BUSY, r)
r = lvota.put({"f": "1", "o": "0"}, b"x" * 10)
check("f3: ... a file piece too", r[0] == 409 and r[1]["have"] is None and r[1]["err"] == lvota.BUSY, r)
r = lvota.apply()
check("f3: ... and apply", r[0] == 409 and r[1]["err"] == lvota.BUSY, r)
check("f3: on trial, ota/old/ untouched", all(read(p) == before[p] for p in olds))
check("f3: on trial, ota/new/ untouched", all(read(p) == b for p, b in _news.items())
      and lvota.phase() == "trial")
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
# soft resets (Ctrl-D, mpremote, bench.py, the updater page over USB) on trial: the chip
# has been up a while, so they don't count and arm no deadline, however many there are
armed = []
real_arm = lvboot.arm
lvboot.arm = lambda ms=lvboot.TRIAL_MS: armed.append(ms)
lvboot.uptime = lambda: 45000
for i in range(5):
    check("soft reset %d on trial: not counted" % i, lvboot.run() == "soft"
          and lvota.read_json(lvota.STATE)["boots"] == 1 and lvota.read_json(lvota.STATE)["phase"] == "trial")
check("soft resets: no deadline armed", armed == [], armed)
ship_runs(FILES[V2], "0.2.2 on trial after soft resets")
lvboot.uptime = lambda: lvboot.SOFT_MS + 1
check("just past SOFT_MS: soft", lvboot.run() == "soft" and lvota.read_json(lvota.STATE)["boots"] == 1)
lvboot.uptime = lambda: 25                    # a real start: ~25 ms after power-up
check("real boot after soft resets: counted", lvboot.run() == "trial"
      and lvota.read_json(lvota.STATE)["boots"] == 2 and armed == [lvboot.TRIAL_MS], armed)
lvboot.uptime = lambda: 45000
check("soft reset at boot 2: not counted", lvboot.run() == "soft" and lvota.read_json(lvota.STATE)["boots"] == 2)
lvboot.uptime = lambda: 25
check("2: boot 3 (real) -> rolled back", lvboot.run() == "undo")
ship_runs(FILES[V1], "rolled back to 0.2.1 (real boots only)")
check("soft test: last", lvota.read_json(lvota.LAST)["result"] == "rolled back"
      and lvota.read_json(lvota.LAST)["boots"] == 3)
data_same("after soft resets and a rollback")
# the swap itself on a soft reset (apply, then Ctrl-D before its own restart): it swaps
# in and that boot counts, with a deadline, as any start of a trial does
stage(V2)
lvboot.uptime = lambda: 45000
armed[:] = []
check("swap on a soft reset: counted", lvboot.run() == "trial"
      and lvota.read_json(lvota.STATE)["boots"] == 1 and armed == [lvboot.TRIAL_MS], armed)
check("then soft: not counted", lvboot.run() == "soft" and lvota.read_json(lvota.STATE)["boots"] == 1)
lvboot.uptime = lambda: 25
check("boot 2 real", lvboot.run() == "trial" and lvota.read_json(lvota.STATE)["boots"] == 2)
lvboot.arm = real_arm
check("2: boot 2", True)
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
    ship = type("RouteShip", (), {"ledtest": None})()

    async def route(self, req, w):
        FakeServer.routed.append(req.path)


class FakeShip:
    @staticmethod
    def drop(name):
        sys.modules.pop(name, None)

    # (main.py's state_busy is the ticks_ms a stream began: review 3 MAJOR-1)
    @staticmethod
    def ticks_ms():
        import time as t
        return t.ticks_ms() if hasattr(t, "ticks_ms") else int(t.monotonic() * 1000)

    @staticmethod
    def ticks_diff(a, b):
        return a - b


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
# R1 m5: lvota.api's put went to lvotap (dead on the board); now only safe mode's fallback
# comes here, when lvotap.py won't load (R1 M2): an answer, not silence
c, j = http(Req("POST", "/api/ota/put", {"f": "0", "n": "10", "o": "0"}, b"x", tok="tok"))
check("R1 m5 / FR1 m3: put through lvota.api -> 500 (not retried as busy), says why", c == 500
      and j["err"] == lvota.DAMAGED and "damaged" in j["err"] and j["have"] is None, j)
# R3 M1: cancel is refused between apply and the restart too
lvota.write_json(lvota.STATE, {"phase": "ready", "v": "9.9.9"})
c, j = http(Req("POST", "/api/ota/cancel", tok="tok"))
check("R3 M1: cancel while ready -> 409", c == 409, (c, j))
rm(lvota.STATE)

# -- 0.3.0 review R1 M2: before a trial is kept, the update path itself is checked
# (board/lvotak.py): lvotaq, lvotap, lvota, lvsig import and lvsig checks RFC 8032's test 1.
import lvotak  # noqa: E402
FAULT, FAULT_LAST = "data/fault.json", "data/fault.last.json"


def trial_state():
    lvota.write_json(lvota.STATE, {"phase": "trial", "v": V3, "prev": V2, "boots": 1,
                                   "put": [], "had": [], "gone": []})


def run(c):
    return asyncio.run(c)


# FR1 M1 / FR3 i1: lvota.KEYS must hold the release key (lvotak.KIDS) under its real id
_test_keys = dict(lvota.KEYS)
check("FR1 M1: the shipped KEYS pin 2111b2e9", list(REAL_KEYS) == ["2111b2e9"] and lvotak.KIDS == ("2111b2e9",))
check("FR1 M1: keys_ok(the shipped KEYS)", lvotak.keys_ok(REAL_KEYS) is True)
check("FR1 M1: keys_ok(the shipped + a test key)", lvotak.keys_ok(dict(REAL_KEYS, **_test_keys)) is True)
_rk = REAL_KEYS["2111b2e9"]
for _why, _k in (("empty", {}), ("not a dict", [("2111b2e9", _rk)]), ("None", None),
                 ("only a test key", _test_keys),
                 ("the id on another key", {"2111b2e9": binascii.unhexlify("ab" * 32)}),
                 ("a 31-byte key", {"2111b2e9": _rk[:31]}),
                 ("hex text, not bytes", {"2111b2e9": binascii.hexlify(_rk).decode()}),
                 ("a bad extra key", dict(REAL_KEYS, x=b"short"))):
    check("FR1 M1: keys_ok refuses %s" % _why, lvotak.keys_ok(_k) is False)
lvota.KEYS = _test_keys
sys.modules.pop("lvsig", None)
trial_state()
try:
    got = run(lvotak.keep(None, FAULT, FAULT_LAST))
except Exception as e:
    got = type(e).__name__
check("FR1 M1: KEYS without the release key: the trial is not kept", got == "ValueError"
      and lvota.read_json(lvota.STATE)["phase"] == "trial", got)
rm(lvota.STATE)
lvota.KEYS = dict(REAL_KEYS, **_test_keys)
sys.modules.pop("lvsig", None)
_had = [m for m in ("lvotaq", "lvotap", "lvsig", "lvsafe") if m in sys.modules]
check("R1 M2: the update path checks out", run(lvotak.check()) is True)
check("R1 M2: ... and leaves none of it loaded (lvsafe too)", not [m for m in ("lvotaq", "lvotap", "lvsig", "lvsafe")
                                                                   if m in sys.modules and m not in _had])
check("FR1 m4: lvsafe is part of it", [x for x in lvotak.NEEDS if x[0] == "lvsafe"])
# 0.3.0 review 2 m4: everything the check imports goes again (lvstateapi brings lvphone and
# lv.engine), and a ship without lv (no game) still keeps an update
for _m in ("lvphone", "lvphoneapi", "lvphoneinit", "lvstateapi", "lv.engine", "lvlight", "lvsetup", "lvcheck"):
    sys.modules.pop(_m, None)
_before = set(sys.modules)
check("review2 m4: the check passes", run(lvotak.check()) is True)
_left = sorted(set(sys.modules) - _before)
check("review2 m4: ... and leaves nothing it imported loaded (lvphone, lv.engine too)", not _left, _left)
_real_game = lvotak.game
check("review2 m4: this test ship has lv", _real_game() is True)
lvotak.game = lambda: False
try:
    os.mkdir(HERE + "/build/ota-nolv-" + sys.implementation.name)
except OSError:
    pass
_nolv = HERE + "/build/ota-nolv-" + sys.implementation.name
for _m in lvotak.GAME:
    with open(_nolv + "/" + _m + ".py", "w") as f:
        f.write("import lv_missing_core\n")
    sys.modules.pop(_m, None)
sys.path.insert(0, _nolv)
if CPY:
    import importlib
    importlib.invalidate_caches()
trial_state()
try:
    got = run(lvotak.keep(None, FAULT, FAULT_LAST))
except Exception as e:
    got = type(e).__name__
finally:
    sys.path.remove(_nolv)
    for _m in lvotak.GAME:
        os.remove(_nolv + "/" + _m + ".py")
        sys.modules.pop(_m, None)
    lvotak.game = _real_game
_st = lvota.read_json(lvota.STATE)
check("review2 m4: no lv: the game's modules skipped, the update kept", got is True
      and (_st or {}).get("phase") != "trial", (got, _st))
if _st is not None:
    rm(lvota.STATE)
check("R1 M2: lvsig refuses the known signature tampered", lvotak.sig_ok() is True)
# a module of the chain shadowed or broken (a stale .py ahead of the .mpy): not kept
SH = HERE + "/build/ota-shadow-" + sys.implementation.name
for name, src, want in (("lvsig", "def verify(a, b, c):\n    return True\n", "false"),
                        ("lvotaq", "X = 1\n", "ImportError"),
                        ("lvotap", "raise ImportError('damaged')\n", "ImportError"),
                        ("lvsig", "syntax error here(\n", "SyntaxError"),
                        # FR1 m4: a damaged safe mode is not kept either
                        ("lvsafe", "raise ImportError('damaged')\n", "ImportError"),
                        ("lvsafe", "def check(t):\n    pass\n", "ImportError"),
                        ("lvsafe", "x = (\n", "SyntaxError")):
    try:
        os.mkdir(SH)
    except OSError:
        pass
    with open(SH + "/" + name + ".py", "w") as f:
        f.write(src)
    sys.path.insert(0, SH)
    sys.modules.pop(name, None)
    if CPY:
        import importlib
        importlib.invalidate_caches()
    trial_state()
    write(FAULT, b'{"n": 1, "why": "x"}')
    try:
        got = run(lvotak.keep(None, FAULT, FAULT_LAST))
    except Exception as e:
        got = type(e).__name__
    finally:
        sys.path.remove(SH)
        os.remove(SH + "/" + name + ".py")
        sys.modules.pop(name, None)
    check("R1 M2: %s broken (%s): trial not kept" % (name, want), got is False if want == "false"
          else got in (want, "ImportError", "SyntaxError"), got)
    check("R1 M2: %s broken: still on trial, the fault count kept" % name,
          lvota.read_json(lvota.STATE)["phase"] == "trial" and read(FAULT) is not None)
rm(SH)
# main.py's kept(): False (tried again in 5 s) on any failure, never raises
kept_src = open(HERE + "/board/main.py").read()
kept_src = kept_src[kept_src.index("async def kept"):kept_src.index("\ndef restart")]
gk = {"lvship": FakeShip, "FAULT": FAULT, "FAULT_LAST": FAULT_LAST}
exec(kept_src, gk)
lvotak.check, _chk = _oom, lvotak.check
sys.modules["lvotak"] = lvotak
check("R1 M2: main.py kept(): a MemoryError -> False, still on trial", run(gk["kept"](None)) is False
      and lvota.read_json(lvota.STATE)["phase"] == "trial")
import lvotak  # noqa: E402,F811
lvotak.check = _chk
check("R1 M2: main.py kept(): the path works -> kept", run(gk["kept"](None)) is True
      and read(lvota.STATE) is None and lvota.read_json(lvota.LAST)["result"] == "installed")
check("R1 M2: ... the fault count starts clean", read(FAULT) is None and read(FAULT_LAST) is not None)
check("R1 M2: kept() dropped lvotak", "lvotak" not in sys.modules)
rm(FAULT_LAST)
data_same("end")

print("test_ota on %s: %d checks ok (%d power cuts in the swap and the rollback)" % (
    sys.implementation.name, ok[0], cuts))
os.chdir(HERE)
rm(W)
