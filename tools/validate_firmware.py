#!/usr/bin/env python3
"""Offline check of everything the updater serves: the release list (firmware/index.json),
every release manifest (embedded sizes + sha256, safe paths, nothing device-local shipped),
the over-the-air envelope of a signed release (signature against the ship's keys in
game/board/lvota.py, manifest = the release's files),
the MicroPython runtime list (firmware/runtime.json) and the served tree as a whole.
Exit 1 on any problem.

    python3 tools/validate_firmware.py            # offline
    python3 tools/validate_firmware.py --online   # also download the upstream UF2s and check their sha256
    python3 tools/validate_firmware.py --root DIR # another tree (served-tree and runtime checks need its files)
"""
import base64, hashlib, json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "--root" in sys.argv:          # check another tree (the tests build releases in a temp dir)
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
SERVED = ["index.html", "styles.css", "favicon.svg", "src", "firmware"]  # what the Dockerfile copies
NEVER_SERVE = {"secrets.py", "secrets.json", "ship.json", "crew.json", "device.json"}
SAFE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]+$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
CHANNELS = ("stable", "beta", "bench", "test")
NOT_LATEST = ("test",)  # listed for hand-picked installs only, never "latest"
SHA = re.compile(r"^[0-9a-f]{64}$")
CORE = re.compile(r"^[0-9a-f]{12}$")
LVX = re.compile(r"^lvx/([a-z_][a-z0-9_]*)\.(mpy|py)$")
errors, notes = [], []


def err(msg):
    errors.append(msg)


def load(path):
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        err(f"{path.relative_to(ROOT)}: {e}")
        return None


def web_path(url):
    return ROOT / url.lstrip("/") if isinstance(url, str) and url.startswith("/") else None


def check_release(path, version):
    rel = load(path)
    if rel is None:
        return None
    name = path.relative_to(ROOT)
    if rel.get("version") != version:
        err(f"{name}: version {rel.get('version')} != index entry {version}")
    if rel.get("project") != "LongVoyage":
        err(f"{name}: project {rel.get('project')!r} is not LongVoyage")
    preserve = rel.get("preserve") or []
    if "data/" not in preserve:
        err(f"{name}: preserve must include data/")
    for log in rel.get("logs") or []:
        if log not in preserve:
            err(f"{name}: log {log} is not preserved")
    paths = [f.get("path", "") for f in rel.get("files", [])]
    if "main.py" not in paths:
        err(f"{name}: no main.py")
    total = 0
    for f in rel.get("files", []):
        p = f.get("path", "")
        if not SAFE.match(p) or p.startswith("data/"):
            err(f"{name}: unsafe or data/ path {p!r}")
        if p in preserve:
            err(f"{name}: {p} is both shipped and preserved")
        if p.split("/")[-1] in NEVER_SERVE:
            err(f"{name}: ships device-local file {p}")
        if "data" not in f:
            err(f"{name}: {p} has no embedded data")
            continue
        raw = base64.b64decode(f["data"])  # always base64; "encoding" only says how the board writes it
        if len(raw) != f.get("size"):
            err(f"{name}: {p} size {len(raw)} != {f.get('size')}")
        if not SHA.match(f.get("sha256", "")) or hashlib.sha256(raw).hexdigest() != f["sha256"]:
            err(f"{name}: {p} sha256 missing or wrong")
        total += len(raw)
    if rel.get("payload_bytes") != total:
        err(f"{name}: payload_bytes {rel.get('payload_bytes')} != {total}")
    part = check_frozen(rel, paths, name)
    if rel.get("ota") is not None:
        part += check_ota(rel, name)
    notes.append(f"{name}: {len(paths)} files, {total} B{part}")
    return rel


