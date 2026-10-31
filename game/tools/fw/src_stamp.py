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


def ensure(root=GAME):
    """Measure today's board code, never a build/board-fw left from older sources: rebuild
    it (tools/board_build.sh) when it is stale, refuse if it still doesn't match. Shared by
    every heap check (tests/phone_heap.py, mp_sync_heap.py, mp_safe_heap.py: review
    0.3.1-10 #6); the MicroPython ones run it as `python3 tools/fw/src_stamp.py --ensure`."""
    import subprocess
    if fresh(root):
        return
    print("build/board-fw is older than the sources: rebuilding (tools/board_build.sh)")
    sys.stdout.flush()
    subprocess.run(["sh", "tools/board_build.sh"], check=True, stdout=subprocess.DEVNULL, cwd=root)
    if not fresh(root):
        sys.exit("build/board-fw still does not match the sources after tools/board_build.sh")


if __name__ == "__main__":
    if sys.argv[1:] == ["--ensure"]:
        ensure()
    else:
        print(stamp())
    sys.exit(0)
