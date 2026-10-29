#!/usr/bin/env python3
"""R2: a first, pre-launch phone clock must not deadlock sign-in or normal OTA.

Adapted from the review's probe_clock_gate.py; exercise the production gate and
real Ship/Clock/Calendar/Phone/Server classes, not an imitation of authorization.
Run from game/: python3 tests/test_clock_auth.py
"""
import ast
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "board"), str(ROOT / "tests/fakeble")]
sys.dont_write_bytecode = True
os.chdir(ROOT)

import lvdays
import lvota
import lvship
import lvweb
from lv import codes as K
from lv.clock import Clock

# Importing main.py boots the board. Extract its actual gate as the review did.
MAIN = ROOT / "board/main.py"
tree = ast.parse(MAIN.read_text(), str(MAIN))
nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
         and n.name in ("_Hdr", "clock_gate")]
gate = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN), "exec"), gate)


class Request:
    def __init__(self, method, path, date="2026-10-29T12:00:00", token=None, pin="1234"):
        self.method, self.path, self.q = method, path, {}
        self.body = json.dumps({"crew": 0, "pin": pin}).encode()
        timestamp = dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc)
        self.headers = {"x-phone-time": str(int(timestamp.timestamp() * 1000)),
                        "x-phone-tz": "0", "user-agent": "correct-phone"}
        if token is not None:
            self.headers["x-crew-token"] = token

    def header(self, name):
        return self.headers.get(name)

    def phone(self):
        return "10.0.0.2|" + self.headers["user-agent"]


class Writer:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data.encode() if isinstance(data, str) else data)

    async def drain(self):
        pass


class ClockAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "web/build.py"], check=True,
                       stdout=subprocess.DEVNULL)

    def setUp(self):
        cfg = lvship.load_config("/nonexistent")
        cfg["launch_date"] = "2026-10-29"
        self.ship = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None,
                                radio=False, days=lvdays.Days())
        self.ship.clock = Clock(ticks=lambda: 0)
        self.ship.cal.clock = self.ship.clock
        self.web = lvweb.Server(self.ship, root="build/", say=lambda s: None)
        self.phone = self.web.get_phone()
        self.phone.book = K.CodeBook(K.make_config(["1234"] * 8, b"clock-auth-test!"))
        gate["clock_gate"](self.web)

    def call(self, req, ota=False):
        writer = Writer()
        if ota:
            asyncio.run(lvota.api(self.web, req, writer))
        else:
            asyncio.run(self.web.route(req, writer))
        head, body = bytes(writer.data).split(b"\r\n\r\n", 1)
        return int(head.split()[1]), json.loads(body)

    def first_wrong_clock(self):
        req = Request("GET", "/api/crew", date="2026-10-28T12:00:00")
        self.assertFalse(self.ship.clock.known())
        status, body = self.call(req)
        self.assertEqual((status, body["day"]), (200, 0))
        self.assertTrue(self.ship.clock.known())
        self.assertEqual(self.ship.day, 0)

    def test_prelaunch_clock_recovery_and_normal_ota(self):
        self.first_wrong_clock()
        base = self.ship.clock.base
        # Correct dates, missing tokens and forged tokens cannot move a known clock.
        for token in (None, "forged"):
            self.assertFalse(self.ship.clock.learn_headers(
                Request("GET", "/api/crew", token=token).header))
            self.assertEqual(self.ship.clock.base, base)
        self.assertEqual(self.call(Request("GET", "/api/me"))[0], 401)
        self.assertEqual(self.call(Request("POST", "/api/login", pin="0000"))[0], 403)
        status, login = self.call(Request("POST", "/api/login"))
        self.assertEqual(status, 200, login)
        self.assertTrue(login["token"])
        self.assertEqual(self.ship.day, 0, "login alone cannot correct the clock")
        # review 2 m2: no recall during the countdown (by IP and browser, which another
        # device on the same lease can share): the page keeps the token it signed in with
        self.assertEqual(self.call(Request("GET", "/api/me"))[0], 401)
        self.assertTrue(login["first"], "a first sign-in: the page shows the briefing on day 1")
        self.assertEqual(self.ship.clock.base, base, "signing in alone cannot move time")
        self.assertEqual(self.call(Request("GET", "/api/state"))[0], 409)
        # review 2 M1: signed in, the countdown's 409 carries what Settings needs, no story
        status, pre = self.call(Request("GET", "/api/state", token=login["token"],
                                        date="2026-10-28T12:00:00"))
        self.assertEqual(status, 409, pre)
        self.assertEqual((pre["pre"]["you"], pre["launch"]), (0, "2026-10-29"), pre)
        self.assertTrue({"here", "v", "season", "led", "bat"} <= set(pre["pre"]), pre)
        self.assertNotIn("story", pre)
        self.assertEqual(self.ship.day, 0, "a wrong date from the signed-in phone is ignored")
        me = {"token": login["token"]}
        self.assertEqual(self.phone.who(Request("GET", "/api/v", token=login["token"])), 0)
        self.call(Request("GET", "/api/v", token=me["token"]))
        self.assertEqual((self.ship.day, self.ship.st.day), (1, 1))
        # once flown, the sign-in is remembered as before, and the briefing is still due
        status, again = self.call(Request("POST", "/api/login"))
        self.assertEqual(status, 200, again)
        self.assertTrue(again["first"], "the briefing wasn't spent by the countdown sign-in")
        status, me2 = self.call(Request("GET", "/api/me"))
        self.assertEqual((status, me2.get("crew")), (200, 0), me2)
        self.assertNotEqual(self.ship.clock.base, base)
        corrected = self.ship.clock.base
        future = "2026-10-30T12:00:00"
        self.assertFalse(self.ship.clock.learn_headers(
            Request("GET", "/api/v", date=future).header))
        self.assertEqual(self.ship.clock.base, corrected)

        # Normal OTA write handler, never safe mode. Stage only a scratch marker;
        # authorized cancel must actually remove it, not merely accept who(req).
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "new"
            staged.mkdir()
            (staged / "marker").write_bytes(b"test staging")
            with patch.object(lvota, "NEW", str(staged)), \
                    patch.object(lvota, "STATE", str(Path(tmp) / "state.json")):
                for token in (None, "forged"):
                    self.assertEqual(self.call(Request("POST", "/api/ota/cancel", token=token), ota=True)[0], 401)
                    self.assertTrue((staged / "marker").exists())
                status, body = self.call(Request("POST", "/api/ota/cancel", token=me["token"]), ota=True)
                self.assertEqual((status, body), (200, {"ok": True}))
                self.assertFalse(staged.exists())

    def test_auth_independent_of_story_and_launch(self):
        self.first_wrong_clock()
        for prelaunch in (True, False):
            for missing in ("st", "days", "both"):
                with self.subTest(prelaunch=prelaunch, missing=missing):
                    self.ship.day = 0 if prelaunch else 1
                    st, days = self.ship.st, self.ship.days
                    try:
                        if missing in ("st", "both"):
                            self.ship.st = None
                        if missing in ("days", "both"):
                            self.ship.days = None
                        self.assertEqual(self.call(Request("GET", "/api/me"))[0], 401)
                        self.assertEqual(self.call(Request("POST", "/api/login", pin="0000"))[0], 403)
                        status, login = self.call(Request("POST", "/api/login"))
                        self.assertEqual(status, 200, login)
                        status, me = self.call(Request("GET", "/api/me"))
                        if prelaunch:       # review 2 m2: no recall in the countdown
                            self.assertEqual(status, 401, me)
                            me = login
                        else:
                            self.assertEqual(status, 200, me)
                        self.assertEqual(self.ship.day, 0 if prelaunch else 1)
                        date = "2026-10-28T12:00:00" if prelaunch else "2026-10-29T12:00:00"
                        self.assertEqual(self.call(Request("GET", "/api/state", date=date, token=me["token"]))[0], 503)
                        self.assertEqual(self.call(Request("POST", "/api/logout", date=date, token=me["token"]))[0], 200)
                        self.assertEqual(self.call(Request("GET", "/api/me"))[0], 401)
                        self.assertIsNone(self.phone.who(Request("GET", "/api/v", token=me["token"])))
                    finally:
                        self.ship.st, self.ship.days = st, days

    def test_prelaunch_logout_and_code_lockout(self):
        self.first_wrong_clock()
        for _ in range(K.MAX_TRIES - 1):
            self.assertEqual(self.call(Request("POST", "/api/login", pin="0000"))[0], 403)
        self.assertEqual(self.call(Request("POST", "/api/login", pin="0000"))[0], 429)
        self.assertEqual(self.call(Request("POST", "/api/login"))[0], 429)
        self.phone.book.until[0] = None
        self.phone.book.fails[0] = 0
        status, login = self.call(Request("POST", "/api/login"))
        self.assertEqual(status, 200, login)
        self.assertEqual(self.call(Request("POST", "/api/logout", date="2026-10-28T12:00:00", token=login["token"]))[0], 200)
        self.assertEqual(self.call(Request("GET", "/api/me"))[0], 401)
        self.assertIsNone(self.phone.who(Request("GET", "/api/v", token=login["token"])))
        self.assertFalse(self.ship.clock.learn_headers(Request("GET", "/api/v", token=login["token"]).header))
        self.assertEqual(self.ship.day, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
