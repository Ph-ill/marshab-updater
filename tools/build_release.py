#!/usr/bin/env python3
"""Package a MicroPython source folder into a Long Voyage updater release.

Writes (relative to the repo root):
  firmware/releases/<version>/release.json   self-contained release (files embedded as base64, size + sha256 each)
  firmware/index.json                        release list the web page reads (updated in place)

Log files named with --log are always preserved too, and data/ is never touched by an install.

Partial releases for the game firmware (a .uf2 with the game core lv/ frozen in, see
game/tools/build_firmware.sh): --frozen game/tools/fw/cores/lv-core-<ver>-<core>.json says
which core the release is built against. Such a release ships no lv/ (a /lv folder would
hide the frozen core), may ship lvx/<module>.mpy overrides of only the core modules that
changed, and is refused by the updater on a board running any other core. lv/ and lvx/ are
always cleared first, so overrides from an older release never linger. A core that froze
the board modules and the pack too (lv-core 0.2.0+: "board", "pack" in its manifest) also
gets every copy of those the release doesn't ship (<module>.py, <module>.mpy, pack.bin)
added to "delete", and "replaces" lists the ones it does ship (hotfixes over the frozen
ones: a file is found first on the board).

Releases that an older updater can't take (--needs VERSION: a ship must already run VERSION
or newer to install this one over the air; 0.3.0's updater takes at most 40 files) keep the
index readable for every page in the field: "channels" names the newest release on each
channel without "needs" (what the phone pages up to 0.3.0 read), "heads" the newest release
on each channel (what pages from 0.3.1-updater read, following "needs" down to a release the
ship can take first). See game/docs/OTA.md section 2.

Example (coexistence bench test):
  python3 tools/build_release.py --version 0.0.1-coex --channel bench \
      --label "Wi-Fi + BLE coexistence bench test" --source game/bench/coex-test \
      --log coex_log.csv --log coex_log.old --log coex_boot.txt --roles A,B
"""
from __future__ import annotations

import argparse
import base64
import gzip
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
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
# Channels a release can be published on. "test" builds are listed for hand-picked installs only:
# they never become the index "latest" (what "Install latest" and the update notice use).
CHANNELS = ("stable", "beta", "bench", "test")
NOT_LATEST = ("test",)


def pick_heads(releases: list[dict]):
    """(channels, heads) for releases sorted newest first: heads is the newest release on each
    channel; channels the newest one without "needs", which every phone page can install."""
    channels, heads = {}, {}
    for r in releases:
        heads.setdefault(r["channel"], r["version"])
        if not r.get("needs"):
            channels.setdefault(r["channel"], r["version"])
    return channels, heads


def pick_latest(releases: list[dict], channels: dict):
    """The stable release, else the newest release outside the test channels, else None."""
    if channels.get("stable"):
        return channels["stable"]
    rest = [r["version"] for r in releases if r.get("channel") not in NOT_LATEST]
    return rest[0] if rest else None
# Pico W littlefs is about 848 KB; Pico 2 W about 2.9 MB. Leave room for logs and saves.
FLASH_WARN_BYTES = 600 * 1024
PROJECT = "LongVoyage"
# Device-local files that must never be shipped: they hold per-ship settings and secrets.
NEVER_SHIP = {"ship.json", "crew.json", "device.json", "secrets.py", "secrets.json"}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="semver, e.g. 0.0.1-coex")
    ap.add_argument("--channel", default="stable", choices=CHANNELS,
                    help="stable | beta | bench | test (test never becomes 'latest')")
    ap.add_argument("--label", required=True)
    ap.add_argument("--source", required=True, type=Path, help="folder copied to the device root")
    ap.add_argument("--include", action="append", default=[], help="only package these paths (repeatable)")
    ap.add_argument("--exclude", action="append", default=[], help="extra glob to skip (repeatable)")
    ap.add_argument("--preserve", action="append", default=[], help="device path never deleted/overwritten (data/ is always kept)")
    ap.add_argument("--delete", action="append", default=[], help="device path removed before writing")
    ap.add_argument("--log", action="append", default=[], help="device file the UI can download; also preserved (repeatable)")
    ap.add_argument("--hotspot-prefix", default="", help="hotspot name prefix the release's firmware uses (name = prefix + ship number), shown by the UI")
    ap.add_argument("--roles", default="", help="comma list of bench roles offered in ship config, e.g. A,B")
    ap.add_argument("--runtime", default="1.29.0", help="minimum MicroPython version")
    ap.add_argument("--boards", default="RPI_PICO_W,RPI_PICO2_W")
    ap.add_argument("--notes", default="", help="short operator notes shown in the UI")
    ap.add_argument("--whats-new", default=None, type=Path,
                    help="what's new for players (Settings on the phone): a JSON list or a text file, one line each, "
                         "1-3 lines of at most 120 characters; default: this version's lines in game/tools/ota/whatsnew.json")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--build-time", default=None, help="ISO timestamp stored in version.json (default: now); pin it for reproducible builds")
    ap.add_argument("--mpy-cross", default=None, help="path to mpy-cross for a syntax check of every .py")
    ap.add_argument("--no-latest", action="store_true", help="do not move the index 'latest' pointer")
    ap.add_argument("--needs", default=None,
                    help="oldest version a ship must already run to take this release over the air "
                         "(the release that brings an updater that accepts it); must be in the index")
    ap.add_argument("--frozen", type=Path, default=None,
                    help="core manifest (game/tools/fw/cores/*.json): a partial release for the game firmware with that frozen core")
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--ota-kid", action="append", default=[],
                    help="key id the shipped lvota's KEYS must hold (repeatable; default "
                         + ", ".join(OTA_KIDS) + ": a throwaway test key's id for test builds)")
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


