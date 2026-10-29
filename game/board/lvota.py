# Over-the-air game updates, the ship's side. The ship has no internet: a phone that can
# reach GitHub fetches a signed release (web/ota.js) and relays it here over the hotspot.
# main.py sends /api/ota* here; this module is imported for one request and dropped again
# (everything it needs between requests is on flash, under ota/), so a ship nobody is
# updating never carries it. The upload itself (POST /api/ota/put) goes to lvotap.py
# (0.3.0), which loads this module only for the envelope, and not through its signature
# check: the heap's biggest moments carry ~2 KB of code instead of ~8 KB.
#
#   GET  /api/ota                 {ota, v, ch, core, chunk, free, staged, last}
#                                 staged: {v, have, sizes, h: sha256 hex of the envelope as
#                                 it arrived}; the phone resumes only on a matching h
#   POST /api/ota/put?f=0&n=N&o=O the signed envelope, in pieces of at most `chunk` bytes
#   POST /api/ota/put?f=I&o=O     file I of the manifest (1-based), raw bytes from offset O
#   POST /api/ota/apply           everything staged and checked: restart into it
#   POST /api/ota/cancel          forget what is staged
# Writes need a signed-in crew member (X-Crew-Token). A piece at the wrong offset gets
# 409 {have}: the phone carries on from there, so a dropped connection costs one piece.
# While the running set is still on trial (ota/state.json "trial"), upload and apply get
# 409 {"err": BUSY}: ota/old/ is the trial's way back (0.3.0 fix review FR1 m5 / FR3 f3).
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
# eh (the envelope's sha256), ix (each file's size, sha256 and path, one fixed-width line
# per file: lvotap.py reads a piece's line with a seek; eh and ix are written before ok),
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
from binascii import a2b_base64, unhexlify

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
# While an update is on trial (ota/state.json "trial": main.py keeps it, lvotak.py, within a
# minute or two of the restart, or lvboot rolls it back) nothing new is staged or applied.
BUSY = "busy, try again in a couple of minutes"
# The answer when the upload's own code (lvotap) won't load: not 503, which the page tries
# again as "busy", since trying again can't help (0.3.0 fix review FR1 m3). Such a set is
# never kept (lvotak.py), so it goes back to the one before by itself.
DAMAGED = ("this ship's update code is damaged, so it can't take an update now. It goes "
           "back to its last good version by itself; if it doesn't, it needs fixing over USB")
# Ed25519 public keys allowed to sign an update: key id (first 8 hex of sha256(key)) -> key.
KEYS = {"2111b2e9": unhexlify("0478d983c1a756c32acf10215359e6f0361ea4800ede2b50031256bcf0f4b58f")}
reset = None              # tests: called instead of machine.reset()


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


def _env_m(p):
    """The envelope at p -> (its manifest text, its parsed self)."""
    with open(p) as fh:
        env = json.loads(fh.read())
    return env["m"], env


def envelope_prep(p):
    """The envelope staged at path p, before its signature check (lvotap.envelope) ->
    (h, message, signature, key, None), or (h, None, None, None, why) if it can't be checked.
    The check (lvsig) is the update's biggest moment for the heap, so nothing of the envelope
    is held through it but the manifest's hash (h): envelope_done reads the file again
    afterwards, and it must hash the same (0.3.0: ~7 KB less at the peak); and this module
    is dropped meanwhile (lvotap)."""
    try:
        m, env = _env_m(p)
        sig = a2b_base64(env["sig"])
        key = KEYS.get(env.get("kid"))
        h = hashlib.sha256(m.encode()).digest()
    except MemoryError:
        raise                   # lvotap.envelope: 503, the phone tries again (not 403)
    except Exception:
        return None, None, None, None, "unreadable update"
    m = env = None
    if key is None:
        return h, None, None, None, "signed with a key this ship doesn't know"
    return h, TAG + h, sig, key, None


def envelope_done(p, h, ok, why=None):
    """After the check: the envelope at p is staged (eh, ix, ok written) if the signature
    checked out (ok), the file still hashes as it did (h) and its manifest may be installed
    here; else ota/new/ goes. -> (status, JSON-able)."""
    m = None
    if why is None and not ok:
        why = "the signature doesn't match"
    if why is None:
        try:
            ms = _env_m(p)[0]
            if hashlib.sha256(ms.encode()).digest() != h:
                why = "the update changed while it was checked"
            else:
                m = json.loads(ms)
        except MemoryError:
            raise
        except Exception:
            why = "unreadable update"
    if why is None:
        why = check_manifest(m, free=free_flash())
    if why:
        rmtree(NEW)
        return 403, {"err": why}
    # The staged envelope's hash, exactly as it came (sha256 of the bytes on flash,
    # read in 512 B pieces: no second copy of it on the heap): the phone resumes an
    # upload only if its own envelope hashes the same (web/ota.js), so a version signed
    # twice can never mix pieces of both (0.3.0, review R2).
    from lvotap import sha_file
    eh = sha_file(p)
    with open(NEW + "/eh", "w") as fh:
        fh.write(eh)
    _write_ix(m)
    # The envelope is kept as {"m": ...} (what lvboot and manifest() read: the signature
    # isn't needed once it checked out). Written beside it and swapped in only once ok is
    # there (0.3.0 fix review FR1 m2): a memory error or a power cut before ok leaves the
    # whole envelope as it came, so the phone's last piece again checks it (env_piece),
    # instead of a shorter rewritten file that the phone's next piece no longer fits
    # (409 have=<its size>, then 403 "unreadable update" for a good release). Cut between
    # ok and the rename: env is still the whole envelope, which reads the same way.
    with open(p + ".new", "w") as fh:
        json.dump({"m": ms}, fh)
    with open(NEW + "/ok", "w") as fh:
        fh.write(m["version"])
    try:
        os.rename(p + ".new", p)                # littlefs: replaces it in one step
    except OSError:                             # (kept whole: lvboot reads it all the same)
        pass
    return 200, {"ok": True, "v": m["version"], "files": len(m["files"])}


