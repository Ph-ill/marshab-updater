#!/usr/bin/env python3
"""What changed since a frozen core: the files a partial release ships on top of it.

  python3 tools/fw/changed_modules.py CORE.json [LV_DIR]
      -> the lvx/ overrides: "engine sync" (may be empty)
  python3 tools/fw/changed_modules.py --files CORE.json [GAME_DIR]
      -> the top-level files: "lvship.mpy pack.bin" (may be empty)

CORE.json is what tools/build_firmware.sh wrote for the flashed .uf2 (tools/fw/cores/).
Core modules: exits 1 if lv/__init__.py changed or a module was added or removed: an
override can't do that, it takes a new firmware.
Top-level files (--files): every board module (tools/fw/gen_lvfrozen.py BOARD) whose
source differs from the frozen one, or that the core doesn't freeze at all (lv-core 0.1.0
froze none: then all of them), as <name>.mpy, and pack.bin if build/pack.bin differs from
the frozen pack (or the core has none). On the board a file is found before the frozen
module, so these replace exactly what changed; the updater removes the rest."""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def changed(core, lv_dir="lv"):
    out, bad = [], []
    for f in sorted(os.listdir(lv_dir)):
        if not f.endswith(".py"):
            continue
        m = "lv" if f == "__init__.py" else "lv." + f[:-3]
        if core["sha256"].get(m) == _sha(os.path.join(lv_dir, f)):
            continue
        if m == "lv" or m not in core["sha256"]:
            bad.append(m)
        else:
            out.append(m[3:])
    gone = [m for m in core["sha256"] if m.startswith("lv.")
            and not os.path.exists(os.path.join(lv_dir, m[3:] + ".py"))]
    return out, bad + gone


def changed_files(core, game_dir=None, board=None):
    """[top-level file] a release on this core has to ship: <board module>.mpy for each
    board module not frozen as it is now, and pack.bin if the pack isn't."""
    if game_dir is None:
        game_dir = os.path.dirname(os.path.dirname(HERE))
    if board is None:
        sys.path.insert(0, HERE)
        try:
            import gen_lvfrozen
        finally:
            sys.path.pop(0)
        board = gen_lvfrozen.BOARD
    sha = core.get("sha256", {})
    frozen = set(core.get("board") or ())
    out = [m + ".mpy" for m in board
           if m not in frozen or sha.get(m) != _sha(os.path.join(game_dir, "board", m + ".py"))]
    pack = os.path.join(game_dir, "build", "pack.bin")
    if not core.get("pack") or sha.get("pack.bin") != _sha(pack):
        out.append("pack.bin")
    return out


def main(argv):
    if argv and argv[0] == "--files":
        core = json.load(open(argv[1]))
        print(" ".join(changed_files(core, argv[2] if len(argv) > 2 else None)))
        return
    core = json.load(open(argv[0]))
    out, bad = changed(core, argv[1] if len(argv) > 1 else "lv")
    if bad:
        sys.exit("%s changed since core %s: an lvx/ override can't replace the package, add or "
                 "remove a module; build a new firmware (tools/build_firmware.sh)" % (", ".join(bad), core["core"]))
    print(" ".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