LVX_RE = re.compile(r"^lvx/([a-z_][a-z0-9_]*)\.(mpy|py)$")


def frozen_spec(path: Path, rels: list[str]) -> tuple[dict, list[str]]:
    """(release "frozen" block, override names) for a partial release; exits on a bad layout."""
    core = json.loads(path.read_text())
    for k in ("id", "version", "core", "modules"):
        if k not in core:
            raise SystemExit(f"{path}: not a core manifest (no {k!r})")
    if not re.match(r"^[0-9a-f]{12}$", core["core"]):
        raise SystemExit(f"{path}: bad core hash {core['core']!r}")
    mods = {m[3:] for m in core["modules"] if m.startswith("lv.")}
    overrides = []
    for r in rels:
        if r == "lv" or r.startswith("lv/"):
            raise SystemExit(f"{r}: a game-firmware release must not ship lv/ (it hides the frozen core); "
                             "changed core modules go in lvx/")
        if r.startswith("lvx/"):
            m = LVX_RE.match(r)
            if not m or m.group(1) not in mods:
                raise SystemExit(f"{r}: lvx/ may only hold overrides of the frozen modules ({', '.join(sorted(mods))})")
            if m.group(1) in overrides:
                raise SystemExit(f"{r}: two overrides for lv.{m.group(1)}")
            overrides.append(m.group(1))
    spec = {"id": core["id"], "version": core["version"], "requires": core["core"],
            "micropython": core.get("micropython", ""), "modules": sorted(mods)}
    # lv-core 0.2.0+ also froze the board modules and the story pack (top-level on the board).
    board = list(core.get("board") or [])
    if board:
        spec["board"] = board
    if core.get("pack"):
        spec["pack"] = True
    return spec, sorted(overrides)


def frozen_replaces(frozen: dict, rels: list[str]) -> list[str]:
    """The frozen board modules (and the pack) this release replaces with its own files."""
    out = [m for m in frozen.get("board", []) if m + ".mpy" in rels or m + ".py" in rels]
    if frozen.get("pack") and "pack.bin" in rels:
        out.append("pack.bin")
    return out


def frozen_stale(frozen: dict, rels: list[str]) -> list[str]:
    """Top-level files to delete before installing: every copy of a frozen board module or
    of the pack the release doesn't ship. Files are found before frozen modules on the
    board, so a leftover from an older release would run instead of the firmware's."""
    out = [m + e for m in frozen.get("board", []) for e in (".py", ".mpy") if m + e not in rels]
    if frozen.get("pack") and "pack.bin" not in rels:
        out.append("pack.bin")
    return out


# The most files the updater in 0.3.0 and older takes in one update (game/board/lvota.py
# MAX_FILES = 40 there; 64 from 0.3.1-updater). A frozen-core release with more over-the-air
# files needs --needs, or those ships would be offered an update they can only turn down.
LEGACY_MAX_FILES = 40


def ota_count(paths) -> int:
    """Files in the signed manifest (game/tools/ota/sign_release.py leaves out what the
    updater never writes: data/, ota/, boot.py, lvboot.*)."""
    return sum(1 for p in paths if not (p.split("/")[0] in ("data", "ota", "boot.py")
                                        or p.split("/")[0].startswith("lvboot.")))


def vkey(version: str):
    core, _, pre = version.partition("-")
    nums = tuple(int(x) for x in core.split("."))
    # a pre-release sorts before the plain version, like semver
    return nums + ((1, "") if not pre else (0, pre))


OTA_CHAIN = ("lvota", "lvotap", "lvotaq", "lvotak", "lvsig", "lvsafe", "lvweb")


