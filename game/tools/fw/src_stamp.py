#!/usr/bin/env python3
"""A digest of everything tools/board_build.sh builds build/board/ and build/board-fw/ from.

board_build.sh writes it to build/board-src.stamp once both trees are built; the heap
checks (tests/phone_heap.py) compare it with the sources before measuring, so a run never
measures, or passes on, board files older than the code (fix round 0.3.1-11: a heap
fixture passed for half an hour against a build/board-fw from before a view() change).
"""
import hashlib
import os
import sys

GAME = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TREES = ("board", "lv", "content", "web", "tools/fw")
FILES = ("tools/lvc.py", "tools/lve.py", "tools/board_build.sh")
STAMP = "build/board-src.stamp"


def stamp(root=GAME):
    h = hashlib.sha256()
    paths = list(FILES)
    for top in TREES:
        for dp, dns, fns in os.walk(os.path.join(root, top)):
            dns[:] = sorted(d for d in dns if d != "__pycache__")
            for n in fns:
                if not n.endswith(".pyc"):
                    paths.append(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/"))
    for p in sorted(paths):
        with open(os.path.join(root, p), "rb") as f:
            data = f.read()
        h.update(p.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def fresh(root=GAME):
    try:
        with open(os.path.join(root, STAMP)) as f:
            return f.read().strip() == stamp(root)
    except OSError:
        return False


if __name__ == "__main__":
    print(stamp())
    sys.exit(0)
