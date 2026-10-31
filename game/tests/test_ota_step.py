#!/usr/bin/env python3
"""The 0.3.1 upgrade path, end to end (review 0.3.1-3 #3 and #6): a ship on 0.3.0, whose
updater takes at most 40 files, gets the stepping stone (0.3.1-updater: 0.3.0 with the
64-file updater), then the duel build (0.3.1, more than 40 files).

From game/: MPY_CROSS=... LV_FROZEN_MP=... python3 tests/test_ota_step.py [--duel-ref REF]

Builds, in a scratch folder (never in a source tree):
- a 0.3.0 ship's flash: OLD_REF exported, tools/board_build.sh, a 0.3.0 release laid out
  as a USB install leaves it (boot.py and lvboot too);
- the stepping stone from this tree (game/tools/ota/build_updater.py --channel test);
- the duel build from --duel-ref (default DUEL_REF), exported and built with its own tools;
- a stand-in GitHub: firmware/index.json and each release.json, signed. "good" is the
  index a publisher should write (channels on the stepping stone, heads on the duel,
  "needs"), checked with tools/validate_firmware.py's rules; "bad" points channels at the
  duel with no "needs", as a hand-edited index might.
Only the public fixture key (sim/mockota.TEST_SEED) signs, and only the test copies of the
updaters trust it. No release key is read or used.

Then tests/ota_step_page.mjs runs the real phone pages (0.3.0's web/ota.js, this tree's,
the duel's) in a JS VM against the simulated ship (tests/mp_ota_step.py on lv32), restart
by restart: the chain, this page on a 0.3.0 ship, both pages against the bad index, and
power cuts and failed trials on both swaps. Heap sampled inside the updater must stay
under 110,000 B.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

GAME = Path(__file__).resolve().parents[1]
REPO = GAME.parent
OLD_REF = "7b4188289d73368cb2f578e62d50a98cd367f5ac"     # 0.3.0 as the ships run it
DUEL_REF = "9a35371"                                      # the 0.3.1 duel build under test
DUEL_FILES = 48                                           # its signed files at DUEL_REF (47 + version.json)
DUEL_MAX_FILES = 64                                       # the updater it ships
CORE = "2661c2144844"
OLD, STEP, DUEL = "0.3.0", "0.3.1-updater", "0.3.1"
CAP = 110000
SCENARIOS = ("chain", "newpage", "badold", "badnew", "faults")


def run(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def export(ref, dest):
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(["git", "archive", ref], cwd=REPO))) as tf:
        tf.extractall(dest, filter="data")
    return subprocess.check_output(["git", "rev-parse", ref + "^{commit}"], cwd=REPO, text=True).strip()


def build_release(tree, version, out, *more):
    """tree's own tools/build_release.py on its own board build -> release.json (a dict)."""
    core = tree / "game/tools/fw/cores" / ("lv-core-0.2.0-%s.json" % CORE)
    run([sys.executable, tree / "tools/build_release.py", "--version", version, "--channel", "test",
         "--label", "upgrade path test", "--source", tree / "game/build/board-fw", "--frozen", core,
         "--repo-root", out, "--no-latest", "--date", "2026-10-30", "--build-time", "2026-10-30T00:00:00Z",
         *more], cwd=tree, stdout=subprocess.DEVNULL)
    return json.loads((out / "firmware/releases" / version / "release.json").read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mpy-cross", default=os.environ.get("MPY_CROSS", "mpy-cross"))
    ap.add_argument("--micropython", default=os.environ.get("LV_FROZEN_MP", "micropython-lv32"))
    ap.add_argument("--duel-ref", default=os.environ.get("LV_DUEL_REF", DUEL_REF))
    ap.add_argument("--expected-duel-files", type=int, default=DUEL_FILES,
                    help="the duel payload's file count at --duel-ref: fail on any other, never pad or trim")
    ap.add_argument("--only", choices=SCENARIOS, action="append", help="run only these scenarios")
    ap.add_argument("--keep", action="store_true", help="keep the scratch folder")
    a = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="ota-step-", dir=os.environ.get("TMPDIR")))
    env = dict(os.environ, MPY_CROSS=a.mpy_cross)
    try:
        sys.dont_write_bytecode = True        # (no __pycache__ left in tools/)
        sys.path[:0] = [str(GAME / "sim"), str(GAME / "tools/ota"), str(REPO / "tools")]
        import mockota
        import ed25519
        import sign_release
        import validate_firmware
        pub = ed25519.public_key(mockota.TEST_SEED)
        kid = sign_release.key_id(pub)
        sup = root / "support"
        sup.mkdir()

        def keyed(src, name):
            """lvota source + the fixture key -> .mpy bytes (the shipped KEYS are kept)."""
            py = sup / (name + ".py")
            py.write_text(src.decode() + '\nKEYS["%s"] = unhexlify("%s")\n' % (kid, pub.hex()))
            run([a.mpy_cross, "-O3", "-o", sup / (name + ".mpy"), py])
            return (sup / (name + ".mpy")).read_bytes()

        def reship(rel, path, data):
            f = next(f for f in rel["files"] if f["path"] == path)
            f.update(size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=base64.b64encode(data).decode())

        # ---- the updaters, as source: each limit checked on its own ----
        old_src = subprocess.check_output(["git", "show", OLD_REF + ":game/board/lvota.py"], cwd=REPO)
        (sup / "old.py").write_bytes(old_src)
        oldmod = module("step_old", sup / "old.py")
        assert oldmod.MAX_FILES == 40, oldmod.MAX_FILES
        for x, y in ((OLD, STEP), (STEP, DUEL), (OLD, DUEL)):
            assert oldmod.vcmp(x, y) < 0 < oldmod.vcmp(y, x), (x, y)
        new_src = (GAME / "board/lvota.py").read_bytes()
        assert new_src == old_src.replace(b"MAX_FILES = 40", b"MAX_FILES = 64            # allow the next release after the updater stepping stone", 1), \
            "the stepping stone's updater is 0.3.0's with only its file limit raised"
        newmod = module("step_new", GAME / "board/lvota.py")
        assert newmod.MAX_FILES == 64

        # ---- 0.3.0, as a ship has it after its USB install ----
        old_tree = root / "old"
        old_sha = export(OLD_REF, old_tree)
        run(["sh", "tools/board_build.sh"], cwd=old_tree / "game", env=env, stdout=subprocess.DEVNULL)
        old_rel = build_release(old_tree, OLD, root / "old-root")
        pristine = root / "pristine"
        (pristine / "data").mkdir(parents=True)
        (pristine / "data/sentinel.bin").write_bytes(bytes(range(256)))
        for f in old_rel["files"]:
            (pristine / f["path"]).parent.mkdir(parents=True, exist_ok=True)
            (pristine / f["path"]).write_bytes(base64.b64decode(f["data"]))
        for f in ("boot.py", "lvboot.mpy"):
            assert (pristine / f).exists(), f + " is on a USB-installed ship"
        (pristine / "lvota.mpy").write_bytes(keyed(old_src, "lvota_old"))
        assert json.loads((pristine / "version.json").read_text())["channel"] == "test"

        # ---- the stepping stone, from this tree ----
        builder = module("step_builder", GAME / "tools/ota/build_updater.py")
        step_rel = builder.build(root / "unsigned-step", "test")
        assert step_rel["channel"] == "test"
        reship(step_rel, "lvota.mpy", keyed(new_src, "lvota_new"))     # test copy: trusts the fixture key
        step_m = sign_release.manifest(step_rel)
        assert len(step_m["files"]) == 38 <= oldmod.MAX_FILES, len(step_m["files"])
        assert oldmod.check_manifest(step_m, {"v": OLD, "core": CORE}, free=10 ** 7) is None

        # ---- the duel build, with its own tools; its updater as it ships ----
        duel_tree = root / "duel"
        duel_sha = export(a.duel_ref, duel_tree)
        duel_py = (duel_tree / "game/board/lvota.py").read_text()
        duel_limit = int(re.search(r"^MAX_FILES = (\d+)", duel_py, re.M).group(1))
        assert duel_limit == DUEL_MAX_FILES, "the duel's own updater takes %d files" % duel_limit
        run(["sh", "tools/board_build.sh"], cwd=duel_tree / "game", env=env, stdout=subprocess.DEVNULL)
        duel_rel = build_release(duel_tree, DUEL, root / "duel-root")
        duel_m = sign_release.manifest(duel_rel)
        assert len(duel_m["files"]) == a.expected_duel_files, (
            "the duel payload at %s has %d files, expected %d: look at it, never pad or trim it"
            % (duel_sha, len(duel_m["files"]), a.expected_duel_files))
        assert len(duel_m["files"]) <= duel_limit and len(duel_m["files"]) <= newmod.MAX_FILES
        assert oldmod.check_manifest(duel_m, {"v": OLD, "core": CORE}, free=10 ** 7) == "bad file list"
        assert newmod.check_manifest(duel_m, {"v": STEP, "core": CORE}, free=10 ** 7) is None

        # ---- the stand-in GitHub ----
        gh = root / "gh"
        counts = {}
        for name, rel, m in ((STEP, step_rel, step_m), (DUEL, duel_rel, duel_m)):
            rel = dict(rel, ota=sign_release.envelope(m, mockota.TEST_SEED))
            for idx in ("good", "bad"):
                p = gh / idx / "firmware/releases" / name / "release.json"
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps(rel))
            counts[name] = {"files": len(m["files"]), "bytes": sum(f[1] for f in m["files"])}

        def entry(v, **more):
            return {"version": v, "channel": "test", "date": "2026-10-30", "label": "upgrade path test",
                    "frozen": CORE, "path": "/firmware/releases/%s/release.json" % v, "notes": [], **more}
        good = {"schema": 1, "channels": {"test": STEP}, "heads": {"test": DUEL},
                "releases": [entry(DUEL, ota=kid, needs=STEP), entry(STEP, ota=kid), entry(OLD)]}
        bad = {"schema": 1, "channels": {"test": DUEL},
               "releases": [entry(DUEL, ota=kid), entry(STEP, ota=kid), entry(OLD)]}
        ota_files = {DUEL: counts[DUEL]["files"], STEP: counts[STEP]["files"], OLD: 0}
        for idx, want in ((good, []), (bad, ["0.3.1: 48 over-the-air files, more than the 40"])):
            validate_firmware.errors[:] = []
            validate_firmware.check_needs(idx, {r["version"]: r for r in idx["releases"]}, ota_files)
            got = validate_firmware.errors
            assert len(got) == len(want) and all(w in e for w, e in zip(want, got)), got
        (gh / "good/firmware/index.json").write_text(json.dumps(good))
        (gh / "bad/firmware/index.json").write_text(json.dumps(bad))

        pages = root / "pages"
        pages.mkdir()
        (pages / "old.js").write_bytes(subprocess.check_output(["git", "show", OLD_REF + ":game/web/ota.js"], cwd=REPO))
        cfg = {"micropython": a.micropython, "runner": str(GAME / "tests/mp_ota_step.py"),
               "flash": str(root / "flash"), "pristine": str(pristine), "gh": str(gh), "index": "good",
               "STEP": STEP, "DUEL": DUEL, "cap": CAP,
               "limits": {OLD: oldmod.MAX_FILES, STEP: newmod.MAX_FILES, DUEL: DUEL_MAX_FILES},
               "pages": {OLD: str(pages / "old.js"), STEP: str(GAME / "web/ota.js"),
                         DUEL: str(duel_tree / "game/web/ota.js")}}
        (root / "config.json").write_text(json.dumps(cfg))
        print("refs: 0.3.0 %s, duel %s; payloads: %s %d files %d B, %s %d files %d B; limits %s"
              % (old_sha, duel_sha, STEP, counts[STEP]["files"], counts[STEP]["bytes"], DUEL,
                 counts[DUEL]["files"], counts[DUEL]["bytes"], cfg["limits"]), flush=True)
        peak = 0
        for sc in a.only or SCENARIOS:
            out = subprocess.run(["node", GAME / "tests/ota_step_page.mjs", root / "config.json", sc],
                                 capture_output=True, text=True)
            if out.returncode:
                sys.stdout.write(out.stdout)
                sys.stderr.write(out.stderr)
                raise SystemExit("test_ota_step: %s FAILED" % sc)
            res = json.loads(out.stdout.strip().splitlines()[-1])
            peak = max(peak, res["heap"]["peak"])
            print("ok   %-8s %d puts, %d boots, heap peak %d B (signature check %d B, %d samples)%s" % (
                sc, res["puts"], res["boots"], res["heap"]["peak"], res["heap"]["sig"], res["heap"]["sig_samples"],
                "".join("\n       " + n for n in res["notes"])), flush=True)
        assert 0 < peak < CAP, peak
        print("test_ota_step: PASS (lv32 updater heap peak %d B, cap %d B)" % (peak, CAP), flush=True)
    finally:
        if a.keep:
            print("scratch kept:", root)
        else:
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
