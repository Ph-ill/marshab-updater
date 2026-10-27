#!/usr/bin/env python3
"""Phones playing on a ship while it syncs over BLE, with the board's heap measured.
Starts tests/mp_sync_heap.py --phone under MicroPython (the board side, one process) and
plays two phones against it from here (tests/phone_flow.py over real sockets, so the
phones' buffers aren't on the board's heap). Every answer is checked; the heap line and
RESULT come from the board side, with the 80,000 B cap at 32-bit.
  python3 tests/phone_heap.py MICROPYTHON [dir | frozen] [--led] [--bat] [--ota]  (from game/)
--ota: a third phone uploads a signed update (the game firmware's own files as a newer
version, signed with a test key) in pieces while the two play, the way web/ota.js does:
a refused envelope first, a piece at a wrong offset, then everything; the board checks
the signature and each file, and the heap peak includes all of it. Then it cancels
(applying restarts the board: tests/test_ota.py covers that)."""
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
OTA_MOD = "build/heap-ota-mod"
OTA_DIR = "build/heap-ota"


def ota_setup():
    """board/lvota.py with a test key and its own staging dir, compiled like the board's
    modules; and a signed update of build/board-fw/'s files. -> (envelope bytes, [file bytes])."""
    import base64
    import hashlib
    import shutil
    sys.path.insert(0, os.path.join(ROOT, "tools", "ota"))
    import ed25519
    seed = hashlib.sha256(b"heap test key, not the release key").digest()
    pub = ed25519.public_key(seed)
    kid = hashlib.sha256(pub).hexdigest()[:8]
    src = open("board/lvota.py").read()
    a = src.index("KEYS = {")
    b = src.index("\n", a)
    src = src[:a] + 'KEYS = {"%s": unhexlify("%s")}' % (kid, pub.hex()) + src[b:]
    src = src.replace('OTA = "ota"\n', 'OTA = "%s"\n' % OTA_DIR, 1)
    shutil.rmtree(OTA_MOD, ignore_errors=True)
    shutil.rmtree(OTA_DIR, ignore_errors=True)
    os.makedirs(OTA_MOD)
    os.makedirs(OTA_DIR)
    open(OTA_MOD + "/lvota.py", "w").write(src)
    mpyc = os.environ.get("MPY_CROSS")
    if mpyc:
        subprocess.run([mpyc, "-O3", "-o", OTA_MOD + "/lvota.mpy", OTA_MOD + "/lvota.py"], check=True)
        os.remove(OTA_MOD + "/lvota.py")
    files = []
    for dp, _, fs in os.walk("build/board-fw"):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, "build/board-fw").replace(os.sep, "/")
            if rel != "boot.py" and not rel.startswith("lvboot."):     # never over the air
                files.append((rel, open(p, "rb").read()))
    files.sort()
    core = json.load(open("build/frozen-core.json"))["core"]
    m = {"schema": 1, "project": "LongVoyage", "version": "9.9.9-heap", "channel": "test", "core": core,
         "files": [[p, len(b), hashlib.sha256(b).hexdigest()] for p, b in files], "delete": []}
    t = json.dumps(m, separators=(",", ":"))
    sig = ed25519.sign(seed, b"LV-OTA-1\n" + hashlib.sha256(t.encode()).digest())
    env = json.dumps({"m": t, "sig": base64.b64encode(sig).decode(), "kid": kid}).encode()
    bad = json.dumps({"m": t.replace("9.9.9-heap", "9.9.8-heap"), "sig": base64.b64encode(sig).decode(),
                      "kid": kid}).encode()
    return env, bad, [b for _, b in files]


async def ota_upload(req, env, bad, files, fail, log):
    """What web/ota.js does: sign in, look, send the envelope and the files in pieces."""
    def js(b):
        return json.loads(b) if b else {}
    s, _, b = await req("POST", "/api/login", json.dumps({"crew": 3, "pin": "1234"}).encode(), {})
    tok = js(b).get("token")
    if s != 200 or not tok:
        return fail("ota: login %d %s" % (s, b))
    H = {"X-Crew-Token": tok}
    s, _, b = await req("GET", "/api/ota", None, {})
    st = js(b)
    if s != 200 or not st.get("ota") or not st.get("chunk"):
        return fail("ota: status %d %s" % (s, b))
    n = st["chunk"]
    s, _, b = await req("POST", "/api/ota/put?f=0&n=%d&o=0" % len(bad), bad[:n], {})
    if s != 401:
        fail("ota: put signed out: %d" % s)

    async def send(f, data, extra=""):
        o = 0
        while o < len(data) or (o == 0 and not data):
            s, _, b = await req("POST", "/api/ota/put?f=%d%s&o=%d" % (f, extra, o), data[o:o + n], H)
            j = js(b)
            if s == 409 and j.get("have") is not None:
                o = j["have"]
                continue
            if s != 200:
                return s, j
            o = j.get("have", o + n)
            if j.get("done") or not data:
                break
        return 200, j
    s, j = await send(0, bad, "&n=%d" % len(bad))
    if s != 403 or "signature" not in j.get("err", ""):
        fail("ota: a tampered envelope: %d %s" % (s, j))
    s, j = await send(0, env, "&n=%d" % len(env))
    if s != 200:
        return fail("ota: envelope %d %s" % (s, j))
    # a piece at the wrong offset: 409 with where to carry on
    s, _, b = await req("POST", "/api/ota/put?f=1&o=%d" % (n * 3), files[0][:n], H)
    if s != 409 or js(b).get("have") != 0:
        fail("ota: wrong offset %d %s" % (s, b))
    for i, data in enumerate(files):
        s, j = await send(i + 1, data)
        if s != 200:
            return fail("ota: file %d: %d %s" % (i + 1, s, j))
    s, _, b = await req("GET", "/api/ota", None, {})
    st = js(b).get("staged") or {}
    if st.get("v") != "9.9.9-heap" or st.get("have") != st.get("sizes"):
        fail("ota: staged %s" % st)
    s, _, b = await req("POST", "/api/ota/cancel", b"", H)
    if s != 200:
        fail("ota: cancel %d" % s)
    log("ota: uploaded %d files, %d B in %d B pieces, signature and checksums checked on the board" % (
        len(files), sum(len(x) for x in files), n))


def main(argv):
    mp, mode = argv[0], argv[1:]
    os.makedirs(DATA, exist_ok=True)
    ota = ota_setup() if "--ota" in mode else None
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
        jobs = [F.session(req, "heapA", 1, "1234", fails.append, assets, log=print),
                F.session(req, "heapB", 6, "1234", fails.append, assets, log=print)]
        if ota:
            jobs.append(ota_upload(req, ota[0], ota[1], ota[2], fails.append, print))
        return await asyncio.gather(*jobs)
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
