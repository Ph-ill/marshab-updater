#!/usr/bin/env python3
"""The calendar (board/lvcal.py): one flight day per real day from the fleet launch date,
rolling over at 06:00 local. Day math (time zones, daylight saving, before launch, after
day 42), the clock unknown, catching up from peers (one day, our fleet, only without a
phone clock), the day saved across a reboot, never backwards, and the ship moving to the
new day while it runs (story told, advert, v for the polling phones, the pre-launch API).
  python3 tests/test_cal.py      (from game/)"""
import datetime as DT
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, "board"), os.path.join(HERE, "fakeble")]
os.chdir(ROOT)

import lvcal as C                    # noqa: E402
from lv.clock import Clock           # noqa: E402

SEASON = 42
UTC = DT.timezone.utc


def ms(y, mo, d, h, mi, tz_min):
    """Epoch ms of a local wall time at a fixed UTC offset (minutes east)."""
    t = DT.datetime(y, mo, d, h, mi, tzinfo=DT.timezone(DT.timedelta(minutes=tz_min)))
    return int(t.timestamp() * 1000)


class FakeTicks:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t

    @staticmethod
    def diff(a, b):
        return a - b


def clock():
    ft = FakeTicks()
    return Clock(ft, ft.diff), ft


def cal(launch="2026-10-24", start=None, data=None, season=SEASON):
    c, ft = clock()
    cfg = {"launch_date": launch}
    if start is not None:
        cfg["day_start"] = start
    return C.Calendar(cfg, c, season, data, say=lambda s: None), c, ft


class DayMath(unittest.TestCase):
    def test_civil_days_match_python(self):
        d0 = DT.date(1970, 1, 1)
        for y in (2000, 2024, 2026, 2027, 2028, 2100):
            for mo in range(1, 13):
                for d in (1, 15, 28):
                    self.assertEqual(C.days_from_civil(y, mo, d), (DT.date(y, mo, d) - d0).days)
        self.assertEqual(C.parse_date("2028-02-29"), (DT.date(2028, 2, 29) - d0).days)

    def test_parse(self):
        for bad in ("", None, "2026-02-29", "2026-13-01", "2026-04-31", "24-10-2026", "2026/10/24", "x" * 10, 20261024):
            self.assertIsNone(C.parse_date(bad), bad)
        self.assertEqual(C.parse_hm("06:00"), 360)
        self.assertEqual(C.parse_hm("21:30"), 1290)
        self.assertEqual(C.parse_hm(90), 90)
        for bad in ("25:00", "6", None, "a:b", -1, 1440):
            self.assertEqual(C.parse_hm(bad), 360, bad)

    def test_rollover_at_six(self):
        L = C.parse_date("2026-10-24")
        lm = lambda d, h, m: (C.days_from_civil(2026, 10, d) * 1440) + h * 60 + m   # noqa: E731
        self.assertEqual(C.flight_day(lm(23, 12, 0), L, SEASON), 0, "the day before launch")
        self.assertEqual(C.flight_day(lm(24, 5, 59), L, SEASON), 0, "launch morning before 06:00")
        self.assertEqual(C.flight_day(lm(24, 6, 0), L, SEASON), 1)
        self.assertEqual(C.flight_day(lm(25, 5, 59), L, SEASON), 1, "until 06:00 next morning")
        self.assertEqual(C.flight_day(lm(25, 6, 0), L, SEASON), 2)
        last = (L + 41) * 1440 + 360
        self.assertEqual(C.flight_day(last, L, SEASON), 42, "six weeks later")
        self.assertEqual(C.flight_day(last + 30 * 1440, L, SEASON), 42, "stays 42 after the voyage")
        self.assertEqual(C.flight_day(lm(24, 21, 30), L, SEASON, 1290), 1, "a bench day start")
        self.assertEqual(C.flight_day(lm(24, 21, 29), L, SEASON, 1290), 0)

    def test_time_zone(self):
        # One instant, 11:30 UTC on launch day: 06:30 in Chicago (CDT, -300) is FD 1;
        # 04:30 in Los Angeles (PDT, -420) is still before launch.
        for tz, want in ((-300, 1), (-420, 0), (60, 1)):
            k, c, ft = cal()
            c.learn(ms(2026, 10, 24, 11, 30, 0), tz)
            self.assertEqual(k.poll(), want, tz)

    def test_daylight_saving_with_phones(self):
        # US clocks go back 2026-11-01 02:00 CDT -> 01:00 CST. Launch 2026-10-24: Nov 1 is FD 9.
        k, c, ft = cal()
        c.learn(ms(2026, 11, 1, 5, 59, -360), -360)
        self.assertEqual(k.poll(), 8)
        ft.t += 60000
        self.assertEqual(k.poll(), 9, "06:00 CST")
        # Spring forward, 2027-03-14 02:00 CST -> 03:00 CDT: no day skipped or doubled.
        k, c, ft = cal("2027-03-10")
        c.learn(ms(2027, 3, 14, 5, 59, -300), -300)
        self.assertEqual(k.poll(), 4)
        ft.t += 60000
        self.assertEqual(k.poll(), 5)

    def test_daylight_saving_without_a_phone(self):
        # The board keeps the last phone's offset (CDT). With no phone that morning it rolls
        # over at 05:00 CST; the next phone (CST) doesn't take the day back.
        k, c, ft = cal()
        c.learn(ms(2026, 10, 31, 22, 0, -300), -300)
        self.assertEqual(k.poll(), 8)
        ft.t = ms(2026, 11, 1, 5, 0, -360) - ms(2026, 10, 31, 22, 0, -300)
        self.assertEqual(k.poll(), 9, "an hour early, on the old offset")
        c.learn(ms(2026, 11, 1, 5, 10, -360), -360)
        self.assertEqual(c.tz, -360)
        self.assertEqual(k.poll(), 9, "never backwards")
        ft.t += 24 * 3600000
        self.assertEqual(k.poll(), 9, "05:10 CST next morning")
        ft.t += 3600000
        self.assertEqual(k.poll(), 10, "06:10 CST: on time again")


