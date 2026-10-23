#!/usr/bin/env python3
"""Which core modules changed since a frozen core: the lvx/ overrides a partial release ships.

  python3 tools/fw/changed_modules.py CORE.json [LV_DIR]   -> "engine sync" (may be empty)

CORE.json is what tools/build_firmware.sh wrote for the flashed .uf2 (tools/fw/cores/).
Exits 1 if lv/__init__.py changed or a module was added: an override can't do that, it
takes a new firmware."""
import hashlib
import json
import os
import sys


def changed(core, lv_dir="lv"):
    out, bad = [], []
    for f in sorted(os.listdir(lv_dir)):
        if not f.endswith(".py"):
            continue
        m = "lv" if f == "__init__.py" else "lv." + f[:-3]
        with open(os.path.join(lv_dir, f), "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        if core["sha256"].get(m) == sha:
            continue
        if m == "lv" or m not in core["sha256"]:
            bad.append(m)
        else:
            out.append(m[3:])
    gone = [m for m in core["sha256"] if m != "lv" and not os.path.exists(os.path.join(lv_dir, m[3:] + ".py"))]
    return out, bad + gone


def main(argv):
    core = json.load(open(argv[0]))
    out, bad = changed(core, argv[1] if len(argv) > 1 else "lv")
    if bad:
        sys.exit("%s changed since core %s: an lvx/ override can't replace the package, add or "
                 "remove a module; build a new firmware (tools/build_firmware.sh)" % (", ".join(bad), core["core"]))
    print(" ".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
