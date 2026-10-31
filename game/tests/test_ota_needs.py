#!/usr/bin/env python3
"""Releases an older updater can't take (review 0.3.1-3 #3): tools/build_release.py --needs
and the index's "channels"/"heads", and tools/validate_firmware.py's rules for them. A ship
on 0.3.0 has an updater that takes at most 40 files, and its phone page reads only
channels[ch]: channels must stay on a release every ship can install, heads names the
newest, and a release with more files must name the one that brings a bigger updater.
Runs in a temp copy of the served tree; nothing is signed.

  python3 game/tests/test_ota_needs.py"""
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
ROOT = GAME.parent
CORE = GAME / "tools/fw/cores/lv-core-0.2.0-2661c2144844.json"
fails = 0


def check(what, ok, extra=""):
    global fails
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else "  %s" % (extra,)))
    fails += not ok


tmp = Path(tempfile.mkdtemp(prefix="lv-ota-needs-"))
serial = itertools.count()
try:
    for x in ("firmware", "src"):
        shutil.copytree(ROOT / x, tmp / x)
    for x in ("index.html", "styles.css", "favicon.svg"):
        shutil.copy(ROOT / x, tmp / x)
    index = tmp / "firmware/index.json"

    def source(name, n):
        """A game-firmware folder with n over-the-air files (main.py, n - 2 assets and the
        version.json build_release writes), plus boot.py, which never goes over the air."""
        d = tmp / "src-fw" / ("%s-%d" % (name, next(serial)))
        (d / "www").mkdir(parents=True)
        (d / "main.py").write_text("print('ship %s')\n" % name)
        (d / "boot.py").write_text("pass\n")
        for i in range(n - 2):
            (d / "www" / ("a%02d.txt" % i)).write_text("asset %d of %s\n" % (i, name))
        return d

    def build(version, n, *more):
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_release.py"), "--version", version,
                            "--channel", "test", "--label", "needs test " + version,
                            "--source", str(source(version, n)), "--frozen", str(CORE),
                            "--repo-root", str(tmp), "--date", "2026-10-30",
                            "--build-time", "2026-10-30T00:00:00Z", *more], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def idx():
        return json.loads(index.read_text())

    def validate():
        r = subprocess.run([sys.executable, str(ROOT / "tools/validate_firmware.py"), "--root", str(tmp)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    code, out = build("0.3.0-needs", 40)
    check("40 over-the-air files (boot.py left out) build without --needs", code == 0, out[-400:])
    entry = next(r for r in idx()["releases"] if r["version"] == "0.3.0-needs")
    check("no needs on it, and no heads while every channel's newest needs nothing",
          "needs" not in entry and "heads" not in idx() and idx()["channels"]["test"] == "0.3.0-needs", idx())
    code, out = build("0.3.1-updater", 38)
    check("the stepping stone builds without --needs", code == 0, out[-400:])
    before = index.read_text()
    code, out = build("0.3.1", 47)
    check("47 over-the-air files without --needs are refused, and say what to do",
          code != 0 and "47 over-the-air files" in out and "--needs" in out, out[-400:])
    check("the refusal writes nothing", index.read_text() == before
          and not (tmp / "firmware/releases/0.3.1").exists())
    for bad, why in (("0.3.2", "must be an older version"), ("0.3.1", "must be an older version"),
                     ("0.2.9-none", "publish it first"), ("0.0.2-coex", "publish it first")):
        code, out = build("0.3.1", 47, "--needs", bad)
        check("--needs %s is refused (%s)" % (bad, why),
              code != 0 and why in out and index.read_text() == before, out[-300:])
    code, out = build("0.3.1", 47, "--needs", "0.3.1-updater")
    check("with --needs 0.3.1-updater it builds", code == 0, out[-400:])
    i = idx()
    duel = next(r for r in i["releases"] if r["version"] == "0.3.1")
    check("the entry records needs", duel.get("needs") == "0.3.1-updater", duel)
    check("channels stays on the stepping stone, which pages up to 0.3.0 can install",
          i["channels"]["test"] == "0.3.1-updater", i["channels"])
    check("heads names the newest release on each channel", i.get("heads", {}).get("test") == "0.3.1"
          and i["heads"]["bench"] == i["channels"]["bench"], i.get("heads"))
    check("latest is untouched by test releases", i["latest"] == "0.0.2-coex", i["latest"])
    code, out = validate()
    check("validate_firmware accepts it", code == 0 and "heads {" in out, out[-600:])
    code, out = build("0.3.2", 47, "--needs", "0.3.1-updater")
    i = idx()
    check("a later big release moves heads; channels stays", code == 0 and i["heads"]["test"] == "0.3.2"
          and i["channels"]["test"] == "0.3.1-updater", (out[-300:], i["channels"], i.get("heads")))
    code, out = validate()
    check("validate_firmware accepts that too", code == 0, out[-600:])

    good = index.read_text()

    def entry_of(i, v):
        return next(r for r in i["releases"] if r["version"] == v)

    def broken(what, change, want):
        i = json.loads(good)
        change(i)
        index.write_text(json.dumps(i, indent=2) + "\n")
        code, out = validate()
        check("validate_firmware refuses " + what, code == 1 and want in out, out[-600:])
        index.write_text(good)

    broken("channels on a release with needs (a 0.3.0 page would offer what its ship refuses)",
           lambda i: i["channels"].update(test="0.3.2"), "channel test -> 0.3.2 needs 0.3.1-updater")
    broken("a release over 40 files without needs",
           lambda i: entry_of(i, "0.3.1").pop("needs"), "0.3.1: 47 over-the-air files, more than the 40")
    broken("needs that names no release", lambda i: entry_of(i, "0.3.1").update(needs="0.3.0-gone"),
           "needs '0.3.0-gone' is not a release")
    broken("needs that isn't older", lambda i: entry_of(i, "0.3.1").update(needs="0.3.2"), "which isn't older")
    broken("needs on another channel", lambda i: entry_of(i, "0.3.1").update(needs="0.0.2-coex"),
           "on another channel or core")
    broken("needs without heads", lambda i: i.pop("heads"), "heads has no test entry")
    broken("heads not on the newest release", lambda i: i["heads"].update(test="0.3.1"),
           "the newest test release is 0.3.2")
    broken("heads on another channel's release", lambda i: i["heads"].update(test="0.0.2-coex"),
           "is not a test release")
    broken("heads that isn't an object", lambda i: i.update(heads=["0.3.2"]), "heads must be an object")
    code, out = validate()
    check("the good index validates again", code == 0, out[-300:])
finally:
    shutil.rmtree(tmp)
print("test_ota_needs: %s" % ("%d FAILED" % fails if fails else "all ok"))
sys.exit(1 if fails else 0)