def mpy_twins(names: list[str]) -> list[str]:
    """The X.py of each module on the update path that the release ships as X.mpy only:
    MicroPython imports X.py ahead of X.mpy, so a stale one (a USB install, a hand-copied fix)
    would run instead of the update's own module, and a broken one that way could keep itself
    (0.3.0 review R1 M2). The update path only (OTA_CHAIN: the upload, the signature check, the
    keep check, safe mode and the web server they answer through): every name here goes into
    the signed envelope, which the ship holds whole at its heap peak (the signature check), so
    a twin for every shipped .mpy (about 25) would cost the install that peak about 1 KB.
    lvboot is never deleted over the air (lvota's bad_path refuses lvboot.*; USB only)."""
    return [m + ".py" for m in OTA_CHAIN if m + ".mpy" in names and m + ".py" not in names]


OTA_KIDS = ("2111b2e9",)    # = game/board/lvotak.py KIDS: the release key's id


def ota_keys_why(payload: list[tuple[str, bytes]], kids: list[str]) -> str | None:
    """None if the release's lvota (lvota.py or lvota.mpy at the root) pins one of `kids`,
    else why not. A release whose lvota.KEYS lacks the release key installs fine, then turns
    down every later update as "signed with a key this ship doesn't know", so only USB could
    fix the ship (0.3.0 fix review FR1 M1; on the ship, lvotak.keys_ok refuses to keep such a
    trial). lvota.py: KEYS read without running it (a dict of 32-byte keys, ids that match
    sha256(key)[:4]). lvota.mpy: its string constants are stored as they are, so the key id
    and the key's 64 hex digits must both be in it. A release with no lvota isn't checked."""
    import ast
    files = dict(payload)
    if "lvota.py" in files:
        keys = None
        for node in ast.parse(files["lvota.py"].decode("utf-8")).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "KEYS":
                try:
                    keys = {k.value: bytes.fromhex(v.args[0].value)
                            for k, v in zip(node.value.keys, node.value.values)}
                except Exception:
                    return "lvota.py: KEYS isn't a plain {kid: unhexlify(hex)} dict"
        if not keys:
            return "lvota.py has no KEYS, or an empty one"
        if any(len(k) != 32 for k in keys.values()):
            return "lvota.py: a KEYS entry isn't a 32-byte key"
        if not any(kid in keys and hashlib.sha256(keys[kid]).hexdigest()[:8] == kid for kid in kids):
            return f"lvota.py: KEYS doesn't hold the release key ({', '.join(kids)})"
    if "lvota.mpy" in files:
        b = files["lvota.mpy"]
        found = {hashlib.sha256(bytes.fromhex(h.decode())).hexdigest()[:8]
                 for h in re.findall(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", b)}
        if not any(kid in found and kid.encode() in b for kid in kids):
            return f"lvota.mpy: KEYS doesn't hold the release key ({', '.join(kids)})"
    return None


FROZEN_COEX_DELETES = ("config.py", "index.html")   # the coex bench firmware's (game/bench/coex-test)


def main() -> None:
    a = parse_args()
    root = a.repo_root.resolve()
    if not VERSION_RE.match(a.version):
        raise SystemExit(f"bad version {a.version!r}; use semver like 0.0.1 or 0.0.1-coex")
    if a.needs is not None:
        index_path = root / "firmware" / "index.json"
        known = {r.get("version"): r for r in (json.loads(index_path.read_text()).get("releases", [])
                                               if index_path.exists() else [])}
        need = known.get(a.needs)
        if not VERSION_RE.match(a.needs) or vkey(a.needs) >= vkey(a.version):
            raise SystemExit(f"--needs {a.needs!r} must be an older version than {a.version}")
        if need is None or need.get("channel") != a.channel:
            raise SystemExit(f"--needs {a.needs}: not a {a.channel} release in {index_path}; publish it first")
    source = a.source.resolve()
    rels = collect(source, a.include, a.exclude)
    bad = [r.as_posix() for r in rels if r.name in NEVER_SHIP]
    if bad:
        raise SystemExit(f"refusing to ship device-local files: {', '.join(bad)}")
    if "main.py" not in [r.as_posix() for r in rels]:
        raise SystemExit("release has no main.py; the board would boot to an empty REPL")

    frozen, overrides = (None, [])
    if a.frozen:
        names = [r.as_posix() for r in rels]
        frozen, overrides = frozen_spec(a.frozen.resolve(), names)
        # never a stale full install, an old override or a copy of a now-frozen module; and
        # never the coex bench firmware's own files on a board it replaces (config.py,
        # index.html: 0.2.0/0.2.2 deleted them, the hand-built 0.2.4-0.2.7 didn't), unless
        # this release ships them itself (review REVIEW2 m1, 0.3.0 R1)
        coex = [d for d in FROZEN_COEX_DELETES if d not in names]
        for d in ["lv", "lvx"] + frozen_stale(frozen, names) + coex + mpy_twins(names):
            if d not in a.delete:
                a.delete.append(d)
    elif any(r.parts[0] == "lvx" for r in rels):
        raise SystemExit("lvx/ overrides only work on the game firmware: give --frozen <core manifest>")

    created = a.build_time or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    # What's new, for players (game/tools/ota/whatsnew.py): in the index entry (the phone's
    # Settings and Version history, online) and release.json's "whats_new". Never in
    # version.json or the signed manifest: the ship reads those while it updates, and its heap
    # has no room for them (0.3.0). Offline, the phone shows the installed version's lines
    # from the page the ship serves (www/app.html.gz, signed with the release: game/web/
    # build.py bakes whatsnew.json into it), checked below.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "game" / "tools" / "ota"))
    import whatsnew
    news = whatsnew.read_file(a.whats_new) if a.whats_new else whatsnew.lines_for(a.version)
    if news is None and frozen:
        print(f"note: no what's new for {a.version} (game/tools/ota/whatsnew.json or --whats-new)", file=sys.stderr)
    version_meta = {
        "schema": 2, "project": PROJECT, "version": a.version,
        "channel": a.channel, "runtime": "micropython", "min_runtime": a.runtime, "build": created,
        **({"frozen": frozen["requires"], "overrides": overrides} if frozen else {}),
    }
    payload: list[tuple[str, bytes]] = [(r.as_posix(), (source / r).read_bytes()) for r in rels if r.as_posix() != "version.json"]
    payload.append(("version.json", (json.dumps(version_meta, separators=(",", ":")) + "\n").encode()))

    page = dict(payload).get("www/app.html.gz")
    if news and page:
        try:
            html = gzip.decompress(page).decode("utf-8")
        except (OSError, EOFError, UnicodeDecodeError):
            html = None
        if html is not None and json.dumps(news[0])[1:-1] not in html:
            raise SystemExit(f"www/app.html.gz doesn't carry {a.version}'s what's new: add it to "
                             "game/tools/ota/whatsnew.json, rebuild the page (game/web/build.py), then build")

    preserve = sorted(set(["data/"] + a.preserve + a.log))
    for path, _ in payload:
        if any(path == k or (k.endswith("/") and path.startswith(k)) for k in preserve):
            raise SystemExit(f"{path} is both shipped and preserved; drop it from --preserve or the source")

    why = ota_keys_why(payload, a.ota_kid or list(OTA_KIDS))
    if why:
        raise SystemExit(f"not building: {why}; the ship could never take another update over the air")

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
        **({"whats_new": news} if news else {}),
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
        **({"hotspot": {"prefix": a.hotspot_prefix}} if a.hotspot_prefix else {}),
        **({"frozen": frozen, "overrides": overrides} if frozen else {}),
        **({"replaces": frozen_replaces(frozen, [p for p, _ in payload])} if frozen and frozen.get("board") else {}),
        "payload_bytes": total,
        "files": files,
    }
    n_ota = ota_count([f["path"] for f in files])
    if frozen and n_ota > LEGACY_MAX_FILES and not a.needs:
        raise SystemExit(f"{a.version} has {n_ota} over-the-air files; ships on 0.3.0 or older take at most "
                         f"{LEGACY_MAX_FILES}. Add --needs <the release whose updater takes it>, e.g. 0.3.1-updater.")
    if frozen and a.needs and (known[a.needs].get("frozen") != frozen["requires"]):
        raise SystemExit(f"--needs {a.needs} is built for core {known[a.needs].get('frozen')}, not {frozen['requires']}")
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
             "path": "/" + (rel_dir / "release.json").as_posix(), "bytes": total, "files": len(files),
             **({"frozen": frozen["requires"]} if frozen else {}),
             **({"notes": news} if news else {}),
             **({"needs": a.needs} if a.needs else {})}
    releases = [r for r in index.get("releases", []) if r.get("version") != a.version] + [entry]
    releases.sort(key=lambda r: vkey(r["version"]), reverse=True)
    index["releases"] = releases
    channels, heads = pick_heads(releases)
    index["channels"] = channels
    if heads != channels or "heads" in index:
        index["heads"] = heads
    if not a.no_latest:
        index["latest"] = pick_latest(releases, heads)
    index_path.write_text(json.dumps(index, indent=2) + "\n")

    print(f"wrote {out.relative_to(root)}: {len(files)} files, {total} bytes payload, {out.stat().st_size} bytes json")
    if frozen:
        print(f"partial release for {frozen['id']} {frozen['version']} core {frozen['requires']}: overrides [{', '.join(overrides)}]"
              + (f", replaces frozen [{', '.join(frozen_replaces(frozen, [p for p, _ in payload]))}]" if frozen.get("board") else ""))
    print(f"index {index_path.relative_to(root)}: latest={index['latest']} channels={index['channels']}"
          + (f" heads={index['heads']}" if "heads" in index else ""))


if __name__ == "__main__":
    main()