class Calendar(unittest.TestCase):
    def test_clock_unknown(self):
        k, c, ft = cal()
        self.assertEqual(k.poll(), 0)
        self.assertIsNone(k.until())
        ft.t += 3 * 86400000
        self.assertEqual(k.poll(), 0, "no time, no day: waits for a phone or a peer")

    def test_before_launch_countdown(self):
        k, c, ft = cal()
        c.learn(ms(2026, 10, 23, 21, 0, -300), -300)
        self.assertEqual(k.poll(), 0)
        self.assertEqual(k.until(), 9 * 60)
        ft.t += 9 * 3600000 - 60000
        self.assertEqual((k.poll(), k.until()), (0, 1))
        ft.t += 60000
        self.assertEqual((k.poll(), k.until()), (1, 0))

    def test_after_the_voyage(self):
        k, c, ft = cal("2026-01-01")
        c.learn(ms(2026, 10, 23, 12, 0, -300), -300)
        self.assertEqual(k.poll(), 42)

    def test_never_backwards(self):
        k, c, ft = cal()
        c.learn(ms(2026, 10, 30, 12, 0, -300), -300)
        self.assertEqual(k.poll(), 7)
        c.learn(ms(2026, 10, 26, 12, 0, -300), -300)        # a phone with a slow clock
        self.assertEqual(k.poll(), 7)

    def test_peer_catch_up(self):
        k, c, ft = cal()
        self.assertEqual(k.poll([3]), 0, "from nothing: a peer at FD 3 is too far ahead")
        self.assertEqual(k.poll([1]), 1)
        self.assertEqual(k.poll([5, 9]), 1, "two or more days ahead: ignored")
        self.assertEqual(k.poll([2]), 2)
        self.assertEqual(k.src, "peer")
        self.assertEqual(k.poll([3, 3]), 3, "one day per poll")
        self.assertEqual(k.poll([3]), 3, "a peer on our day: nothing to do")
        self.assertEqual(k.poll([2]), 3, "a peer behind: nothing to do")
        k2, c2, ft2 = cal(season=3)
        k2.day = 3
        self.assertEqual(k2.poll([4]), 3, "not past the season")

    def test_no_peer_catch_up_with_a_phone_clock(self):
        k, c, ft = cal()
        c.learn(ms(2026, 10, 26, 12, 0, -300), -300)
        self.assertEqual(k.poll([4]), 3, "the phone says FD 3: a peer at FD 4 is the wrong one")

    def test_reboot_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            k, c, ft = cal(data=d)
            c.learn(ms(2026, 10, 28, 20, 0, -300), -300)
            self.assertEqual(k.poll(), 5)
            with open(d + "/clock.json") as f:
                saved = json.load(f)
            self.assertEqual((saved["day"], saved["key"]), (5, "2026-10-24@360"))
            # Reboot, no phone: FD 5 at once, and the saved time runs on to FD 6 at 06:00.
            k, c, ft = cal(data=d)
            self.assertFalse(c.known())
            self.assertEqual((k.poll(), k.src), (5, "saved"))
            ft.t = 10 * 3600000
            self.assertEqual((k.poll(), k.src), (6, "saved"))
            with open(d + "/clock.json") as f:
                self.assertEqual(json.load(f)["day"], 6)
            # A peer can still move an unsure ship one day.
            self.assertEqual(k.poll([7]), 7)
            # Another launch date (or day start) forgets it.
            k, c, ft = cal("2026-10-25", data=d)
            self.assertEqual(k.poll(), 0)
            k, c, ft = cal(start="21:30", data=d)
            self.assertEqual(k.poll(), 0)

    def test_saves_are_rare(self):
        with tempfile.TemporaryDirectory() as d:
            k, c, ft = cal(data=d)
            n = [0]
            real = k.save

            def count(up):
                n[0] += 1
                real(up)
            k.save = count
            c.learn(ms(2026, 10, 28, 12, 0, -300), -300)
            k.poll()
            for i in range(24 * 60):             # a day of polls, one a minute
                ft.t += 60000
                k.poll()
            # The first phone time, then hourly (24), plus the 06:00 rollover's.
            self.assertLessEqual(n[0], 27)
            self.assertGreaterEqual(n[0], 24)


