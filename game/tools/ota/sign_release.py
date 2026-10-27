#!/usr/bin/env python3
"""Sign a release for over-the-air install (the ship's side: board/lvota.py).

  python3 game/tools/ota/sign_release.py firmware/releases/<version>/release.json [--key PEM]
  python3 game/tools/ota/sign_release.py --keygen PEM

Run after tools/build_release.py. Adds "ota" to the release.json: the signed envelope
{"m": manifest JSON text, "sig": base64 Ed25519, "kid": key id}, where the manifest lists
every file the release ships as [path, size, sha256] plus what it deletes, the version,
the channel and the frozen core it needs. Marks the release's index.json entry with
"ota": <key id> so the phone page knows it can offer it. The ship checks the signature
(over b"LV-OTA-1\\n" + sha256(manifest)) against the public keys in board/lvota.py
KEYS, then each file's sha256 as it lands.

The private key: --key, else $LV_OTA_KEY, else ~/.secrets/lv_ota_signing_key. Keep it out
of the repo; this script never prints it. --keygen writes a new one (mode 600) and prints
only the public key and its id, for KEYS.

Only releases for a frozen core (game firmware lv-core 0.2.0+) can go over the air: their
main.py must report in (lvota.good()) or the ship rolls the update back. The ship never
takes data/, ota/, boot.py or lvboot over the air: a release that ships a file in data/ or
ota/ is refused here; boot.py and lvboot (the rollback itself) are left out of the manifest,
with a note, because they go on over USB only, so a bad update can't break its own way
back. None of these paths ever goes in "delete"."""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = HERE.parent.parent
ROOT = GAME.parent
sys.path[:0] = [str(HERE), str(GAME / "board")]
import ed25519  # noqa: E402

TAG = b"LV-OTA-1\n"
DEFAULT_KEY = Path(os.path.expanduser("~/.secrets/lv_ota_signing_key"))


def key_id(pub):
    return hashlib.sha256(pub).hexdigest()[:8]


def protected(p):
    parts = p.split("/")
    return parts[0] in ("data", "ota", "boot.py") or parts[0].startswith("lvboot.")


def manifest(rel):
    fz = rel.get("frozen") or {}
    if not fz.get("requires"):
        raise SystemExit("%s: not built for a frozen core: can't go over the air" % rel.get("version"))
    files = []
    for f in rel["files"]:
        if protected(f["path"]):
            if f["path"].startswith(("data/", "ota/")):
                raise SystemExit("%s: ships %s: a release never writes there" % (rel["version"], f["path"]))
            # boot.py and lvboot (the rollback) go on over USB only: an update can't break them
            print("%s: %s left out (installed over USB only)" % (rel["version"], f["path"]))
            continue
        files.append([f["path"], f["size"], f["sha256"]])
    main = next((f for f in rel["files"] if f["path"] == "main.py"), None)
    if main is None or b"lvota" not in base64.b64decode(main["data"]):
        raise SystemExit("%s: main.py doesn't report in to lvota: every install would roll back" % rel["version"])
    shipped = {f[0] for f in files}
    delete = [p for p in rel.get("delete") or () if not protected(p) and p not in shipped]
    return {"schema": 1, "project": rel["project"], "version": rel["version"],
            "channel": rel["channel"], "core": fz["requires"], "files": files, "delete": delete}


def envelope(m, seed):
    text = json.dumps(m, separators=(",", ":"))
    sig = ed25519.sign(seed, TAG + hashlib.sha256(text.encode()).digest())
    return {"m": text, "sig": base64.b64encode(sig).decode(), "kid": key_id(ed25519.public_key(seed))}


def check(env, keys):
    """None if `env` verifies against `keys` ({kid: pub}) the way the ship does, else why not."""
    import lvsig
    pub = keys.get(env.get("kid"))
    if pub is None:
        return "unknown key id %s" % env.get("kid")
    h = hashlib.sha256(env["m"].encode()).digest()
    return None if lvsig.verify(pub, TAG + h, base64.b64decode(env["sig"])) else "bad signature"


def ship_keys(path=None):
    """KEYS from board/lvota.py (or another copy: the tests'), read without importing it."""
    import ast
    src = Path(path or GAME / "board" / "lvota.py").read_text()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "KEYS":
            return {k.value: bytes.fromhex(v.args[0].value) for k, v in zip(node.value.keys, node.value.values)}
    raise SystemExit("no KEYS in board/lvota.py")


def keygen(path):
    path = Path(path)
    if path.exists():
        raise SystemExit("%s exists: not overwriting a key" % path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    seed = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(ed25519.dump_pem(seed))
    pub = ed25519.public_key(seed)
    print("wrote %s (mode 600). For board/lvota.py KEYS:" % path)
    print('    "%s": unhexlify("%s")' % (key_id(pub), pub.hex()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("release", nargs="?")
    ap.add_argument("--key")
    ap.add_argument("--keygen")
    ap.add_argument("--index", default=str(ROOT / "firmware" / "index.json"))
    ap.add_argument("--lvota", help="the lvota.py whose KEYS must accept the signature (tests)")
    a = ap.parse_args(argv)
    if a.keygen:
        return keygen(a.keygen)
    if not a.release:
        ap.error("name a release.json")
    kp = Path(a.key or os.environ.get("LV_OTA_KEY") or DEFAULT_KEY)
    seed = ed25519.load_pem(kp.read_text())
    rp = Path(a.release)
    rel = json.loads(rp.read_text())
    env = envelope(manifest(rel), seed)
    why = check(env, ship_keys(a.lvota))
    if why:
        raise SystemExit("not signing: %s (is board/lvota.py KEYS this key's public key?)" % why)
    rel["ota"] = env
    rp.write_text(json.dumps(rel, separators=(",", ":")) + "\n")
    ip = Path(a.index)
    if ip.exists():
        idx = json.loads(ip.read_text())
        for r in idx.get("releases", []):
            if r.get("version") == rel["version"]:
                r["ota"] = env["kid"]
        ip.write_text(json.dumps(idx, indent=2) + "\n")
    print("signed %s for over-the-air install: %d files, key %s" % (rel["version"], len(json.loads(env["m"])["files"]), env["kid"]))


if __name__ == "__main__":
    main()
