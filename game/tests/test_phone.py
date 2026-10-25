#!/usr/bin/env python3
"""The board's phone API (board/lvphone.py) against the contract the page was built on
(sim/mockserver.py): the same routes, the same JSON shapes, the same gift rules.
Then tests/phone_check.py (both phones end to end on fake sockets) for a few days.
  python3 tests/test_phone.py      (from game/)"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, "board"), os.path.join(HERE, "fakeble")]
os.chdir(ROOT)

import lvship                       # noqa: E402
import lvdays                       # noqa: E402
import lvphone                      # noqa: E402
from lv import record as R          # noqa: E402
from sim import mockserver as M     # noqa: E402


def shape(x):
    """The JSON's structure: dict keys (recursively), list element shapes (first element)."""
    if isinstance(x, dict):
        return {k: shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, int):
        return "int"
    if x is None:
        return None
    return type(x).__name__


def merge_none(a, b):
    # None in one (e.g. "mine": null, "act": null) matches anything in the other.
    if a is None or b is None:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(merge_none(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return not a or not b or merge_none(a[0], b[0])
    return a == b


class Req:
    def __init__(self, method, path, body=b"", hdr=None, q=None, peer="10.0.0.2"):
        self.method, self.path, self.body = method, path, body
        self.hdr, self.q, self.peer = hdr or {}, q or {}, peer

    def header(self, k):
        return self.hdr.get(k)

    def phone(self):
        return self.peer + "|" + self.hdr.get("user-agent", "")


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "web/build.py"], check=True, stdout=subprocess.DEVNULL)
        cls.day = 9
        cls.mock = M.Game(cls.day)
        cfg = lvship.load_config("/nonexistent")
        cfg["day"] = cls.day
        cls.ship = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None, radio=False)
        raw = open("build/season_log.bin", "rb").read()
        for i in range(0, len(raw), R.LEN):
            r = raw[i:i + R.LEN]
            if R.day(r) < cls.day:
                cls.ship.log.merge(r)
        from lv.state import State
        cls.ship.st = State(cls.ship.pack)
        cls.ship.days = lvdays.Days()
        cls.ship.tick_to(cls.day)
        cls.phone = lvphone.Phone(cls.ship, "build/", lambda s: None)
        from lv import codes as K
        cls.phone.book = K.CodeBook(K.make_config(["1234"] * 8, b"mock-fleet-salt!"))

    def test_state_shape(self):
        you = 1    # has a private dilemma open on day 9 in both
        want = self.mock.state(you, self.day, self.day - 3, 600)
        want["v"] = 0
        got = self.phone.state_body(you, self.day - 3, 600)
        self.assertEqual(sorted(set(want) - {"story"}), sorted(got))
        # "updated" maps day -> day as strings -> ints; which days depends on what arrived late.
        for k, v in list(want["updated"].items()) + list(got["updated"].items()):
            self.assertTrue(k.isdigit() and isinstance(v, int))
        skip = ("story", "updated")
        self.assertTrue(merge_none(shape({k: v for k, v in want.items() if k not in skip}),
                                   shape({k: v for k, v in got.items() if k not in skip})),
                        "state JSON shape differs from sim/mockserver.py")
        self.assertTrue(got["open"], "nothing open on day 9")
        self.assertEqual(got["day"], self.day)

    def test_air(self):
        # Bluetooth contact as the crew list and gift picker read it: lv/ble's peers (kept a
        # day by lvship), ages to its last sweep, in sync when it last matched our log.
        from lv.ble import Peer
        a, b = Peer(2), Peer(5)
        a.seen, b.seen = 95000, 1000000          # b heard after the sweep: age 0, not negative
        b.diff_since = 990000                    # b's log differed: still syncing

        class Ble:
            peers = {2: a, 5: b}
            _swept = 125000
        self.ship.ble = Ble()
        try:
            got = self.phone.state_body(1, self.day - 3, 600)["air"]
        finally:
            self.ship.ble = None
        self.assertEqual(sorted(got), [[2, 30, True], [5, 0, False]])
        self.assertIsNone(self.phone.state_body(1, self.day - 3, 600)["air"])   # no radio: hidden
        mock = self.mock.state(1, self.day, self.day - 3, 600)["air"]
        self.assertTrue(all(len(x) == 3 and x[0] != 1 and x[1] >= 0 for x in mock))

    def test_peer_ttl(self):
        # lvship keeps a heard ship a day (lv/ble forgets after 10 min by default); a "ble"
        # in ship.json replaces the default.
        import bluetooth
        cfg = lvship.load_config("/nonexistent")
        sh = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None, radio=bluetooth.World(3).new())
        self.assertEqual(sh.ble.cfg["peer_ttl_ms"], 86400000)
        cfg = lvship.load_config("/nonexistent")
        cfg["ble"] = {"peer_ttl_ms": 60000}
        sh = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None, radio=bluetooth.World(3).new())
        self.assertEqual(sh.ble.cfg["peer_ttl_ms"], 60000)

    def test_routes(self):
        P = self.phone
        s, j = P.api(Req("GET", "/api/crew"))
        self.assertEqual((s, len(j["set"]), j["day"]), (200, 8, self.day))
        s, j = P.api(Req("POST", "/api/login", b'{"crew":3,"pin":"1234"}', {"user-agent": "t"}))
        self.assertEqual(s, 200)
        tok = {"x-crew-token": j["token"], "user-agent": "t"}
        s, w = P.api(Req("GET", "/api/state", hdr=tok))
        self.assertEqual(s, 0)          # streamed by lvweb
        self.assertTrue(callable(w))
        for path, body in (("/api/vote", b'{"card":"x"}'), ("/api/act", b"{}"), ("/api/gift", b'{"item":0}'),
                           ("/api/open", b'{"day":99}')):
            self.assertEqual(P.api(Req("POST", path, body, tok))[0], 400, path)
        self.assertEqual(P.api(Req("POST", "/api/nope", b"{}", tok))[0], 404)
        self.assertEqual(P.api(Req("GET", "/api/state"))[0], 401)

    def test_gift_rules_match_mock(self):
        # Same error strings for the same refusals.
        P = self.phone
        self.assertEqual(P.gift(2, self.day, 0, 2, 0), "bad request")       # to yourself
        self.assertEqual(P.gift(2, self.day, 0, 3, 7), "bad request")       # bad mode
        self.assertEqual(P.gift(2, self.day, 0, 3, 2), "Nothing to answer.")


