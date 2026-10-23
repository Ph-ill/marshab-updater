#!/usr/bin/env python3
"""Phones playing on a ship while it syncs over BLE, with the board's heap measured.
Starts tests/mp_sync_heap.py --phone under MicroPython (the board side, one process) and
plays two phones against it from here (tests/phone_flow.py over real sockets, so the
phones' buffers aren't on the board's heap). Every answer is checked; the heap line and
RESULT come from the board side, with the 80,000 B cap at 32-bit.
  python3 tests/phone_heap.py MICROPYTHON [dir | frozen]      (from game/)"""
import asyncio
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]
os.chdir(ROOT)
import phone_flow as F            # noqa: E402
from lv import codes as K         # noqa: E402

DATA = "build/heap-data"


def main(argv):
    mp, mode = argv[0], argv[1:]
    os.makedirs(DATA, exist_ok=True)
    with open(DATA + "/crew.json", "w") as f:
        json.dump(K.make_config(["1234"] * 7 + [None], b"bench-salt-16-by"), f)
    p = subprocess.Popen([mp, "-X", "heapsize=512k", "tests/mp_sync_heap.py"] + mode + ["--phone"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    port = None
    for line in p.stdout:
        if line.startswith("PORT "):
            port = int(line.split()[1])
            break
        print(line, end="")
    fails = []
    if port is None:
        print(p.stdout.read())
        sys.exit("board side never started its server")
    assets = {n: open("build/" + n, "rb").read() for n in ("app.html.gz", "text.json.gz", "engage.json.gz")}

    async def phones():
        req = F.tcp(port)
        return await asyncio.gather(F.session(req, "heapA", 1, "1234", fails.append, assets, log=print),
                                    F.session(req, "heapB", 6, "1234", fails.append, assets, log=print))
    try:
        asyncio.run(phones())
    finally:
        open(DATA + "/done", "w").close()
    out = p.stdout.read()
    p.wait()
    print(out, end="")
    for f in fails:
        print("PHONE FAIL", f)
    if fails or p.returncode or "RESULT PASS" not in out:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
