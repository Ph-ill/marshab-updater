#!/usr/bin/env python3
"""Offline check of everything the updater serves: the release list (firmware/index.json),
every release manifest (embedded sizes + sha256, safe paths, nothing device-local shipped),
the MicroPython runtime list (firmware/runtime.json) and the served tree as a whole.
Exit 1 on any problem.

    python3 tools/validate_firmware.py            # offline
    python3 tools/validate_firmware.py --online   # also download the upstream UF2s and check their sha256
"""
import base64, hashlib, json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVED = ["index.html", "styles.css", "favicon.svg", "src", "firmware"]  # what the Dockerfile copies
NEVER_SERVE = {"secrets.py", "secrets.json", "ship.json", "device.json"}
SAFE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]+$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
SHA = re.compile(r"^[0-9a-f]{64}$")
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
        return
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
    notes.append(f"{name}: {len(paths)} files, {total} B")


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
    for r in idx.get("releases", []):
        if not SEMVER.match(r.get("version", "")):
            err(f"index.json: bad version {r.get('version')!r}")
        rp = web_path(r.get("path"))
        if not rp or not rp.is_file():
            err(f"index.json {r.get('version')}: release file {r.get('path')} missing")
        else:
            check_release(rp, r["version"])
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
