#!/usr/bin/env python3
"""Sign-in rules end to end against the mock Pico's HTTP API (the board will serve the same
API): codes set up front, 'not set up', five-try lockout, the phone remembered for the rest of
the flight day and only by the same IP + browser, sign-out forgets it.

  python3 tests/mock_check.py      (from game/, after python3 web/build.py)
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim import mockserver as M   # noqa: E402
from lv import codes as K          # noqa: E402

M.G = M.Game(8)
M.G.book = K.CodeBook(K.make_config(["1234", "2468", "1357", None, "0000", "1111", "2222", "3333"], b"0123456789abcdef"))
srv = M.ThreadingHTTPServer(("127.0.0.1", 0), M.H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def call(path, body=None, ua="phone-a", tok=""):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"User-Agent": ua, "X-Crew-Token": tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(cond, what):
    if not cond:
        print("FAIL:", what)
        sys.exit(1)


s, j = call("/api/crew?day=8")
check(j["set"] == [True, True, True, False, True, True, True, True], "crew list shows who is set up (all 8)")
check(call("/api/me?day=8")[0] == 401, "unknown phone isn't signed in")
check(call("/api/login?day=8", {"crew": 3, "pin": "1234"})[0] == 409, "no code set up -> 409")
check(call("/api/login?day=8", {"crew": 0, "pin": "12x4"})[0] == 400, "non-digits -> 400")
s, j = call("/api/login?day=8", {"crew": 7, "pin": "3333"}, ua="phone-m")
check(s == 200 and j["crew"] == 7, "Marco (crew 7, ship 8) signs in")
s, st = call("/api/state?day=8", tok=j["token"])
check(s == 200, "Marco's token works")
check(len(st["best"]) == len(st["bestb"]) == 8 and all(b != c for c, b in enumerate(st["best"])),
      "state has each astronaut's closest crewmate and that bond (epilogue fallback)")
check(call("/api/login?day=8", {"crew": 8, "pin": "1234"})[0] == 400, "crew 8 doesn't exist -> 400")

s, j = call("/api/login?day=8", {"crew": 0, "pin": "1234"})
check(s == 200 and j["crew"] == 0 and j["first"] is True, "right code signs in, first time")
check(call("/api/state?day=8", tok=j["token"])[0] == 200, "token works")
s, j = call("/api/me?day=8")
check(s == 200 and j["crew"] == 0 and j["first"] is False, "same phone, same day: remembered")
check(call("/api/me?day=8", ua="phone-b")[0] == 401, "another browser on the same IP isn't")
check(call("/api/me?day=9")[0] == 401, "next flight day: forgotten")
check(call("/api/me?day=8")[0] == 401, "and it stays forgotten")

s, j = call("/api/login?day=9", {"crew": 0, "pin": "1234"})
check(s == 200 and j["first"] is False, "second sign-in isn't 'first'")
call("/api/logout?day=9", {}, tok=j["token"])
check(call("/api/me?day=9")[0] == 401, "sign out forgets the phone")
check(call("/api/state?day=9", tok=j["token"])[0] == 401, "and drops the token")

lefts = [call("/api/login?day=9", {"crew": 1, "pin": "0000"}, ua="phone-c")[1].get("left") for _ in range(4)]
check(lefts == [4, 3, 2, 1], "wrong codes count down: %r" % lefts)
s, j = call("/api/login?day=9", {"crew": 1, "pin": "0000"}, ua="phone-c")
check(s == 429 and j["wait"] == 300, "fifth wrong code locks for 5 minutes")
s, j = call("/api/login?day=9", {"crew": 1, "pin": "2468"}, ua="phone-d")
check(s == 429, "locked even with the right code, from any phone")
check(call("/api/login?day=9", {"crew": 2, "pin": "1357"}, ua="phone-d")[0] == 200, "other names unaffected")
srv.shutdown()
print("sign-in: codes, lockout, remembered phone and sign-out ok")
