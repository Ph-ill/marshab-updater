# Over-the-air game updates, the ship's side. The ship has no internet: a phone that can
# reach GitHub fetches a signed release (web/ota.js) and relays it here over the hotspot.
# main.py sends /api/ota* here; this module is imported for one request and dropped again
# (everything it needs between requests is on flash, under ota/), so a ship nobody is
# updating never carries it.
#
#   GET  /api/ota                 {ota, v, ch, core, chunk, free, staged, last, src}
#   POST /api/ota/put?f=0&n=N&o=O the signed envelope, in pieces of at most `chunk` bytes
#   POST /api/ota/put?f=I&o=O     file I of the manifest (1-based), raw bytes from offset O
#   POST /api/ota/apply           everything staged and checked: restart into it
#   POST /api/ota/cancel          forget what is staged
# Writes need a signed-in crew member (X-Crew-Token). A piece at the wrong offset gets
# 409 {have}: the phone carries on from there, so a dropped connection costs one piece.
#
# The envelope is {"m": manifest JSON text, "sig": base64, "kid": key id}. The signature
# (Ed25519, lvsig.py) is over TAG + sha256(m) and must come from a key in KEYS; the private
# key never leaves the release machine (game/tools/ota/sign_release.py). The manifest:
#   {"schema": 1, "project": "LongVoyage", "version", "channel", "core",
#    "files": [[path, size, sha256 hex], ...], "delete": [path, ...]}
# Refused: a bad or unknown signature, another frozen core, a version that isn't newer
# than the installed one (no downgrades, no replays), a path under data/ or ota/, boot.py
# or lvboot (the rollback code is never replaced over the air), "..", too little flash.
# Each file is checked against its sha256 as soon as its last byte lands.
#
# Staging is ota/new/: env (the envelope), ok (written once the signature checked out),
# f<I> while file I arrives, f<I>.ok once it matches. apply writes ota/state.json
# {"phase": "ready"} and restarts; boot.py hands that to lvboot.py, which swaps the files
# in (the old ones go to ota/old/), runs the new set on trial and puts the old one back if
# it doesn't come up twice. main.py calls good() once the game has been up a while.
import os
import json

try:
    import hashlib
except ImportError:  # pragma: no cover
    import uhashlib as hashlib
from binascii import a2b_base64, unhexlify, hexlify

OTA = "ota"
NEW = OTA + "/new"
OLD = OTA + "/old"
STATE = OTA + "/state.json"
LAST = OTA + "/last.json"
TAG = b"LV-OTA-1\n"
CHUNK = 1024              # main.py sets lvweb.MAX_BODY to this for the board's requests
MAX_ENV = 8192
MAX_FILE = 256 * 1024
MAX_FILES = 40
SPARE = 16 * 1024         # flash left free after staging (littlefs needs room to work)
# Ed25519 public keys allowed to sign an update: key id (first 8 hex of sha256(key)) -> key.
KEYS = {"2111b2e9": unhexlify("0478d983c1a756c32acf10215359e6f0361ea4800ede2b50031256bcf0f4b58f")}
reset = None              # tests: called instead of machine.reset()
# Where the phone looks for releases: a branch of the public repo, main unless this ship's
# /data/ship.json says "ota_src": "<branch>" (a test ship reading a test branch, so a test
# release published there reaches it and no other ship). Only a branch name, never a URL:
# the page builds the address from it, so a ship can't point a phone anywhere else, and
# whatever is fetched still has to carry a signature from KEYS.
SHIP = "data/ship.json"
SRC_OK = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/"


def src():
    """The branch the phone fetches releases from: ship.json "ota_src", or None (main)."""
    b = (read_json(SHIP) or {}).get("ota_src")
    if not isinstance(b, str) or not 0 < len(b) <= 64 or ".." in b or b[0] in "/-." \
            or any(c not in SRC_OK for c in b):
        return None
    return b


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _size(p):
    try:
        return os.stat(p)[6]
    except OSError:
        return -1


