#!/usr/bin/env python3
"""Package a MicroPython source folder into a Long Voyage updater release.

Writes (relative to the repo root):
  firmware/releases/<version>/release.json   self-contained release (files embedded as base64, size + sha256 each)
  firmware/index.json                        release list the web page reads (updated in place)

Log files named with --log are always preserved too, and data/ is never touched by an install.

Example (coexistence bench test):
  python3 tools/build_release.py --version 0.0.1-coex --channel bench \
      --label "Wi-Fi + BLE coexistence bench test" --source game/bench/coex-test \
      --log coex_log.csv --log coex_log.old --log coex_boot.txt --roles A,B
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".json", ".html", ".css", ".js", ".mjs", ".txt", ".md", ".csv", ".svg"}
DEFAULT_EXCLUDE_DIRS = {"host", "data", "__pycache__", ".git", "tests", "docs"}
DEFAULT_EXCLUDE_GLOBS = ["*.md", "*.pyc", "*.tmp", ".*", "*.orig", "*.bak"]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
# Pico W littlefs is about 848 KB; Pico 2 W about 2.9 MB. Leave room for logs and saves.
FLASH_WARN_BYTES = 600 * 1024
PROJECT = "LongVoyage"
# Device-local files that must never be shipped: they hold per-ship settings and secrets.
NEVER_SHIP = {"ship.json", "crew.json", "device.json", "secrets.py", "secrets.json"}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="semver, e.g. 0.0.1-coex")
    ap.add_argument("--channel", default="stable", help="stable | beta | bench")
    ap.add_argument("--label", required=True)
    ap.add_argument("--source", required=True, type=Path, help="folder copied to the device root")
    ap.add_argument("--include", action="append", default=[], help="only package these paths (repeatable)")
    ap.add_argument("--exclude", action="append", default=[], help="extra glob to skip (repeatable)")
    ap.add_argument("--preserve", action="append", default=[], help="device path never deleted/overwritten (data/ is always kept)")
    ap.add_argument("--delete", action="append", default=[], help="device path removed before writing")
    ap.add_argument("--log", action="append", default=[], help="device file the UI can download; also preserved (repeatable)")
    ap.add_argument("--roles", default="", help="comma list of bench roles offered in ship config, e.g. A,B")
    ap.add_argument("--runtime", default="1.29.0", help="minimum MicroPython version")
    ap.add_argument("--boards", default="RPI_PICO_W,RPI_PICO2_W")
    ap.add_argument("--notes", default="", help="short operator notes shown in the UI")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--build-time", default=None, help="ISO timestamp stored in version.json (default: now); pin it for reproducible builds")
    ap.add_argument("--mpy-cross", default=None, help="path to mpy-cross for a syntax check of every .py")
    ap.add_argument("--no-latest", action="store_true", help="do not move the index 'latest' pointer")
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    return ap.parse_args()


def should_skip(rel: Path, extra_globs: list[str]) -> bool:
    if any(part in DEFAULT_EXCLUDE_DIRS for part in rel.parts[:-1]):
        return True
    return any(rel.match(g) for g in DEFAULT_EXCLUDE_GLOBS + extra_globs)


def collect(source: Path, include: list[str], exclude: list[str]) -> list[Path]:
    if include:
        rels = [Path(p) for p in include]
        for rel in rels:
            if not (source / rel).is_file():
                raise SystemExit(f"--include {rel} not found in {source}")
        return sorted(rels, key=lambda p: p.as_posix())
    out = []
    for src in sorted(source.rglob("*")):
        if src.is_file():
            rel = src.relative_to(source)
            if not should_skip(rel, exclude):
                out.append(rel)
    return out


def mpy_check(mpy_cross: str, files: list[tuple[str, bytes]]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for path, data in files:
            if not path.endswith(".py"):
                continue
            src = Path(tmp) / path
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(data)
            res = subprocess.run([mpy_cross, "-o", str(src.with_suffix(".mpy")), str(src)], capture_output=True, text=True)
            if res.returncode != 0:
                raise SystemExit(f"mpy-cross rejected {path}:\n{res.stderr or res.stdout}")
    print("mpy-cross syntax check passed")


def vkey(version: str):
    core, _, pre = version.partition("-")
    nums = tuple(int(x) for x in core.split("."))
    # a pre-release sorts before the plain version, like semver
    return nums + ((1, "") if not pre else (0, pre))


def main() -> None:
    a = parse_args()
    root = a.repo_root.resolve()
    if not VERSION_RE.match(a.version):
        raise SystemExit(f"bad version {a.version!r}; use semver like 0.0.1 or 0.0.1-coex")
    source = a.source.resolve()
    rels = collect(source, a.include, a.exclude)
    bad = [r.as_posix() for r in rels if r.name in NEVER_SHIP]
    if bad:
        raise SystemExit(f"refusing to ship device-local files: {', '.join(bad)}")
    if "main.py" not in [r.as_posix() for r in rels]:
        raise SystemExit("release has no main.py; the board would boot to an empty REPL")

    created = a.build_time or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    version_meta = {
        "schema": 2, "project": PROJECT, "version": a.version,
        "channel": a.channel, "runtime": "micropython", "min_runtime": a.runtime, "build": created,
    }
    payload: list[tuple[str, bytes]] = [(r.as_posix(), (source / r).read_bytes()) for r in rels if r.as_posix() != "version.json"]
    payload.append(("version.json", (json.dumps(version_meta, separators=(",", ":")) + "\n").encode()))

    preserve = sorted(set(["data/"] + a.preserve + a.log))
    for path, _ in payload:
        if any(path == k or (k.endswith("/") and path.startswith(k)) for k in preserve):
            raise SystemExit(f"{path} is both shipped and preserved; drop it from --preserve or the source")

    if a.mpy_cross:
        mpy_check(a.mpy_cross, payload)

    files = []
    total = 0
    for path, data in payload:
        text = Path(path).suffix.lower() in TEXT_SUFFIXES
        if text:
            data.decode("utf-8")  # fail loudly on a non-UTF-8 "text" file
        files.append({
            "path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "encoding": "utf8" if text else "binary", "data": base64.b64encode(data).decode("ascii"),
        })
        total += len(data)
    if total > FLASH_WARN_BYTES:
        print(f"WARNING: payload is {total} bytes; a Pico W filesystem holds about 848 KB", file=sys.stderr)

    release = {
        "schema": 2,
        "project": PROJECT,
        "version": a.version,
        "channel": a.channel,
        "label": a.label,
        "notes": a.notes,
        "date": a.date,
        "created_at": created,
        "device": "raspberry-pi-pico-w",
        "boards": [b for b in a.boards.split(",") if b],
        "runtime": {"name": "micropython", "min": a.runtime},
        "entrypoint": "main.py",
        "preserve": preserve,
        "delete": a.delete,
        "logs": a.log,
        "shipConfig": {"roles": [r for r in a.roles.split(",") if r]},
        "payload_bytes": total,
        "files": files,
    }
    rel_dir = Path("firmware") / "releases" / a.version
    out_dir = root / rel_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    out = out_dir / "release.json"
    out.write_text(json.dumps(release, separators=(",", ":")) + "\n")

    index_path = root / "firmware" / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"schema": 2, "project": PROJECT, "latest": None, "channels": {}, "releases": []}
    entry = {"version": a.version, "channel": a.channel, "date": a.date, "label": a.label,
             "path": "/" + (rel_dir / "release.json").as_posix(), "bytes": total, "files": len(files)}
    releases = [r for r in index.get("releases", []) if r.get("version") != a.version] + [entry]
    releases.sort(key=lambda r: vkey(r["version"]), reverse=True)
    index["releases"] = releases
    channels = {}
    for r in releases:
        channels.setdefault(r["channel"], r["version"])
    index["channels"] = channels
    if not a.no_latest:
        index["latest"] = channels.get("stable") or releases[0]["version"]
    index_path.write_text(json.dumps(index, indent=2) + "\n")

    print(f"wrote {out.relative_to(root)}: {len(files)} files, {total} bytes payload, {out.stat().st_size} bytes json")
    print(f"index {index_path.relative_to(root)}: latest={index['latest']} channels={index['channels']}")


if __name__ == "__main__":
    main()