def check_frozen(rel, paths, name):
    """A partial release for the game firmware (a frozen core): no lv/, overrides only of
    the core's modules in lvx/, lv and lvx cleared first. Anything else must not ship lvx/."""
    fz = rel.get("frozen")
    lvx = [p for p in paths if p.startswith("lvx/")]
    if fz is None:
        if lvx:
            err(f"{name}: ships lvx/ overrides but names no frozen core")
        return ""
    if not isinstance(fz, dict) or not CORE.match(str(fz.get("requires", ""))) or not fz.get("id"):
        err(f"{name}: frozen must name id and a 12-hex core hash in 'requires'")
        return ""
    mods = set(fz.get("modules") or [])
    if not mods:
        err(f"{name}: frozen lists no modules")
    for p in paths:
        if p == "lv" or p.startswith("lv/"):
            err(f"{name}: ships {p}: a /lv folder hides the frozen core")
    names = []
    for p in lvx:
        m = LVX.match(p)
        if not m or m.group(1) not in mods:
            err(f"{name}: {p} is not an override of a frozen module")
        elif m.group(1) in names:
            err(f"{name}: two overrides for lv.{m.group(1)}")
        else:
            names.append(m.group(1))
    if sorted(names) != sorted(rel.get("overrides") or []):
        err(f"{name}: overrides {rel.get('overrides')} != lvx/ files {sorted(names)}")
    for d in ("lv", "lvx"):
        if d not in (rel.get("delete") or []):
            err(f"{name}: a frozen-core release must delete {d} before installing")
    for d in rel.get("preserve") or []:
        if d.rstrip("/") in ("lv", "lvx") or d.startswith(("lv/", "lvx/")):
            err(f"{name}: must not preserve {d}")
    # lv-core 0.2.0+: the board modules and the pack are frozen too. A file on the board is
    # found before the frozen module, so the release must delete every copy it doesn't ship
    # (an older install's lvship.mpy would run instead of the firmware's), and "replaces"
    # must name exactly the ones it ships (hotfixes).
    board = fz.get("board") or []
    if not isinstance(board, list) or not all(isinstance(m, str) and re.match(r"^[a-z_][a-z0-9_]*$", m) for m in board):
        err(f"{name}: frozen.board must be a list of module names")
        board = []
    top = set(p for p in paths if "/" not in p)
    stale = [m + e for m in board for e in (".py", ".mpy") if m + e not in top]
    if fz.get("pack") and "pack.bin" not in top:
        stale.append("pack.bin")
    missing = [p for p in stale if p not in (rel.get("delete") or [])]
    if missing:
        err(f"{name}: must delete {', '.join(missing)} (frozen in core {fz['requires']}; a leftover file would replace it)")
    shipped = [m for m in board if m + ".mpy" in top or m + ".py" in top] + (
        ["pack.bin"] if fz.get("pack") and "pack.bin" in top else [])
    if board and sorted(rel.get("replaces") or []) != sorted(shipped):
        err(f"{name}: replaces {rel.get('replaces')} != the frozen modules it ships {sorted(shipped)}")
    for p in top:
        if p in (rel.get("delete") or []):
            err(f"{name}: ships {p} and deletes it")
    extra = f", replaces frozen [{', '.join(shipped)}]" if board else ""
    return f", partial: {fz['id']} core {fz['requires']}, overrides [{', '.join(sorted(names))}]{extra}"


def ota_keys():
    """KEYS from game/board/lvota.py (what the ships trust), read without importing it."""
    import ast
    src = (ROOT / "game/board/lvota.py").read_text() if (ROOT / "game/board/lvota.py").is_file() else \
        (Path(__file__).resolve().parents[1] / "game/board/lvota.py").read_text()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "KEYS":
            return {k.value: bytes.fromhex(v.args[0].value) for k, v in zip(node.value.keys, node.value.values)}
    return {}


def ota_protected(p):
    top = p.split("/")[0]
    return top in ("data", "ota", "boot.py") or top.startswith("lvboot.")


