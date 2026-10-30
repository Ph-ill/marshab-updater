# Isolated lv32 updater/boot simulation, driven by test_ota_step.py.
# Fixture metadata/paths stand in for the phone and are excluded by the baseline;
# updater, signature verifier, envelope parsing, chunks and real boot swaps are
# included. Sampled live heap is NOT a full-game/safe-mode or allocator high-water
# measurement. Each stage is a fresh interpreter: the reboot imports installed
# lvota.mpy, never changes MAX_FILES in memory, and never executes main.py/game.
import sys
import os
import gc
import json
import hashlib
import binascii
import struct

ROOT, STAGE = sys.argv[1], sys.argv[2]
assert sys.implementation.name == "micropython"
assert struct.calcsize("P") == 4, "heap evidence requires lv32, not a 64-bit unix build"
SUPPORT = ROOT + "/support"
FLASH = ROOT + "/flash"
os.chdir(FLASH)
# Avoid any source-tree .py shadow and keep installed bytecode ahead of helpers.
sys.path[:] = [FLASH, SUPPORT, ".frozen"]
META = json.load(open(ROOT + "/meta.json"))
NAME = "duel" if "duel" in STAGE or STAGE == "direct" else "step"
FOLDER = ROOT + "/" + NAME
MANIFEST = json.load(open(FOLDER + "/manifest.json"))
VERSION = MANIFEST["version"]
# The duel ships its own lvota; after it swaps in, its own limit applies.
DUEL_LIMIT = META["duel_max_files"]
EXPECTED = 40 if STAGE in ("direct", "install-step", "boot-step") else DUEL_LIMIT if STAGE == "final" else 64
COUNT = 0


def check(value, label):
    global COUNT
    assert value, label
    COUNT += 1


def readjson(path):
    with open(path) as f:
        return json.load(f)


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


# Baseline holds the test/phone side only; code loaded below belongs to the board.
gc.collect()
BASE = gc.mem_alloc()
PEAK = 0


def sample(*args):
    global PEAK
    gc.collect()
    used = gc.mem_alloc() - BASE
    if used > PEAK:
        PEAK = used


import lvweb
lvweb.probe = sample
import lvota
check(lvota.MAX_FILES == EXPECTED, "fresh import of installed lvota limit")
check(lvota.__file__ == FLASH + "/lvota.mpy", "installed bytecode, not helper/source copy")
sample()


def envelope():
    n = os.stat(FOLDER + "/env.json")[6]
    with open(FOLDER + "/env.json", "rb") as f:
        off = 0
        while off < n:
            body = f.read(300)
            result = lvota.put({"f": "0", "n": str(n), "o": str(off)}, body)
            sample()
            if result[0] != 200:
                return result
            off += len(body)
    return result


def data_ok():
    with open("data/sentinel.bin", "rb") as f:
        check(f.read() == bytes(range(256)), "data unchanged")


if STAGE == "direct":
    check(META["duel"]["count"] == len(MANIFEST["files"]) > 40, "actual duel count exceeds old cap")
    result = envelope()
    check(result[0] == 403 and result[1]["err"] == "bad file list", "old signed upload refuses actual duel payload")
    check(lvota.manifest() is None, "refusal stages nothing")
    check(lvota.installed()["v"] == "0.3.0", "refusal changes no version")
    print("direct old -> duel:", result)
elif STAGE.startswith("install-"):
    check(lvota.vcmp("0.3.1-updater", "0.3.0") > 0, "updater newer than old")
    check(lvota.vcmp("0.3.0", "0.3.1-updater") < 0, "old older than updater")
    check(lvota.vcmp("0.3.1", "0.3.1-updater") > 0, "plain duel newer than updater")
    check(lvota.vcmp("0.3.1-updater", "0.3.1") < 0, "updater older than plain duel")
    check(envelope()[0] == 200, "signed envelope accepted")
    for i, entry in enumerate(MANIFEST["files"]):
        path, size, digest = entry
        with open(FOLDER + "/" + path, "rb") as f:
            off = 0
            while off < size or off == 0:
                body = f.read(1024)
                result = lvota.put({"f": str(i + 1), "o": str(off)}, body)
                check(result[0] == 200, "file piece accepted: " + path)
                sample()
                off += len(body)
                if off >= size:
                    break
        check(result[1].get("done"), "file hash checked: " + path)
    check(lvota.apply()[0] == 200, "apply accepted")
    sample()
    check(readjson("ota/state.json")["phase"] == "ready", "ready for real boot swap")
    expected_prev = "0.3.0" if NAME == "step" else "0.3.1-updater"
    check(lvota.installed()["v"] == expected_prev, "apply does not swap before reboot")
    print("uploaded", NAME, META[NAME]["count"], "files", META[NAME]["bytes"], "bytes")
elif STAGE.startswith("boot-"):
    # Before boot-step the old bytecode is still on flash. Its import above proves
    # the swap, not a preassigned constant, installs the larger updater.
    import lvboot
    real_mv, real_save = lvboot._mv, lvboot._save

    def mv(a, b):
        result = real_mv(a, b)
        sample()
        return result

    def save(state):
        result = real_save(state)
        sample()
        return result

    lvboot._mv, lvboot._save = mv, save
    check(lvboot.run() == "trial", "real lvboot swap enters trial")
    sample()
    state = readjson("ota/state.json")
    check(state["phase"] == "trial" and state["boots"] == 1, "trial state")
    check(state["prev"] == ("0.3.0" if NAME == "step" else "0.3.1-updater"), "previous version")
    check(state["v"] == VERSION, "trial target version")
    # Simulate boot.py followed by main.py importing the newly installed updater.
    del sys.modules["lvota"]
    lvota = None
    gc.collect()
    import lvota
    check(lvota.MAX_FILES == (64 if NAME == "step" else DUEL_LIMIT), "swapped bytecode carries the shipped limit")
    check(lvota.__file__ == FLASH + "/lvota.mpy", "reload executes swapped .mpy")
    for path, size, digest in MANIFEST["files"]:
        check(os.stat(path)[6] == size, "installed size: " + path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                buf = f.read(512)
                if not buf:
                    break
                h.update(buf)
        check(binascii.hexlify(h.digest()).decode() == digest, "installed SHA256: " + path)
    check(lvota.installed()["v"] == VERSION, "installed target version")
    check(lvota.good() is True, "real good keeps trial")
    sample()
    check(not exists("ota/state.json"), "keep clears state")
    last = readjson("ota/last.json")
    check(last["result"] == "installed" and last["v"] == VERSION, "keep result")
    check(lvboot.run() is None, "kept boot has no pending swap")
    print("swapped and kept", VERSION, "MAX_FILES", lvota.MAX_FILES)
elif STAGE == "final":
    import lvboot
    check(lvboot.run() is None, "fresh reboot stays kept")
    check(lvota.installed()["v"] == "0.3.1", "fresh reboot runs duel")
    check(readjson("ota/last.json")["result"] == "installed", "duel still installed")
    check(not exists("ota/old"), "rollback copies cleared")
else:
    raise ValueError(STAGE)
data_ok()
sample()
check(0 < PEAK < 100000, "isolated sampled live board heap under 100000 B")
print("%s: PASS %d checks; isolated lv32 updater/boot sampled live heap %d B / 100000 B" % (STAGE, COUNT, PEAK))