def _mkdirs(p):
    a = ""
    for part in p.split("/"):
        a = a + "/" + part if a else part
        try:
            os.mkdir(a)
        except OSError:
            pass


def rmtree(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rmtree(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass


def read_json(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def write_json(p, obj):
    # tmp + rename: a power cut leaves the old file or the new one, never half of either.
    with open(p + ".tmp", "w") as f:
        json.dump(obj, f)
    try:
        os.rename(p + ".tmp", p)             # littlefs: replaces it in one step
    except OSError:                          # a filesystem that won't rename over a file
        try:
            os.remove(p)
        except OSError:
            pass
        os.rename(p + ".tmp", p)


def _vparse(v):
    v = str(v or "")
    if v[:1] in ("v", "V"):
        v = v[1:]
    core, _, pre = v.partition("-")
    nums = []
    for n in core.split("."):
        d = ""
        for ch in n:
            if "0" <= ch <= "9":
                d += ch
            else:
                break
        nums.append(int(d) if d else 0)
    while len(nums) < 3:
        nums.append(0)
    return nums[:3], pre


def vcmp(a, b):
    """The updater's compareVersions (src/releases.js): 1.2.3 > 1.2.3-coex > 1.2.2."""
    (x, xp), (y, yp) = _vparse(a), _vparse(b)
    for i in range(3):
        if x[i] != y[i]:
            return x[i] - y[i]
    if xp == yp:
        return 0
    if not xp:
        return 1
    if not yp:
        return -1
    return -1 if xp < yp else 1


def installed():
    """{v, ch, core} of what the ship runs: version.json, and the frozen core it sits on."""
    j = read_json("version.json") or {}
    core = j.get("frozen")
    try:
        import lv
        c, _ = lv.firmware()
        if c is not None:
            core = c["core"]
    except Exception:
        pass
    return {"v": j.get("version"), "ch": j.get("channel"), "core": core}


def bad_path(p, delete=False):
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or len(p) > 64:
        return True
    parts = p.split("/")
    if "" in parts or "." in parts or ".." in parts:
        return True
    top = parts[0]
    # lv/ (or lv.py, lv.mpy): ahead of .frozen on sys.path, it shadows the frozen core
    # (lv.firmware "shadowed"), so the phone game and its /api/ota would never start again:
    # no update can install one (review #3 m4). Deleting one is the cure, and every partial
    # release lists "lv" in its delete (tools/build_release.py), so delete may name them.
    # (lvx/ is the core's own way to replace one lv module, and stays allowed.)
    if not delete and top in ("lv", "lv.py", "lv.mpy"):
        return True
    return top in ("data", "ota", "boot.py") or top.startswith("lvboot.") or top.startswith(".")


def check_manifest(m, inst=None, free=None):
    """None if `m` (the parsed manifest) may be installed here, else why not."""
    inst = inst or installed()
    if not isinstance(m, dict) or m.get("schema") != 1 or m.get("project") != "LongVoyage":
        return "not an update for this game"
    if inst["core"] and m.get("core") != inst["core"]:
        return "built for another ship firmware"
    if not m.get("version") or (inst["v"] and vcmp(m["version"], inst["v"]) <= 0):
        return "not newer than what the ship runs"
    files = m.get("files")
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return "bad file list"
    total = 0
    seen = []
    for f in files:
        if (not isinstance(f, list) or len(f) != 3 or bad_path(f[0]) or f[0] in seen
                or not isinstance(f[1], int) or not 0 <= f[1] <= MAX_FILE
                or not isinstance(f[2], str) or len(f[2]) != 64):
            return "bad file entry"
        seen.append(f[0])
        total += f[1]
    for p in m.get("delete") or ():
        if bad_path(p, True) or p in seen:
            return "bad delete entry"
    if free is not None and total + SPARE > free:
        return "not enough flash on the ship"
    return None


def open_envelope(raw):
    """(manifest dict, None) if the envelope's signature checks out, else (None, why)."""
    try:
        env = json.loads(raw)
        m = env["m"]
        sig = a2b_base64(env["sig"])
        key = KEYS.get(env.get("kid"))
    except Exception:
        return None, "unreadable update"
    if key is None:
        return None, "signed with a key this ship doesn't know"
    h = hashlib.sha256(m.encode() if isinstance(m, str) else m).digest()
    import lvsig
    import sys
    try:
        import lvweb
        lvsig.probe = lvweb.probe       # the heap tests' sampler (None on a board)
    except Exception:
        pass
    try:
        ok = lvsig.verify(key, TAG + h, sig)
    finally:
        try:
            del sys.modules["lvsig"]   # ~5 KB of code: only ever needed for this
        except KeyError:
            pass
    if not ok:
        return None, "the signature doesn't match"
    try:
        return json.loads(m), None
    except ValueError:
        return None, "unreadable update"


def free_flash():
    try:
        s = os.statvfs("/" if _exists("/") else ".")
        return s[0] * s[3]
    except Exception:
        return None


def manifest():
    """The staged manifest, once its signature has been checked (ota/new/ok), else None."""
    if not _exists(NEW + "/ok"):
        return None
    try:
        with open(NEW + "/env") as f:
            return json.loads(json.load(f)["m"])
    except Exception:
        return None


def status():
    st = installed()
    st["ota"] = 1
    st["chunk"] = CHUNK
    st["free"] = free_flash()
    st["last"] = read_json(LAST)
    s = read_json(STATE)
    st["phase"] = s.get("phase") if s else None
    st["src"] = src()
    m = manifest()
    if m:
        have = []
        for i in range(1, len(m["files"]) + 1):
            p = "%s/f%d" % (NEW, i)
            have.append(m["files"][i - 1][1] if _exists(p + ".ok") else max(0, _size(p)))
        st["staged"] = {"v": m["version"], "have": have,
                        "sizes": [f[1] for f in m["files"]]}
    else:
        st["staged"] = None
    return st


def _sha_file(p):
    h = hashlib.sha256()
    buf = bytearray(512)
    with open(p, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(buf[:n] if n < 512 else buf)
    return str(hexlify(h.digest()), "ascii")


def _append(p, off, body, size):
    """Write `body` at `off`, which must be the end of what's there, within `size`.
    -> None, or the (status, answer) refusing it: 409 says where to carry on from."""
    have = max(0, _size(p))
    if off != have:
        return 409, {"err": "wrong offset", "have": have}
    if off + len(body) > size:
        return 400, {"err": "more than the file's size"}
    with open(p, "ab") as f:
        f.write(body)
    return None


def put(q, body):
    """-> (status, JSON-able)."""
    try:
        f = int(q.get("f", "-1"))
        off = int(q.get("o", "-1"))
    except ValueError:
        return 400, {"err": "bad request"}
    if f == 0:
        try:
            n = int(q.get("n", "0"))
        except ValueError:
            n = 0
        if not 0 < n <= MAX_ENV:
            return 400, {"err": "bad request"}
        if off == 0:
            rmtree(NEW)
            if not _exists(STATE):
                rmtree(OLD)     # a kept update's rollback copies, if good() was cut short
            _mkdirs(NEW)
        p = NEW + "/env"
        have = _append(p, off, body, n)
        if have is not None:
            return have
        if off + len(body) < n:
            return 200, {"ok": True, "have": off + len(body)}
        with open(p) as fh:
            raw = fh.read()
        m, why = open_envelope(raw)
        if m is not None:
            why = check_manifest(m, free=free_flash())
        if why:
            rmtree(NEW)
            return 403, {"err": why}
        with open(NEW + "/env", "w") as fh:      # kept as {"m": ...} for lvboot
            json.dump({"m": json.loads(raw)["m"]}, fh)
        with open(NEW + "/ok", "w") as fh:
            fh.write(m["version"])
        return 200, {"ok": True, "v": m["version"], "files": len(m["files"])}
    m = manifest()
    if m is None:
        return 409, {"err": "send the update's signature first", "have": None}
    if not 1 <= f <= len(m["files"]):
        return 400, {"err": "bad request"}
    path, size, sha = m["files"][f - 1]
    p = "%s/f%d" % (NEW, f)
    if _exists(p + ".ok"):
        return 200, {"ok": True, "have": size, "done": True}
    have = _append(p, off, body, size)
    if have is not None:
        return have
    have = off + len(body)
    if have < size:
        return 200, {"ok": True, "have": have}
    if _sha_file(p) != sha:
        os.remove(p)
        return 400, {"err": "%s didn't match its signed checksum" % path, "have": 0}
    os.rename(p, p + ".ok")
    return 200, {"ok": True, "have": have, "done": True}


def ready():
    m = manifest()
    if m is None:
        return None
    for i in range(1, len(m["files"]) + 1):
        if not _exists("%s/f%d.ok" % (NEW, i)):
            return None
    return m


def apply():
    m = ready()
    if m is None:
        return 409, {"err": "the update isn't all here yet"}
    why = check_manifest(m)
    if why:
        return 403, {"err": why}
    if not _exists(STATE):
        rmtree(OLD)             # lvboot.swap keeps an ota/old/<path> already there: none stale
    write_json(STATE, {"phase": "ready", "v": m["version"], "prev": installed()["v"]})
    return 200, {"ok": True, "v": m["version"], "restart_ms": 1500}


async def api(web, req, w):
    """main.py routes /api/ota* here."""
    import lvweb
    p = req.path
    if req.method == "GET" and p == "/api/ota":
        return await lvweb.send_json(w, 200, status())
    if req.method != "POST":
        return await lvweb.send_json(w, 404, {"err": "no such thing"})
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    if p == "/api/ota/put":
        code, obj = put(req.q, req.body or b"")
    elif p == "/api/ota/cancel":
        rmtree(NEW)
        code, obj = 200, {"ok": True}
    elif p == "/api/ota/apply":
        code, obj = apply()
        if code == 200:
            await lvweb.send_json(w, code, obj)
            return restart(web)
    else:
        code, obj = 404, {"err": "no such thing"}
    return await lvweb.send_json(w, code, obj)


def restart(web):
    try:
        import asyncio
    except ImportError:  # pragma: no cover
        import uasyncio as asyncio

    async def later():
        await asyncio.sleep(1)
        if reset:
            return reset()
        try:
            web.ship.say("ota: restarting into the update")
        except Exception:
            pass
        import machine
        machine.reset()
    asyncio.create_task(later())


def good():
    """The new set came up and has run a while (main.py): keep it, drop the old copies.
    The state file goes first, in one step: from then on lvboot has nothing to do, so a
    power cut while ota/old/ is being deleted can't roll back to a mix of old and new files
    (review #3 M2). What's left of ota/old/ and ota/new/ is only flash in use; staging the
    next update (put f=0 o=0) and apply() clear it before lvboot could look at it. Cut
    before the state file goes: the trial carries on as if good() never ran."""
    s = read_json(STATE)
    if not s or s.get("phase") != "trial":
        return False
    write_json(LAST, {"result": "installed", "v": s.get("v"), "prev": s.get("prev"),
                      "boots": s.get("boots")})
    # lvboot's own .tmp first (a stale one from a cut lvboot._save): lvboot._load falls
    # back to it when the state file is gone, so it must not outlive it
    for p in (STATE + ".tmp", STATE):
        try:
            os.remove(p)
        except OSError:
            pass
    rmtree(NEW)
    rmtree(OLD)
    return True
