#!/usr/bin/env python3
"""Build real OTA stepping-stone fixtures and execute them on lv32 MicroPython.

From game/: MPY_CROSS=... LV_FROZEN_MP=... python3 tests/test_ota_step.py
Exports ota-031-duel to TMPDIR, never builds in the source worktree. Only the
public mockota.TEST_SEED signs these fixtures. No release key is read or used.
The MicroPython test is an isolated updater/boot simulation, not a game or
safe-mode heap measurement. Each reboot is a new interpreter using the actual
installed .mpy and the real lvboot swap and lvota.good implementation.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

GAME = Path(__file__).resolve().parents[1]
REPO = GAME.parent
OLD_REF = "7b4188289d73368cb2f578e62d50a98cd367f5ac"
DUEL_REF = "318ba6d51537bc5019d12084e21b6fe98071554e"
CORE = "2661c2144844"
STEP = "0.3.1-updater"
DUEL = "0.3.1"


def run(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mpy-cross", default=os.environ.get("MPY_CROSS", "mpy-cross"))
    ap.add_argument("--micropython", default=os.environ.get("LV_FROZEN_MP", "micropython-lv32"))
    ap.add_argument("--duel-ref", default=DUEL_REF)
    ap.add_argument("--expected-duel-files", type=int, default=48,
                    help="explicit release count; fail rather than silently invent a 43-file payload")
    ap.add_argument("--keep", action="store_true", help="retain scratch fixtures for inspection")
    a = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="ota-step-", dir=os.environ.get("TMPDIR")))
    try:
        export = root / "export"
        export.mkdir()
        archive = subprocess.check_output(["git", "archive", a.duel_ref], cwd=REPO)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
            tf.extractall(export, filter="data")
        game = export / "game"
        env = dict(os.environ, MPY_CROSS=a.mpy_cross)
        run(["sh", "tools/board_build.sh"], cwd=game, env=env)
        core = game / "tools/fw/cores/lv-core-0.2.0-2661c2144844.json"
        if not core.exists():
            core = next(p for p in (game / "tools/fw/cores").glob("*.json")
                        if json.loads(p.read_text())["core"] == CORE)
        run([sys.executable, export / "tools/build_release.py", "--version", DUEL,
             "--channel", "test", "--label", "Duel stepping-stone test",
             "--source", game / "build/board-fw", "--frozen", core,
             "--repo-root", root / "release-root", "--no-latest",
             "--build-time", "2026-10-30T00:00:00Z"], cwd=export)
        rel = json.loads((root / "release-root/firmware/releases" / DUEL / "release.json").read_text())
        sys.path[:0] = [str(GAME / "sim"), str(GAME / "tools/ota"), str(GAME / "board")]
        import mockota
        import ed25519
        import sign_release
        pub = ed25519.public_key(mockota.TEST_SEED)
        kid = hashlib.sha256(pub).hexdigest()[:8]
        support = root / "support"
        support.mkdir()
        old = subprocess.check_output(["git", "show", OLD_REF + ":game/board/lvota.py"], cwd=REPO)
        (support / "old.py").write_bytes(old)
        oldmod = module("step_old", support / "old.py")
        assert oldmod.MAX_FILES == 40
        assert oldmod.vcmp(STEP, "0.3.0") > 0
        assert oldmod.vcmp("0.3.0", STEP) < 0
        assert oldmod.vcmp(DUEL, STEP) > 0
        assert oldmod.vcmp(STEP, DUEL) < 0
        print("CPython: old MAX_FILES=40; old vcmp both orders: 0.3.0 < 0.3.1-updater < 0.3.1", flush=True)
        # Preserve the shipped release key; add only the public fixture key to test copies.
        def compile_module(src, dest):
            run([a.mpy_cross, "-O3", "-o", dest, src])
        def keyed(src, out):
            text = src.decode() + '\nKEYS["%s"] = unhexlify("%s")\n' % (kid, pub.hex())
            out.write_text(text)
            return out
        compile_module(keyed(old, support / "lvota_old.py"), support / "lvota.mpy")
        fresh = (GAME / "board/lvota.py").read_bytes()
        assert fresh == old.replace(b"MAX_FILES = 40", b"MAX_FILES = 64            # allow the next release after the updater stepping stone", 1)
        newmod = module("step_new", GAME / "board/lvota.py")
        assert newmod.MAX_FILES == 64, "stepping-stone source must ship MAX_FILES=64"
        new_mpy = support / "lvota_new.mpy"
        compile_module(keyed(fresh, support / "lvota_new.py"), new_mpy)
        for name in ("lvotap", "lvsig", "lvboot"):
            compile_module(GAME / "board" / (name + ".py"), support / (name + ".mpy"))
        flash = root / "flash"
        flash.mkdir()
        (flash / "data").mkdir()
        (flash / "data/sentinel.bin").write_bytes(bytes(range(256)))
        (flash / "main.py").write_bytes((GAME / "board/main.py").read_bytes())
        def version(v):
            return json.dumps({"schema": 2, "project": "LongVoyage", "version": v,
                               "channel": "test", "frozen": CORE}, separators=(",", ":")).encode() + b"\n"
        (flash / "version.json").write_bytes(version("0.3.0"))
        shutil.copyfile(support / "lvota.mpy", flash / "lvota.mpy")
        meta = {"kid": kid, "pub": pub.hex(), "duel_ref": subprocess.check_output(
            ["git", "rev-parse", a.duel_ref], cwd=REPO, text=True).strip()}
        def fixture(name, files, manifest):
            folder = root / name
            folder.mkdir()
            for p, data in files.items():
                target = folder / p
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (folder / "env.json").write_text(json.dumps(sign_release.envelope(manifest, mockota.TEST_SEED), separators=(",", ":")))
            (folder / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
            meta[name] = {"count": len(manifest["files"]), "bytes": sum(f[1] for f in manifest["files"])}
        builder = module("step_builder", GAME / "tools/ota/build_updater.py")
        step_rel = builder.build(root / "unsigned-step")
        step_files = {f["path"]: base64.b64decode(f["data"]) for f in step_rel["files"]}
        step_files["lvota.mpy"] = new_mpy.read_bytes()  # only test copies gain the fixture key
        step_m = sign_release.manifest(step_rel)
        step_m["files"] = [[p, len(b), hashlib.sha256(b).hexdigest()] for p, b in sorted(step_files.items())]
        assert len(step_m["files"]) == 38 < oldmod.MAX_FILES
        fixture("step", step_files, step_m)
        duel_m = sign_release.manifest(rel)
        assert len(duel_m["files"]) == a.expected_duel_files, (
            "actual built duel payload has %d files, expected %d; inspect, do not pad or truncate it"
            % (len(duel_m["files"]), a.expected_duel_files))
        assert oldmod.check_manifest(duel_m, {"v": "0.3.0", "core": CORE}, free=10000000) == "bad file list"
        files = {f["path"]: base64.b64decode(f["data"]) for f in rel["files"]}
        # The duel remains the actual built payload, including its unmodified lvota.
        fixture("duel", {p: files[p] for p, _, _ in duel_m["files"]}, duel_m)
        runner = GAME / "tests/mp_ota_step.py"
        # The branch has grown beyond the originally planned 43 files. Exercise
        # both a 43-file size-realistic fixture and the complete current release.
        # Only five launch-screen assets are omitted in the fixture; all included
        # bytes/sizes are unchanged from the actual build. Never publish it.
        actual_files = {p: files[p] for p, _, _ in duel_m["files"]}
        for count in (43, a.expected_duel_files):
            chosen = dict(actual_files)
            omit = sorted(p for p in chosen if p.startswith("www/ls/"))[:len(chosen) - count]
            for p in omit:
                del chosen[p]
            manifest = dict(duel_m, files=[f for f in duel_m["files"] if f[0] in chosen])
            shutil.rmtree(root / "duel")
            fixture("duel", chosen, manifest)
            assert meta["duel"]["count"] == count
            (root / "meta.json").write_text(json.dumps(meta))
            # Reset simulated flash, including original updater, for each chain.
            shutil.rmtree(flash)
            (flash / "data").mkdir(parents=True)
            (flash / "data/sentinel.bin").write_bytes(bytes(range(256)))
            (flash / "main.py").write_bytes((GAME / "board/main.py").read_bytes())
            (flash / "version.json").write_bytes(version("0.3.0"))
            shutil.copyfile(support / "lvota.mpy", flash / "lvota.mpy")
            print("Fixtures:", json.dumps(meta, sort_keys=True), "omitted assets:", omit, flush=True)
            for stage in ("direct", "install-step", "boot-step", "install-duel", "boot-duel", "final"):
                run([a.micropython, "-X", "heapsize=512k", runner, root, stage], cwd=flash)
        print("test_ota_step: PASS (old refusal, two real swaps/keeps, shipped bytecode reload, isolated lv32 heap <100000 B)", flush=True)
    finally:
        if a.keep:
            print("Fixtures retained:", root)
        else:
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