class LateRecords(unittest.TestCase):
    def test_updated_days(self):
        # Ship 4's records for days 2-5 arrive late (BLE): the days they change are flagged
        # for the page ("log updated"), as the mock does, and v moves.
        cfg = lvship.load_config("/nonexistent")
        cfg["day"] = 12
        ship = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None, radio=False)
        raw = open("build/season_log.bin", "rb").read()
        recs = [raw[i:i + R.LEN] for i in range(0, len(raw), R.LEN)]
        late = [r for r in recs if R.ship(r) == 4 and 2 <= R.day(r) <= 5]
        for r in recs:
            if R.day(r) < 12 and r not in late:
                ship.log.merge(r)
        from lv.state import State
        ship.st = State(ship.pack)
        ship.days = lvdays.Days()
        ship.tick_to(12)
        before = {d: ship.days.get(d) for d in ship.days.idx}
        v = ship.v
        ship.node.merge(late)
        self.assertGreater(ship.v, v)
        changed = [d for d in before if d < 12 and lvdays.visible(before[d]) != lvdays.visible(ship.days.get(d))]
        self.assertTrue(changed, "the late records changed nothing visible; pick others")
        self.assertEqual(sorted(ship.days.updated), sorted(changed))   # today (12) is never "updated"
        self.assertTrue(all(v == 12 for v in ship.days.updated.values()))


class EndToEnd(unittest.TestCase):
    def test_phone_check_days(self):
        for d in ("5", "9", "42"):
            p = subprocess.run([sys.executable, "tests/phone_check.py", d], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn(": ok", p.stdout)


class DaysFile(unittest.TestCase):
    """lvdays.Days on a file: the story isn't on the heap, a phone's ref() stays readable
    while days are retold, and the file is compacted only when nobody is reading."""

    def test_refs_and_compaction(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            days = lvdays.Days(os.path.join(d, "days.bin"))
            for x in range(1, 6):
                days.put(x, bytes([x]) * 80, x)
            self.assertEqual(days.get(3), bytes([3]) * 80)
            self.assertEqual(days.length(4), 80)
            self.assertIsInstance(days.ref(2), tuple)      # an offset, not the bytes
            days.readers += 1                              # a phone mid-stream
            held = days.ref(2)
            for k in range(200):                           # many replays retell day 2
                days.put(2, bytes([100 + k % 50]) * 80, 6)
            self.assertEqual(days.load(held), bytes([2]) * 80)
            grown = days.size
            self.assertGreater(grown, 4096)
            days.readers -= 1
            days.put(2, b"\x09" * 80, 6)                  # nobody reading: compacts
            self.assertLess(days.size, grown)
            self.assertEqual(days.size, 6 * 80)                # 5 live days, then the new day 2
            for x in (1, 3, 4, 5):
                self.assertEqual(days.get(x), bytes([x]) * 80)
            self.assertEqual(days.get(2), b"\x09" * 80)
            self.assertEqual(os.path.getsize(os.path.join(d, "days.bin")), days.size)
            self.assertEqual(days.ref(99), b"")
            self.assertEqual(days.length(99), 0)

    def test_today_never_updated(self):
        days = lvdays.Days()
        days.put(4, b"\x00" * 8, 4)
        days.put(4, b"\x01" * 8, 4)       # retold the same day: not "updated"
        self.assertEqual(days.updated, {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