def _write_ix(m):
    from lvotap import ix_line, IX
    with open(IX + ".new", "w") as fh:
        for path, size, sha in m["files"]:
            fh.write(ix_line(path, size, sha))
    os.rename(IX + ".new", IX)


def index():
    """ota/new/ix for an update staged before 0.3.0 (lvotap.entry): from the manifest,
    once. Nothing if nothing checked is staged."""
    m = manifest()
    if m is not None:
        _write_ix(m)


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
    m = manifest()
    if m:
        have = []
        for i in range(1, len(m["files"]) + 1):
            p = "%s/f%d" % (NEW, i)
            n = m["files"][i - 1][1]
            # a file all here but never checked (lvotap.piece): one byte short, so the
            # phone sends its last piece again and that checks it
            have.append(n if _exists(p + ".ok") else max(0, min(_size(p), n - 1)))
        try:
            with open(NEW + "/eh") as f:
                eh = f.read(64)
        except OSError:
            eh = None       # staged by 0.2.7 or older: the phone starts again from nothing
        st["staged"] = {"v": m["version"], "have": have, "h": eh,
                        "sizes": [f[1] for f in m["files"]]}
    else:
        st["staged"] = None
    return st


def env_piece(q, off, body):
    """A piece of the envelope (lvotap.envelope) -> (status, JSON-able), or None once the
    whole envelope is on flash and its signature is to be checked."""
    try:
        n = int(q.get("n", "0"))
    except ValueError:
        n = 0
    if not 0 < n <= MAX_ENV:
        return 400, {"err": "bad request"}
    ph = phase()
    if ph in ("ready", "swap"):
        # apply() said ready and the restart is ~1.5 s away (or lvboot is mid-swap): lvboot
        # reads ota/new/env as it is then, so nothing may touch it (0.3.0 review R3 M1: a
        # short envelope sent in that window was never checked, and its delete list was
        # swapped out all the same).
        return 409, {"err": "an update is being installed: wait for the restart", "have": None}
    if ph == "trial":
        return 409, {"err": BUSY, "have": None}
    p = NEW + "/env"
    if off and _size(p) == n and not _exists(NEW + "/ok"):
        # all of it is here but its check never answered (no heap for it, a dropped
        # connection): the phone sends the last piece again, and that checks it (R1 m1)
        return None
    if off == 0:
        rmtree(NEW)
        if not _exists(STATE):
            rmtree(OLD)     # a kept update's rollback copies, if good() was cut short
        _mkdirs(NEW)
    from lvotap import append
    have = append(p, off, body, n)
    if have is not None:
        return have
    if off + len(body) < n:
        return 200, {"ok": True, "have": off + len(body)}
    return None


def put(q, body):
    """-> (status, JSON-able): lvotap.put (the board's route goes there directly; the tests
    and tools call this)."""
    import lvotap
    return lvotap.put(q, body)


def phase():
    """ota/state.json's phase: None (no update under way), "ready" or "swap" (apply() has
    handed the staged update to lvboot), "trial" (the new set runs, not yet kept)."""
    st = read_json(STATE)
    return st.get("phase") if isinstance(st, dict) else None


def installing():
    """apply() has handed the staged update to lvboot (ota/state.json ready or swap)."""
    return phase() in ("ready", "swap")


def ready():
    m = manifest()
    if m is None:
        return None
    for i in range(1, len(m["files"]) + 1):
        if not _exists("%s/f%d.ok" % (NEW, i)):
            return None
    return m


def apply():
    if phase() == "trial":
        # The set that runs is still on trial (lvboot keeps ota/old/ for its rollback, and
        # main.py hasn't called good() yet): a second update applied now would swap in over
        # it, keep those old copies, and a rollback of it would leave a mix of three sets
        # (0.3.0 fix review FR1 m5 / FR3 f3). The trial ends in a minute or two, kept or
        # rolled back; then the update goes in as usual.
        return 409, {"err": BUSY}
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
        # The upload is lvotap.api's (main.py and lvsafe.py send it there). Nothing comes
        # here with it now (safe mode answers DAMAGED itself when lvotap won't load); kept
        # so that a caller that does still gets that answer, not silence (0.3.0 review R1
        # M2/m5, fix review FR1 m3: not 503, which the page would retry as "busy").
        code, obj = 500, {"err": DAMAGED, "have": None}
    elif p == "/api/ota/cancel":
        if installing():
            code, obj = 409, {"err": "an update is being installed: wait for the restart"}
        else:
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