def check_ota(rel, name):
    """The signed envelope game/tools/ota/sign_release.py adds: a ship would take it."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game/board"))
    import lvsig
    env = rel["ota"]
    if not isinstance(env, dict) or not all(isinstance(env.get(k), str) for k in ("m", "sig", "kid")):
        err(f"{name}: ota must be {{m, sig, kid}} strings")
        return ""
    pub = ota_keys().get(env["kid"])
    if pub is None:
        err(f"{name}: ota key {env['kid']} is not one the ships trust (game/board/lvota.py KEYS)")
        return ""
    try:
        sig = base64.b64decode(env["sig"], validate=True)
    except Exception:  # noqa: BLE001
        sig = b""
    if not lvsig.verify(pub, b"LV-OTA-1\n" + hashlib.sha256(env["m"].encode()).digest(), sig):
        err(f"{name}: ota signature doesn't verify")
        return ""
    m = json.loads(env["m"])
    want = {"schema": 1, "project": "LongVoyage", "version": rel.get("version"),
            "channel": rel.get("channel"), "core": (rel.get("frozen") or {}).get("requires")}
    for k, v in want.items():
        if m.get(k) != v:
            err(f"{name}: ota manifest {k} {m.get(k)!r} != {v!r}")
    files = [[f["path"], f["size"], f["sha256"]] for f in rel.get("files", []) if not ota_protected(f["path"])]
    if m.get("files") != files:
        err(f"{name}: ota manifest files don't match the release's files")
    for p in m.get("delete") or []:
        if not SAFE.match(p) or ota_protected(p):
            err(f"{name}: ota deletes {p!r}")
    return f", ota signed {env['kid']}"


def check_index():
    idx = load(ROOT / "firmware/index.json")
    if idx is None:
        return
    versions = [r.get("version") for r in idx.get("releases", [])]
    if len(set(versions)) != len(versions):
        err("index.json: duplicate versions")
    if idx.get("latest") is not None and idx["latest"] not in versions:
        err(f"index.json: latest {idx['latest']} not in releases")
    for ch, v in (idx.get("channels") or {}).items():
        if v not in versions:
            err(f"index.json: channel {ch} -> {v} not in releases")
    by_version = {r.get("version"): r for r in idx.get("releases", [])}
    if idx.get("latest") in by_version and by_version[idx["latest"]].get("channel") in NOT_LATEST:
        err(f"index.json: latest {idx['latest']} is a {by_version[idx['latest']].get('channel')} release")
    for r in idx.get("releases", []):
        if r.get("channel") not in CHANNELS:
            err(f"index.json {r.get('version')}: unknown channel {r.get('channel')!r}")
        if not SEMVER.match(r.get("version", "")):
            err(f"index.json: bad version {r.get('version')!r}")
        rp = web_path(r.get("path"))
        if not rp or not rp.is_file():
            err(f"index.json {r.get('version')}: release file {r.get('path')} missing")
        else:
            rel = check_release(rp, r["version"])
            want = ((rel or {}).get("frozen") or {}).get("requires")
            if rel is not None and r.get("frozen") != want:
                err(f"index.json {r.get('version')}: frozen {r.get('frozen')} != release {want}")
            kid = ((rel or {}).get("ota") or {}).get("kid")
            if rel is not None and r.get("ota") != kid:
                err(f"index.json {r.get('version')}: ota {r.get('ota')} != release's key {kid}")
    notes.append(f"index.json: {len(versions)} release(s), latest {idx.get('latest')}")


def check_runtime(online):
    spec = load(ROOT / "firmware/runtime.json")
    if spec is None:
        return
    if not SEMVER.match(spec.get("version", "")):
        err("runtime.json: bad version")
    for board, b in (spec.get("boards") or {}).items():
        url = b.get("url", "")
        if not url.startswith("https://micropython.org/resources/firmware/") or not url.endswith(".uf2"):
            err(f"runtime.json {board}: url must be an https micropython.org .uf2")
        if spec.get("version", "~") not in url:
            err(f"runtime.json {board}: url does not carry version {spec.get('version')}")
        if not SHA.match(b.get("sha256", "")) or not isinstance(b.get("size"), int):
            err(f"runtime.json {board}: size/sha256 missing")
            continue
        if online:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
            if len(data) != b["size"] or hashlib.sha256(data).hexdigest() != b["sha256"]:
                err(f"runtime.json {board}: upstream file does not match size/sha256")
            elif data[:4] != b"UF2\n":
                err(f"runtime.json {board}: upstream file is not a UF2")
            else:
                notes.append(f"runtime {board}: upstream {len(data)} B matches sha256")
    notes.append(f"runtime.json: MicroPython {spec.get('version')} for {', '.join(spec.get('boards') or {})}")


def check_served_tree():
    for top in SERVED:
        p = ROOT / top
        if not p.exists():
            err(f"served path {top} missing")
            continue
        for f in [p] if p.is_file() else p.rglob("*"):
            if f.is_file() and f.name in NEVER_SERVE:
                err(f"served tree contains {f.relative_to(ROOT)}")
            if f.is_file() and f.suffix == ".uf2":
                err(f"served tree vendors {f.relative_to(ROOT)}; link micropython.org instead")


check_index()
check_runtime("--online" in sys.argv)
check_served_tree()
for n in notes:
    print("ok ", n)
for e in errors:
    print("ERR", e)
print(f"{len(errors)} problem(s)")
sys.exit(1 if errors else 0)
