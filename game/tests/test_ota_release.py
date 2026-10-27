#!/usr/bin/env python3
"""The release side of over-the-air updates: tools/ota/sign_release.py signs a release the
way a ship would take it, and tools/validate_firmware.py (the repo's release check) accepts
it and catches a broken one. Runs in a temp copy of firmware/ with a TEST key (seed 0..31)
and a lvota.py whose KEYS hold only that key; the release key is never touched.

  python3 game/tests/test_ota_release.py"""
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
ROOT = GAME.parent
sys.path[:0] = [str(GAME / "tools" / "ota"), str(GAME / "board")]
import ed25519  # noqa: E402
import lvsig  # noqa: E402

fails = 0


def check(what, ok, extra=""):
    global fails
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else "  %s" % (extra,)))
    fails += not ok


SEED = bytes(range(32))
PUB = ed25519.public_key(SEED)
KID = hashlib.sha256(PUB).hexdigest()[:8]
V = "0.2.0-lv-test"
tmp = Path(tempfile.mkdtemp(prefix="lv-ota-rel-"))
try:
    for x in ("firmware", "src"):
        shutil.copytree(ROOT / x, tmp / x)
    for x in ("index.html", "styles.css", "favicon.svg"):
        shutil.copy(ROOT / x, tmp / x)
    (tmp / "game/board").mkdir(parents=True)
    (tmp / "game/board/lvota.py").write_text(
        'from binascii import unhexlify\nKEYS = {"%s": unhexlify("%s")}\n' % (KID, PUB.hex()))
    key = tmp / "test.pem"
    key.write_text(ed25519.dump_pem(SEED))
    rp = tmp / "firmware/releases" / V / "release.json"
    rel = json.loads(rp.read_text())
    # This release predates OTA: give it a main.py that reports in, and boot.py + lvboot to leave out.
    extra = {"main.py": (GAME / "board/main.py").read_bytes(), "boot.py": (GAME / "board/boot.py").read_bytes(),
             "lvboot.mpy": b"not really compiled"}
    rel["files"] = [f for f in rel["files"] if f["path"] not in extra]
    for p, b in extra.items():
        rel["files"].append({"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                             "data": base64.b64encode(b).decode()})
    rel["payload_bytes"] = sum(f["size"] for f in rel["files"])
    rp.write_text(json.dumps(rel, separators=(",", ":")) + "\n")

    def sign(*more):
        return subprocess.run([sys.executable, str(GAME / "tools/ota/sign_release.py"), str(rp), "--key", str(key),
                               "--index", str(tmp / "firmware/index.json"), "--lvota", str(tmp / "game/board/lvota.py"), *more],
                              capture_output=True, text=True)

    def validate():
        r = subprocess.run([sys.executable, str(ROOT / "tools/validate_firmware.py"), "--root", str(tmp)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    r = sign()
    check("sign_release signs it", r.returncode == 0, r.stdout + r.stderr)
    check("the key never shows in its output", SEED.hex() not in r.stdout + r.stderr and "PRIVATE" not in r.stdout)
    check("boot.py and lvboot left out, with a note", "boot.py left out" in r.stdout and "lvboot.mpy left out" in r.stdout, r.stdout)
    rel = json.loads(rp.read_text())
    env = rel["ota"]
    m = json.loads(env["m"])
    check("envelope: kid, manifest version/channel/core", env["kid"] == KID and m["version"] == V
          and m["channel"] == "test" and m["core"] == rel["frozen"]["requires"])
    check("manifest: every file but boot.py and lvboot", [f[0] for f in m["files"]] ==
          [f["path"] for f in rel["files"] if f["path"] not in ("boot.py", "lvboot.mpy")])
    check("manifest: nothing protected deleted", not any(p.split("/")[0] in ("data", "ota", "boot.py") for p in m["delete"]))
    check("the ship's verify accepts it (lvsig)", lvsig.verify(PUB, b"LV-OTA-1\n" + hashlib.sha256(env["m"].encode()).digest(),
                                                              base64.b64decode(env["sig"])))
    idx = json.loads((tmp / "firmware/index.json").read_text())
    check("index entry marked ota: kid", next(e for e in idx["releases"] if e["version"] == V).get("ota") == KID)
    code, out = validate()
    check("validate_firmware: passes, says signed", code == 0 and ("ota signed " + KID) in out, out)

    good = rp.read_text()
    for what, change in (
        ("a tampered manifest", lambda r: r["ota"].__setitem__("m", r["ota"]["m"].replace(V, "9.9.9"))),
        ("a bad signature", lambda r: r["ota"].__setitem__("sig", base64.b64encode(bytes(64)).decode())),
        ("an untrusted key", lambda r: r["ota"].__setitem__("kid", "00000000")),
        ("a file changed after signing", lambda r: r["files"][0].update(
            data=base64.b64encode(b"x").decode(), size=1, sha256=hashlib.sha256(b"x").hexdigest())),
    ):
        r = json.loads(good)
        change(r)
        if what.startswith("a file"):
            r["payload_bytes"] = sum(f["size"] for f in r["files"])
        rp.write_text(json.dumps(r, separators=(",", ":")) + "\n")
        code, out = validate()
        check("validate_firmware refuses " + what, code == 1 and "ERR firmware/releases/%s/release.json: ota" % V in out, out[-400:])
    rp.write_text(good)
    r = json.loads(good)
    r["files"].append({"path": "data/x", "size": 1, "sha256": hashlib.sha256(b"x").hexdigest(), "data": "eA=="})
    rp.write_text(json.dumps(r, separators=(",", ":")) + "\n")
    s = sign()
    check("sign_release refuses a release that ships data/", s.returncode != 0 and "data/x" in s.stderr, s.stderr)
    rp.write_text(good)
    other = tmp / "other.pem"
    other.write_text(ed25519.dump_pem(bytes(range(1, 33))))
    s = subprocess.run([sys.executable, str(GAME / "tools/ota/sign_release.py"), str(rp), "--key", str(other),
                        "--index", str(tmp / "firmware/index.json"), "--lvota", str(tmp / "game/board/lvota.py")],
                       capture_output=True, text=True)
    check("sign_release refuses a key the ships don't trust", s.returncode != 0 and "not signing" in s.stderr, s.stderr)
    check("the repo's own lvota KEYS are untouched (one key, 2111b2e9)",
          '"2111b2e9"' in (GAME / "board/lvota.py").read_text())
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("RESULT", "PASS" if not fails else "FAIL %d" % fails)
sys.exit(1 if fails else 0)