class OnTheShip(unittest.TestCase):
    """lvship.Ship with a launch date: the day moves while it runs; lvphone before launch."""

    def ship(self, launch, day=1):
        import lvship
        import lvdays
        from lv import record as R
        cfg = lvship.load_config("/nonexistent")
        cfg["day"] = day
        if launch:
            cfg["launch_date"] = launch
        sh = lvship.Ship(cfg, root="build/", data=None, say=lambda s: None, radio=False, days=lvdays.Days())
        with open("build/season_log.bin", "rb") as f:
            raw = f.read()
        for i in range(0, len(raw), R.LEN):
            sh.log.merge(raw[i:i + R.LEN])
        return sh

    def test_manual_day_unchanged(self):
        sh = self.ship("", day=9)
        self.assertIsNone(sh.cal)
        self.assertEqual(sh.day, 9)
        sh.clock.learn(ms(2026, 10, 30, 12, 0, -300), -300)
        self.assertFalse(sh.day_check())
        self.assertEqual((sh.day, sh.status()["day_src"]), (9, "manual"))
        self.assertIsNone(self.ship("not-a-date", day=4).cal, "a bad date: the manual day")

    def test_rollover_while_running(self):
        sh = self.ship("2026-10-24")
        self.assertEqual((sh.day, sh.st.day, sh.node.day), (0, 0, 0))
        t0 = ms(2026, 11, 1, 5, 58, -360)
        sh.clock.learn(t0, -360)
        self.assertTrue(sh.day_check())
        self.assertEqual((sh.day, sh.st.day, sh.node.day), (8, 8, 8))
        v = sh.v
        sh.clock.learn(t0 + 3 * 60000, -360)                 # 06:01
        self.assertTrue(sh.day_check())
        self.assertEqual((sh.day, sh.st.day, sh.node.day), (9, 9, 9))
        self.assertGreater(sh.v, v, "polling phones see a new v")
        self.assertEqual(sh.status()["day_src"], "phone")
        # The same story as a ship told FD 9 from the start (the clock is not in it).
        ref = self.ship("", day=9)
        from lv.state import State
        ref.st = State(ref.pack)
        ref.tick_to(9)
        self.assertEqual(sh.st.hexdigest(), ref.st.hexdigest())

    def test_pre_launch_api(self):
        import lvphone
        sys.path.insert(0, HERE)
        from test_phone import Req
        sh = self.ship("2026-10-24")
        sh.clock.learn(ms(2026, 10, 23, 20, 0, -300), -300)
        sh.day_check()
        ph = lvphone.Phone(sh, "build/", lambda s: None)
        s, j = ph.api(Req("GET", "/api/crew"))
        self.assertEqual((s, j["day"], j["launch"], j["until"], j["start"]), (200, 0, "2026-10-24", 600, 360))
        s, j = ph.api(Req("POST", "/api/login", json.dumps({"crew": 0, "pin": "1234"}).encode()))
        self.assertEqual((s, j["until"]), (409, 600))
        self.assertEqual(ph.api(Req("GET", "/api/v"))[0], 200)
        sh.clock.learn(ms(2026, 10, 24, 6, 0, -300), -300)
        sh.day_check()
        s, j = ph.api(Req("GET", "/api/crew"))
        self.assertEqual((s, j["day"], j["start"]), (200, 1, 360))
        self.assertNotIn("until", j)


if __name__ == "__main__":
    unittest.main(verbosity=1)
