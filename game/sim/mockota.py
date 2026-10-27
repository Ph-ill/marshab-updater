"""Over-the-air updates for the mock Pico (sim/mockserver.py ota=...), and a stand-in for the
GitHub side, so the phone's update screens can be clicked through and photographed.

  ota=0.2.0          the ship runs 0.2.0 on stable, core 0.2.0; GitHub offers 0.2.1
  ota=0.2.0,back     ... and the update "doesn't start": the ship comes back on 0.2.0, rolled back

The ship's half follows board/lvota.py's protocol (GET /api/ota, POST put/apply/cancel, the
409 {have} for a piece at the wrong place, 401 signed out) but doesn't check signatures or
hashes (tests/test_ota.py does that on the real module). /gh/... is what the page would get
from raw.githubusercontent.com: an index and a signed release.json, made here with the TEST
key (tools/ota/ed25519.py, seed 0..31), never the release key. The files are filler bytes.
"""
import base64
import hashlib
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools", "ota"))
import ed25519  # noqa: E402

TEST_SEED = bytes(range(32))
NEW = "0.2.1"


def release(core):
    rnd = random.Random(7)
    files = []
    for path, n in (("main.py", 9000), ("lvota.mpy", 7400), ("lvsig.mpy", 4900),
                    ("www/app.html.gz", 35000), ("version.json", 120)):
        files.append((path, bytes(rnd.getrandbits(8) for _ in range(n))))
    m = {"schema": 1, "project": "LongVoyage", "version": NEW, "channel": "stable", "core": core,
         "files": [[p, len(b), hashlib.sha256(b).hexdigest()] for p, b in files], "delete": []}
    mt = json.dumps(m, separators=(",", ":"))
    pub = ed25519.public_key(TEST_SEED)
    sig = ed25519.sign(TEST_SEED, b"LV-OTA-1\n" + hashlib.sha256(mt.encode()).digest())
    env = {"m": mt, "sig": base64.b64encode(sig).decode(), "kid": hashlib.sha256(pub).hexdigest()[:8]}
    rel = {"project": "LongVoyage", "version": NEW, "channel": "stable", "label": "Mock update",
           "frozen": {"requires": core}, "ota": env,
           "files": [{"path": p, "data": base64.b64encode(b).decode()} for p, b in files]}
    idx = {"latest": NEW, "channels": {"stable": NEW},
           "releases": [{"version": NEW, "channel": "stable", "path": "/firmware/releases/%s/release.json" % NEW,
                         "frozen": core, "ota": env["kid"]},
                        {"version": "0.2.0", "channel": "stable", "path": "/firmware/releases/0.2.0/release.json",
                         "frozen": core}]}
    return idx, rel


class MockOta:
    def __init__(self, arg):
        p = arg.split(",")
        self.v, self.back, self.core = p[0], "back" in p[1:], "2661c2144844"
        self.idx, self.rel = release(self.core)
        self.env = b""
        self.n = 0
        self.m = None
        self.have = []
        self.down_until = 0
        self.last = None

    def down(self):
        return time.monotonic() < self.down_until

    def status(self):
        st = {"ota": 1, "v": self.v, "ch": "stable", "core": self.core, "chunk": 1024,
              "free": 600000, "last": self.last, "phase": None, "staged": None}
        if self.m:
            st["staged"] = {"v": self.m["version"], "have": list(self.have),
                            "sizes": [f[1] for f in self.m["files"]]}
        return st

    def put(self, q, body):
        f, o = int(q.get("f", ["-1"])[0]), int(q.get("o", ["-1"])[0])
        if f == 0:
            if o == 0:
                self.env, self.n, self.m = b"", int(q.get("n", ["0"])[0]), None
            if o != len(self.env):
                return 409, {"err": "wrong place", "have": len(self.env)}
            self.env += body
            if len(self.env) < self.n:
                return 200, {"have": len(self.env)}
            m = json.loads(json.loads(self.env)["m"])
            self.m, self.have = m, [0] * len(m["files"])
            return 200, {"have": len(self.env), "done": True, "v": m["version"]}
        if not self.m or not 1 <= f <= len(self.have):
            return 409, {"err": "send the signature first"}
        size = self.m["files"][f - 1][1]
        if o != self.have[f - 1]:
            return 409, {"err": "wrong place", "have": self.have[f - 1]}
        if o + len(body) > size:
            return 400, {"err": "more than the file's size"}
        self.have[f - 1] += len(body)
        time.sleep(0.04)   # a Pico takes a while per piece
        return 200, {"have": self.have[f - 1], "done": self.have[f - 1] == size}

    def apply(self):
        if not self.m or self.have != [f[1] for f in self.m["files"]]:
            return 409, {"err": "the update isn't all here yet"}
        prev, v = self.v, self.m["version"]
        self.down_until = time.monotonic() + 6
        if self.back:
            self.last = {"result": "rolled back", "v": v, "prev": prev, "boots": 2}
        else:
            self.v, self.last = v, {"result": "installed", "v": v, "prev": prev, "boots": 1}
        self.m, self.env = None, b""
        return 200, {"ok": True, "v": v, "restart_ms": 1500}
