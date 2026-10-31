#!/usr/bin/env python3
"""Build the unsigned 0.3.0 updater bridge without changing firmware/index.json.

From the repository root: MPY_CROSS=... python3 game/tools/ota/build_updater.py
Outputs game/build/updater/release.json and its generated version.json.
The normal frozen release is a complete set of overrides, not a delta: its
cleanup deletes omitted overrides. Keep the full 38-file payload, below the
old updater's 40-file limit, rather than accidentally restoring frozen code.
Signing and publication are separate operator steps.

Run it on the stepping stone's own commit (the ota-030-updater branch). On a later branch,
such as the duel's, it would build that branch's files and stop at the 38-file check.

--channel must be the channel the ships that need it are on (their version.json's): the
phone only offers a release on the ship's own channel, and once it's installed its channel
is the ship's. The ships on the 0.3.0 test build are on "test". docs/OTA.md section 8 has
the publishing order (this first, then 0.3.1 with --needs 0.3.1-updater).
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

GAME = Path(__file__).resolve().parents[2]
ROOT = GAME.parent
VERSION = "0.3.1-updater"
CORE = "2661c2144844"


def build(output, channel="stable"):
    subprocess.run(["sh", "tools/board_build.sh"], cwd=GAME, check=True)
    with tempfile.TemporaryDirectory(prefix="updater-build-", dir=os.environ.get("TMPDIR")) as scratch:
        subprocess.run([
            sys.executable, ROOT / "tools/build_release.py", "--version", VERSION,
            "--channel", channel, "--label", "Updater preparation",
            "--source", GAME / "build/board-fw", "--frozen",
            GAME / ("tools/fw/cores/lv-core-0.2.0-" + CORE + ".json"),
            "--exclude", "boot.py", "--exclude", "lvboot.mpy",
            "--repo-root", scratch, "--no-latest", "--date", "2026-10-30",
            "--build-time", "2026-10-30T00:00:00Z",
        ], cwd=ROOT, check=True)
        raw = (Path(scratch) / "firmware/releases" / VERSION / "release.json").read_bytes()
    release = json.loads(raw)
    assert len(release["files"]) == 38 < 40, (
        "%d files: inspect the payload before publishing (run this on the ota-030-updater branch)" % len(release["files"]))
    assert "ota" not in release, "this tool must never sign"
    assert release["channel"] == channel, release["channel"]
    version = next(f for f in release["files"] if f["path"] == "version.json")
    output.mkdir(parents=True, exist_ok=True)
    (output / "release.json").write_bytes(raw)
    (output / "version.json").write_bytes(base64.b64decode(version["data"]))
    print("updater payload: exactly %d files; unsigned; repository index untouched" % len(release["files"]))
    print(output / "release.json")
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GAME / "build/updater")
    parser.add_argument("--channel", choices=("stable", "test"), default="stable",
                        help="the channel of the ships that need it (default stable)")
    args = parser.parse_args()
    build(args.output.resolve(), args.channel)
