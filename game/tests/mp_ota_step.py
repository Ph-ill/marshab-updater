# The ship's side of tests/test_ota_step.py, on the lv32 MicroPython build (the frozen core,
# 32-bit pointers). Every run is one boot of a simulated ship whose flash is the folder it
# starts in, with that ship's own installed bytecode first on sys.path: nothing from the
# source tree, and no helper copy of the updater.
#
#   micropython-lv32 -X heapsize=160k mp_ota_step.py boot <cut> <good>
#       boot.py as the ship runs it (lvboot swaps, counts the trial boot or rolls back).
#       cut > 0: the power goes after that many file moves (inside lvboot's swap or undo).
#       good = 1: main.py came up and calls lvota.good(). Prints one JSON line, with the
#       MAX_FILES of the updater that then runs.
#   micropython-lv32 -X heapsize=160k mp_ota_step.py serve <max_files>
#       The ship's /api/ota routes as board/main.py sends them (GET /api/ota, the upload
#       through lvotap, cancel, apply), one JSON request per line on stdin and one JSON
#       answer [status, body] per line on stdout. lvota and lvotap are loaded per request
#       and dropped after it, as main.py does. The updater is imported fresh from flash and
#       its MAX_FILES must be <max_files>: the limit the ship really has, not one set here.
#
# Heap: the baseline is taken before any of the ship's update code is loaded, so what the
# test harness itself holds (this file, the request line) is left out; the request body is
# not (the ship holds it too). The peak is sampled inside the updater (lvweb.probe, which
# lvotap hands to lvsig: every 64 rounds of the signature check, its fullest moment) and
# around every lvboot move and state write, each time after a gc.collect(): what's really
# held there. It must stay under CAP. ota_step_page.mjs runs this with a 160 KB heap, so the
# collections happen under about the pressure a ship has. Not a full-game heap measurement:
# the game isn't running (tests/mp_sync_heap.py and phone_heap.py measure that).
import sys
import os
import gc
import json
import struct
import binascii

assert sys.implementation.name == "micropython"
assert struct.calcsize("P") == 4, "heap evidence needs the 32-bit lv32 build, not a 64-bit unix one"
CAP = 110000
MODE = sys.argv[1]
sys.path[:] = ["", ".frozen"]

gc.collect()
BASE = gc.mem_alloc()
LIVE = SIG = SIGN = 0


def sample(*args):
    global LIVE, SIG, SIGN
    gc.collect()
    live = gc.mem_alloc() - BASE
    if live > LIVE:
        LIVE = live
    if "lvsig" in sys.modules:          # inside the signature check (lvsig.probe)
        SIGN += 1
        if live > SIG:
            SIG = live


def drop(*names):
    for n in names:
        if n in sys.modules:
            del sys.modules[n]


def heap_ok():
    assert 0 < LIVE < CAP, "heap peak %d B, cap %d B" % (LIVE, CAP)


import lvweb
lvweb.probe = sample


def exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def readjson(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class PowerCut(BaseException):
    """The power goes: nothing in lvboot or boot.py may catch it (they catch Exception)."""


if MODE == "boot":
    cut, good = int(sys.argv[2]), sys.argv[3] == "1"
    moves = [0]
    pending = exists("ota/state.json") or exists("ota/state.json.tmp")
    out = {"pending": pending}
    if pending:
        import lvboot
        real_mv, real_save = lvboot._mv, lvboot._save

        def mv(a, b):
            sample()
            if cut and moves[0] == cut:
                raise PowerCut()
            moves[0] += 1
            real_mv(a, b)
            sample()

        def save(s):
            real_save(s)
            sample()

        lvboot._mv, lvboot._save = mv, save
    try:
        with open("boot.py") as f:
            code = f.read()
        exec(code, {"__name__": "boot"})
        out["cut"] = False
    except PowerCut:
        out["cut"] = True
    out["moves"] = moves[0]
    drop("lvboot")
    gc.collect()
    if good and not out["cut"]:
        import lvota
        sample()
        assert lvota.__file__ == "lvota.mpy", lvota.__file__
        out["max_files"] = lvota.MAX_FILES
        out["good"] = lvota.good()
        sample()
        drop("lvota")
    st = readjson("ota/state.json")
    out["state"] = st
    out["last"] = readjson("ota/last.json")
    out["v"] = (readjson("version.json") or {}).get("version")
    heap_ok()
    out["peak"] = LIVE
    print(json.dumps(out))
elif MODE == "serve":
    want = int(sys.argv[2])
    gc.collect()
    print(json.dumps({"ready": True}))
    while True:
        line = sys.stdin.readline()
        if not line or line.strip() == "quit":
            break
        req = json.loads(line)
        line = None
        body = binascii.unhexlify(req.get("b", "")) if req.get("b") else b""
        q = req.get("q") or {}
        p, m = req["p"], req["m"]
        req = None
        gc.collect()
        import lvota
        assert lvota.__file__ == "lvota.mpy", lvota.__file__
        assert lvota.MAX_FILES == want, "installed updater takes %d files, expected %d" % (lvota.MAX_FILES, want)
        sample()
        if m == "GET" and p == "/api/ota":
            code, obj = 200, lvota.status()
        elif m == "POST" and p == "/api/ota/put":
            lvota = None
            drop("lvota")
            import lvotap
            code, obj = lvotap.put(q, body)
            lvotap = None
            drop("lvotap", "lvota")
        elif m == "POST" and p == "/api/ota/cancel":
            if lvota.installing():
                code, obj = 409, {"err": "an update is being installed: wait for the restart"}
            else:
                lvota.rmtree(lvota.NEW)
                code, obj = 200, {"ok": True}
        elif m == "POST" and p == "/api/ota/apply":
            code, obj = lvota.apply()
        else:
            code, obj = 404, {"err": "no such thing"}
        body = None
        lvota = None
        drop("lvota", "lvotap", "lvsig")
        sample()
        print(json.dumps([code, obj]))
    heap_ok()
    print(json.dumps({"peak": LIVE, "sig": SIG, "sig_samples": SIGN}))
else:
    raise ValueError(MODE)
