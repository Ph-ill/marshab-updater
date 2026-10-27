#!/usr/bin/env python3
"""The game firmware's split: lv/, the board modules and the pack frozen, files override.
 - lv/__init__.py, via the frozen lvfrozen.py (tools/fw/lvfrozen_rt.py), loads
   lvx/<name>.mpy|.py over lv.<name> (a fixed core module without reflashing), in
   dependency order; a broken override falls back to the built-in one. Without lvfrozen
   (stock MicroPython, CPython) lvx/ is ignored.
 - lvfrozen.py (tools/fw/gen_lvfrozen.py) names the frozen core; lv.describe() reports
   "frozen lv-core <version> (core <hash>), overrides: [...]", and a /lv directory that
   hides the frozen package is called out.
 - tools/fw/manifest.py freezes lv/, lvfrozen.py and, since lv-core 0.2.0, the board
   modules (gen_lvfrozen.BOARD) and the story pack (lvpackdata.py). main.py, the web
   pages and engage.bin stay files. A /<module>.mpy or /pack.bin file replaces the frozen
   one (a hotfix); describe() lists those as "board files", and the core hash covers them.
Under CPython always; with LV_FROZEN_MP (tools/build_firmware.sh unix32) and MPY_CROSS,
also on the frozen interpreter with .mpy overrides, as on a board.
  python3 tests/test_fw_split.py      (from game/)"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FROZEN_MP = os.environ.get("LV_FROZEN_MP")
MPY_CROSS = os.environ.get("MPY_CROSS")

def rd(p):
    with open(p) as f:
        return f.read()


def rd_b(p):
    with open(p, "rb") as f:
        return f.read()


def wr(p, s):
    with open(p, "w") as f:
        f.write(s)


PROBE = """
import sys
import lv
print("DESCRIBE " + lv.describe())
from lv.engage import Engage
import lv.engage as E
print("ENGAGE", getattr(E, "MARK", "builtin"))
from lv import sync
print("SYNC", getattr(sync, "MARK", "builtin"))
from lv.engine import Engine
from lv import engine
print("ENGINE", getattr(engine, "MARK", "builtin"))
print("LEAK", [n for n in ("engage", "sync", "engine") if n in sys.modules])
"""


def write_overrides(d, compile_mpy=False):
    os.makedirs(os.path.join(d, "lvx"))
    for name, extra in (("engage", 'MARK = "override"\n'), ("engine", 'MARK = "override"\n')):
        src = rd(os.path.join(ROOT, "lv", name + ".py")) + extra
        p = os.path.join(d, "lvx", name + ".py")
        wr(p, src)
        if compile_mpy:
            subprocess.run([MPY_CROSS, "-o", p[:-3] + ".mpy", p], check=True)
            os.remove(p)
    wr(os.path.join(d, "lvx", "sync.py"), 'raise ValueError("broken on purpose")\n')
    wr(os.path.join(d, "probe.py"), PROBE)


class Split(unittest.TestCase):
    def run_probe(self, cmd, d, path=ROOT):
        p = subprocess.run(cmd + ["probe.py"], cwd=d, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=path))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_cpython_overrides(self):
        subprocess.run([sys.executable, "tools/fw/gen_lvfrozen.py"], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        with tempfile.TemporaryDirectory() as d:
            write_overrides(d)
            out = self.run_probe([sys.executable], d)     # no lvfrozen: lvx/ is ignored
            self.assertIn("DESCRIBE no frozen core", out)
            self.assertIn("ENGAGE builtin", out)
            self.assertNotIn("override", out)
            # lvfrozen importable (the loader, as frozen on the board); lv/ is on the path
            # too here, which on a board would hide the frozen package: describe says so.
            out = self.run_probe([sys.executable], d, ROOT + os.pathsep + os.path.join(ROOT, "build", "fw"))
            self.assertIn("HIDDEN by a /lv directory", out)
            self.assertIn("override sync failed", out)
            self.assertIn("ENGAGE override", out)
            self.assertIn("ENGINE override", out)
            self.assertIn("SYNC builtin", out)
            self.assertIn("LEAK []", out)

    def test_manifest(self):
        m = rd(os.path.join(ROOT, "tools", "fw", "manifest.py"))
        calls = re.findall(r'^(\w+)\("([^"]+)"', m, re.M)
        sys.path.insert(0, os.path.join(ROOT, "tools", "fw"))
        import gen_lvfrozen as G
        self.assertEqual(calls, [("include", "$(BOARD_DIR)/manifest.py"), ("package", "lv"),
                                 ("module", "lvfrozen.py"), ("module", "lvpackdata.py")]
                         + [("module", b + ".py") for b in G.BOARD])
        # every board module but main.py and boot.py (the boot entries) is frozen
        self.assertEqual(sorted(G.BOARD), sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "board"))
                                                 if f.endswith(".py") and f not in ("main.py", "boot.py")))
        subprocess.run([sys.executable, "tools/fw/gen_lvfrozen.py"], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        g = {}
        exec(rd(os.path.join(ROOT, "build", "fw", "lvfrozen.py")), g)
        want = sorted(["lv"] + ["lv." + f[:-3] for f in os.listdir(os.path.join(ROOT, "lv"))
                                if f.endswith(".py") and f != "__init__.py"])
        self.assertEqual(sorted(g["MODULES"]), want)
        self.assertRegex(g["CORE"], r"^[0-9a-f]{12}$")
        self.assertEqual(tuple(g["BOARD"]), G.BOARD)
        self.assertRegex(g["PACK"], r"^[0-9a-f]{12}$")
        p = {}
        exec(rd(os.path.join(ROOT, "build", "fw", "lvpackdata.py")), p)
        self.assertEqual(p["DATA"], rd_b(os.path.join(ROOT, "build", "pack.bin")))

    def test_core_hash_covers_board_and_pack(self):
        """Changing a board module or the pack changes the core hash (the updater matches
        releases to firmware by it); changed_files() names what a release must ship."""
        sys.path.insert(0, os.path.join(ROOT, "tools", "fw"))
        import gen_lvfrozen as G
        import changed_modules as CM
        import json
        base = G.core_hash()
        saved = (G.ROOT, G.PACK, G.RT)
        with tempfile.TemporaryDirectory() as d:
            for sub in ("lv", "board"):
                shutil.copytree(os.path.join(ROOT, sub), os.path.join(d, sub))
            os.makedirs(os.path.join(d, "build"))
            shutil.copy(G.PACK, os.path.join(d, "build", "pack.bin"))
            try:
                G.ROOT, G.PACK = d, os.path.join(d, "build", "pack.bin")
                self.assertEqual(G.core_hash(), base, "a copy hashes the same")
                with open(os.path.join(d, "board", "lvweb.py"), "a") as f:
                    f.write("\n# fixed\n")
                h1 = G.core_hash()
                self.assertNotEqual(h1, base)
                with open(G.PACK, "ab") as f:
                    f.write(b"\0")
                self.assertNotEqual(G.core_hash(), h1)
            finally:
                G.ROOT, G.PACK, G.RT = saved
            cores = sorted(f for f in os.listdir(os.path.join(ROOT, "tools", "fw", "cores")) if f.endswith(".json"))
            with open(os.path.join(ROOT, "tools", "fw", "cores", cores[-1])) as f:
                core = json.load(f)
            # board modules newer than the newest core (the OTA ones after 0.2.0) ship as files too
            # ...and the frozen ones fixed since (lvbatt: the VCELL-not-ready fix, ota-hwfix)
            fixed = ("lvbatt",)
            new = [b + ".mpy" for b in G.BOARD if b not in core["board"] or b in fixed]
            self.assertEqual(CM.changed_files(core, d),
                             [b + ".mpy" for b in G.BOARD if b not in core["board"] or b in fixed or b == "lvweb"]
                             + ["pack.bin"])
            self.assertEqual(CM.changed_files(core), new, "otherwise board/ and the pack match the newest core")
            old = {"id": "lv-core", "version": "0.1.0", "core": "f1b383588e79", "modules": core["modules"],
                   "sha256": {k: v for k, v in core["sha256"].items() if k.startswith("lv")}}
            self.assertEqual(CM.changed_files(old), [b + ".mpy" for b in G.BOARD] + ["pack.bin"],
                             "a 0.1.0 core froze no board modules: a release ships them all")

    def test_partial_overrides(self):
        """A partial release ships only the core modules changed since the flashed core."""
        sys.path.insert(0, os.path.join(ROOT, "tools", "fw"))
        import changed_modules as CM
        cores = sorted(f for f in os.listdir(os.path.join(ROOT, "tools", "fw", "cores")) if f.endswith(".json"))
        self.assertTrue(cores, "tools/fw/cores/ holds the flashed core's manifest")
        import json
        with open(os.path.join(ROOT, "tools", "fw", "cores", cores[-1])) as f:
            core = json.load(f)
        with tempfile.TemporaryDirectory() as d:
            lvd = os.path.join(d, "lv")
            shutil.copytree(os.path.join(ROOT, "lv"), lvd)
            out, bad = CM.changed(core, lvd)
            self.assertEqual((out, bad), ([], []), "lv/ matches the newest core in tools/fw/cores/")
            with open(os.path.join(lvd, "engine.py"), "a") as f:
                f.write("\n# fixed\n")
            with open(os.path.join(lvd, "sync.py"), "a") as f:
                f.write("\n# fixed\n")
            self.assertEqual(CM.changed(core, lvd), (["engine", "sync"], []))
            with open(os.path.join(lvd, "newmod.py"), "w") as f:
                f.write("X = 1\n")
            self.assertEqual(CM.changed(core, lvd)[1], ["lv.newmod"])
            os.remove(os.path.join(lvd, "newmod.py"))
            with open(os.path.join(lvd, "__init__.py"), "a") as f:
                f.write("\n")
            self.assertEqual(CM.changed(core, lvd)[1], ["lv"])

    @unittest.skipUnless(FROZEN_MP and MPY_CROSS, "set LV_FROZEN_MP and MPY_CROSS")
    def test_frozen_interpreter(self):
        with tempfile.TemporaryDirectory() as d:
            wr(os.path.join(d, "probe.py"), PROBE)
            out = self.run_probe([FROZEN_MP], d)          # nothing else on the filesystem
            self.assertRegex(out, r"DESCRIBE frozen lv-core \S+ \(core [0-9a-f]{12}\), overrides: \[\]")
            self.assertIn("ENGAGE builtin", out)
        with tempfile.TemporaryDirectory() as d:
            write_overrides(d, compile_mpy=True)
            out = self.run_probe([FROZEN_MP], d)
            self.assertRegex(out, r"overrides: \[engine, engage\]")
            self.assertIn("ENGAGE override", out)
            self.assertIn("ENGINE override", out)
            self.assertIn("SYNC builtin", out)
            self.assertIn("LEAK []", out)
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(os.path.join(ROOT, "lv"), os.path.join(d, "lv"))   # a stale full install
            wr(os.path.join(d, "probe.py"), PROBE)
            out = self.run_probe([FROZEN_MP], d)
            self.assertIn("HIDDEN by a /lv directory", out)
        board_probe = (PROBE.split("from lv.engage")[0] +
                       "import lvship\nprint('GLUE', getattr(lvship, 'MARK', 'frozen'))\n"
                       "p, src = lvship.pack_for()\nprint('PACK', src, p.ncards > 0)\n")
        with tempfile.TemporaryDirectory() as d:           # lv-core 0.2.0: all frozen
            wr(os.path.join(d, "probe.py"), board_probe)
            out = self.run_probe([FROZEN_MP], d)
            self.assertRegex(out, r"overrides: \[\], board files: \[\]")
            self.assertIn("GLUE frozen", out)
            self.assertIn("PACK frozen True", out)
        with tempfile.TemporaryDirectory() as d:           # hotfix files replace them
            p = os.path.join(d, "lvship.py")
            wr(p, rd(os.path.join(ROOT, "board", "lvship.py")) + 'MARK = "file"\n')
            subprocess.run([MPY_CROSS, "-O3", "-o", p[:-3] + ".mpy", p], check=True)
            os.remove(p)
            shutil.copy(os.path.join(ROOT, "build", "pack.bin"), os.path.join(d, "pack.bin"))
            wr(os.path.join(d, "probe.py"), board_probe)
            out = self.run_probe([FROZEN_MP], d)
            self.assertRegex(out, r"board files: \[lvship, pack.bin\]")
            self.assertIn("GLUE file", out)
            self.assertIn("PACK file True", out)
        board_probe = (PROBE.split("from lv.engage")[0] +
                       "import lvship\nprint('GLUE', getattr(lvship, 'MARK', 'frozen'))\n"
                       "p, src = lvship.pack_for()\nprint('PACK', src, p.ncards > 0)\n")
        with tempfile.TemporaryDirectory() as d:           # lv-core 0.2.0: all frozen
            wr(os.path.join(d, "probe.py"), board_probe)
            out = self.run_probe([FROZEN_MP], d)
            self.assertRegex(out, r"overrides: \[\], board files: \[\]")
            self.assertIn("GLUE frozen", out)
            self.assertIn("PACK frozen True", out)
        with tempfile.TemporaryDirectory() as d:           # hotfix files replace them
            p = os.path.join(d, "lvship.py")
            wr(p, rd(os.path.join(ROOT, "board", "lvship.py")) + 'MARK = "file"\n')
            subprocess.run([MPY_CROSS, "-O3", "-o", p[:-3] + ".mpy", p], check=True)
            os.remove(p)
            shutil.copy(os.path.join(ROOT, "build", "pack.bin"), os.path.join(d, "pack.bin"))
            wr(os.path.join(d, "probe.py"), board_probe)
            out = self.run_probe([FROZEN_MP], d)
            self.assertRegex(out, r"board files: \[lvship, pack.bin\]")
            self.assertIn("GLUE file", out)
            self.assertIn("PACK file True", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
