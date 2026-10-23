#!/usr/bin/env python3
"""Engagement layer tests (CPython): gifts in the engine, drops, jobs, streaks, the
waiting list, the clock, the LED notifier, and a season where 3 of 8 never play."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lv import record as R              # noqa: E402
from lv import ops as O                 # noqa: E402
from lv import engage as E              # noqa: E402
from lv.chlog import ChoiceLog          # noqa: E402
from lv.clock import Clock              # noqa: E402
from lv.engine import Engine            # noqa: E402
from lv.led import Notifier, BUDGET_MS, ON_MS  # noqa: E402
from lv.pack import load                # noqa: E402
from lv.state import State, N           # noqa: E402
from sim import season as S             # noqa: E402

FK = S.FLEET_KEY
PACK = os.path.join(ROOT, "build", "pack.bin")
TABLE = os.path.join(ROOT, "build", "engage.bin")


def rec(kind, ship, seq, day, a, b=0, c=0, delay=1):
    return R.encode(FK, kind, ship, delay, seq, day, a, b, c)


class FakeTicks:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t & 0x3FFFFFFF

    @staticmethod
    def diff(a, b):
        d = (a - b) & 0x3FFFFFFF
        return d - 0x40000000 if d & 0x20000000 else d


NOON = 1792843200000   # 2026-10-24 12:00 UTC


class TestMergeCollect(unittest.TestCase):
    # lv/chlog.py collects every GC_EVERY new records (MicroPython only by default).
    def test_collects_every_32_new_records_only(self):
        from lv import chlog
        log = ChoiceLog(S.FLEET_KEY)
        self.assertIsNone(log.collect)          # off on CPython
        calls = []
        log.collect = lambda: calls.append(len(log))
        recs = [r for _, r in S.reference_season(load(os.path.join(ROOT, "build", "pack.bin")), seed=1)[1]]
        for r in recs:
            log.merge(r)
        self.assertEqual(len(calls), len(recs) // chlog.GC_EVERY)
        self.assertEqual(calls[0], chlog.GC_EVERY - 1)   # before the 32nd insert
        n = len(calls)
        for r in recs:
            self.assertEqual(log.merge(r), chlog.DUP)
        self.assertEqual(len(calls), n)          # duplicates never collect


sys.path.insert(0, os.path.join(ROOT, "tools"))


class TestContentSafety(unittest.TestCase):
    # Engagement text shows on any day, so it may not touch the story (tools/lve.py).
    def _build(self, edit):
        import shutil
        import tempfile
        import lve
        d = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(ROOT, "content", "engage"), os.path.join(d, "engage"))
            p = os.path.join(d, "engage", "collections.json")
            with open(p) as f:
                c = json.load(f)
            edit(c)
            with open(p, "w") as f:
                json.dump(c, f)
            return lve.build(d)
        finally:
            shutil.rmtree(d)

    def test_shipped_text_is_clean_and_every_patch_has_a_lock_line(self):
        self._build(lambda c: None)

    def test_reserved_word_fails(self):
        import lve
        with open(os.path.join(ROOT, "content", "engage", "reserved.json")) as f:
            word = json.load(f)["patterns"][0]
        def edit(c):
            c["patches"][0]["t"] = "A %s, for the record." % word
        self.assertRaises(lve.Err, self._build, edit)

    def test_spooky_word_fails(self):
        import lve
        def edit(c):
            c["artifacts"][0]["t"] = "Something eerie in the bag."
        self.assertRaises(lve.Err, self._build, edit)

    def test_missing_lock_fails(self):
        import lve
        def edit(c):
            del c["patches"][0]["lock"]
        self.assertRaises(lve.Err, self._build, edit)


class TestGiftRecord(unittest.TestCase):
    def test_give_and_ask_same_day_are_different_keys(self):
        a = rec(R.GIFT, 1, 1, 3, 2, 4, R.GIFT_GIVE)
        b = rec(R.GIFT, 1, 2, 3, 5, 4, R.GIFT_ASK)
        c = rec(R.GIFT, 1, 3, 3, 5, 2, R.GIFT_GIVE)
        self.assertEqual(len({R.key(a), R.key(b), R.key(c)}), 3)

    def test_gift_warms_bond_ask_does_nothing(self):
        p = load(PACK)
        st = State(p)
        log = ChoiceLog(FK)
        log.merge(rec(R.GIFT, 0, 1, 0, 1, 3, R.GIFT_GIVE))
        log.merge(rec(R.GIFT, 1, 1, 0, 2, 4, R.GIFT_ASK))
        ref = State(p)
        Engine(p, ref, ChoiceLog(FK)).tick()
        Engine(p, st, log).tick()
        gifts = [st.out[i:i + 8] for i in range(0, len(st.out), 8) if st.out[i + 1] == O.O_GIFT]
        self.assertEqual(len(gifts), 1)
        self.assertEqual(list(gifts[0][3:7]), [0, 1, 3, R.GIFT_GIVE])

    def test_bad_gift_is_ignored(self):
        p = load(PACK)
        st = State(p)
        log = ChoiceLog(FK)
        log.merge(rec(R.GIFT, 0, 1, 0, 1, 0, R.GIFT_GIVE))   # to self
        log.merge(rec(R.GIFT, 0, 2, 0, 1, 9, R.GIFT_ANSWER))  # no such crew
        Engine(p, st, log).tick()
        self.assertFalse(any(st.out[i + 1] == O.O_GIFT for i in range(0, len(st.out), 8)))


class TestEightCrew(unittest.TestCase):
    """Marco (crew 7, ship 8) gets everything the other seven get: gifts both ways over the
    radio record, drops, jobs, a crew-file line and a slot in the ship-local file."""

    @classmethod
    def setUpClass(cls):
        cls.p = load(PACK)
        cls.t = E.load_table(TABLE)
        cls.e = E.Engage(cls.t, cls.p.voyage_key, cls.p.season)

    def test_endings_are_the_titled_cards(self):
        # The shipped text.json has no card ids, so the file screen's story % (engage.js
        # storyPct) leaves endings out by their title. Every ending has one; nothing else does.
        dev = json.load(open(os.path.join(ROOT, "build", "text.dev.json"), encoding="utf-8"))
        ends = [c["id"].startswith("end_") for c in dev["cards"]]
        self.assertEqual(ends, [bool(c.get("ti")) for c in dev["cards"]])
        self.assertTrue(any(ends))

    def test_n_is_eight_everywhere(self):
        from lv import codes as K
        self.assertEqual((N, K.N, self.e.n, E.Local(42).n), (8, 8, 8, 8))
        self.assertGreater(R.ADMIN_SHIP, N - 1)

    def test_gifts_to_and_from_marco(self):
        st = State(self.p)
        log = ChoiceLog(FK)
        log.merge(rec(R.GIFT, 7, 1, 0, 1, 0, R.GIFT_GIVE))    # Marco -> Phill
        log.merge(rec(R.GIFT, 5, 1, 0, 2, 7, R.GIFT_GIVE))    # Diego -> Marco
        log.merge(rec(R.GIFT, 2, 1, 0, 4, 7, R.GIFT_ASK))     # Kim asks Marco
        Engine(self.p, st, log).tick()
        out = [list(st.out[i + 3:i + 7]) for i in range(0, len(st.out), 8) if st.out[i + 1] == O.O_GIFT]
        self.assertIn([7, 1, 0, R.GIFT_GIVE], out)
        self.assertIn([5, 2, 7, R.GIFT_GIVE], out)
        inbox, outbox, asks, (gave, asked) = E.gifts(log, 7, 1, self.t.ask_days)
        self.assertEqual([g[1] for g in inbox], [2, 5])
        self.assertEqual(outbox, [(0, 0, 1, R.GIFT_GIVE)])
        self.assertEqual([a[1] for a in asks], [2])
        v = E.view(self.e, E.Local(self.p.season), self.p, st, log, 7, 600)
        self.assertEqual(v["stats"]["gifts"], 1)

    def test_marco_drops_and_jobs(self):
        d7 = self.e.drops(7)
        self.assertEqual(len(d7), len(self.e.drops(0)))
        self.assertNotEqual(d7, self.e.drops(6))
        self.assertTrue(any(self.e.job(7, d) for d in range(1, self.p.season + 1)))

    def test_local_file_has_eight_slots_and_reads_old_seven(self):
        loc = E.Local(42)
        loc.open(7, 3)
        self.assertEqual(E.Local.load(loc.dump()).is_open(7, 3), 1)
        old = E.Local(42, 7)
        old.open(6, 5)
        back = E.Local.load(old.dump())
        self.assertEqual((back.n, back.is_open(6, 5), back.is_open(7, 5)), (8, 1, 0))

    def test_crew_file_line_for_everyone(self):
        with open(os.path.join(ROOT, "build", "engage.json"), encoding="utf-8") as f:
            tr = json.load(f)["file"]["traded"]
        self.assertEqual(len(set(tr)), N)


class TestDropsJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load(PACK)
        cls.t = E.load_table(TABLE)
        cls.e = E.Engage(cls.t, cls.p.voyage_key, cls.p.season)

    def test_deterministic(self):
        e2 = E.Engage(self.t, self.p.voyage_key, self.p.season)
        for s in range(N):
            self.assertEqual(self.e.drops(s), e2.drops(s))
            self.assertEqual([self.e.job(s, d) for d in range(43)], [e2.job(s, d) for d in range(43)])

    def test_other_voyage_differs(self):
        e2 = E.Engage(self.t, b"otherkey", self.p.season)
        self.assertNotEqual(self.e.drops(0), e2.drops(0))

    def test_no_repeat_until_tier_exhausted(self):
        for s in range(N):
            seen = {}
            for d in range(1, self.p.season + 1):
                tier, item = self.e.drop(s, d)
                seen.setdefault(tier, []).append(item)
            for tier, items in seen.items():
                c = self.t.count[tier]
                for i in range(0, len(items), c):
                    chunk = items[i:i + c]
                    self.assertEqual(len(chunk), len(set(chunk)), (s, tier))

    def test_pity(self):
        top = len(self.t.pct) - 1
        for s in range(N):
            last = 0
            for d in range(1, self.p.season + 1):
                if self.e.drop(s, d)[0] == top:
                    last = d
                self.assertLess(d - last, self.t.pity, (s, d))

    def test_jobs_in_window(self):
        n = 0
        for s in range(N):
            for d in range(1, 43):
                j = self.e.job(s, d)
                if j:
                    n += 1
                    h0, h1, w = self.t.jobs[j[0]]
                    self.assertTrue(h0 * 60 <= j[1] < h1 * 60)
                    self.assertTrue(0 <= j[2] < len(w))
        self.assertTrue(0.4 < n / (7 * 42) < 0.8)


class TestStreak(unittest.TestCase):
    def act(self, days, season=42):
        a = bytearray(season + 2)
        for d in days:
            a[d] = 1
        return a

    def test_plain(self):
        self.assertEqual(E.streak(self.act([1, 2, 3]), 3)[:2], (3, 3))

    def test_today_does_not_break(self):
        self.assertEqual(E.streak(self.act([1, 2]), 3)[0], 2)

    def test_grace_two_per_week(self):
        cur, best, cov = E.streak(self.act([1, 3, 5, 7]), 7)
        # 1 on, 2 covered, 3 on, 4 covered, 5 on, 6 is the 3rd miss in week 1: a new
        # watch starts on 7
        self.assertEqual((cur, best, cov), (1, 5, [2, 4]))

    def test_grace_resets_weekly(self):
        cur, best, cov = E.streak(self.act([1, 2, 3, 4, 5, 6, 8, 10, 12, 14]), 14)
        # week 1 covers 7; week 2 covers 9 and 11; 13 is the 3rd miss in week 2
        self.assertEqual((cur, best, cov), (1, 12, [7, 9, 11]))

    def test_no_streak_no_grace(self):
        cur, best, cov = E.streak(self.act([]), 42)
        self.assertEqual((cur, best, cov), (0, 0, []))


class TestClockLed(unittest.TestCase):
    def clock(self, t=0):
        ft = FakeTicks(t)
        return ft, Clock(ft, FakeTicks.diff)

    def test_unknown_until_phone(self):
        ft, c = self.clock()
        self.assertIsNone(c.minute())
        self.assertFalse(c.learn(5, 0))           # 1970: rejected
        self.assertFalse(c.learn("x", 0))
        self.assertTrue(c.learn(NOON, -300))       # Chicago, CDT
        self.assertEqual(c.minute(), 7 * 60)

    def test_wrap(self):
        ft, c = self.clock(0x3FFFFFFF - 1000)
        c.learn(NOON, 0)
        for _ in range(30):                        # 30 x 12 h, many wraps
            ft.t += 12 * 3600000
            c.uptime()
        self.assertEqual(c.epoch_ms(), NOON + 30 * 12 * 3600000)

    def test_small_corrections_ignored(self):
        ft, c = self.clock()
        c.learn(NOON, 0)
        c.learn(NOON + 30000, 0)
        self.assertEqual(c.epoch_ms(), NOON)
        c.learn(NOON + 600000, 0)
        self.assertEqual(c.epoch_ms(), NOON + 600000)

    def run_led(self, c, ft, led, ms, step=10):
        on = 0
        for _ in range(ms // step):
            ft.t += step
            led.poll()
            on += led.lit
        return on * step

    def pin(self):
        class P:
            n = 0
            v = 0

            def value(self, v):
                self.v = v
                P.n += 1
        return P

    def test_disabled_never_touches_pin(self):
        ft, c = self.clock()
        c.learn(NOON, 0)
        made = []
        led = Notifier(c, False, lambda: made.append(1))
        led.set_waiting(True)
        self.run_led(c, ft, led, 60000)
        self.assertEqual(made, [])

    def test_unknown_time_stays_dark(self):
        ft, c = self.clock()
        P = self.pin()
        led = Notifier(c, True, P)
        led.set_waiting(True)
        self.assertEqual(self.run_led(c, ft, led, 60000), 0)

    def test_quiet_hours(self):
        ft, c = self.clock()
        c.learn(NOON + 11 * 3600000, 0)     # 23:00
        led = Notifier(c, True, self.pin())
        led.set_waiting(True)
        self.assertEqual(self.run_led(c, ft, led, 60000), 0)
        c.learn(NOON - 4 * 3600000, 0)      # 08:00
        self.assertGreater(self.run_led(c, ft, led, 60000), 0)

    def test_blink_rate_and_off_after_visit(self):
        ft, c = self.clock()
        c.learn(NOON, 0)
        P = self.pin()
        led = Notifier(c, True, P)
        led.set_waiting(True)
        lit = self.run_led(c, ft, led, 60000)
        self.assertTrue(1000 <= lit <= 2000, lit)     # ~13 blinks of 110 ms
        self.assertLessEqual(P.n, 30)                  # < 1 radio command a second
        led.set_waiting(False)
        self.run_led(c, ft, led, 1000)
        self.assertEqual(self.run_led(c, ft, led, 60000), 0)

    def test_budget(self):
        ft, c = self.clock()
        c.learn(NOON - 5 * 3600000, 0)      # 07:00
        led = Notifier(c, True, self.pin(), )
        led.set_waiting(True)
        lit = self.run_led(c, ft, led, 6 * 3600000, step=50)
        self.assertLessEqual(lit, BUDGET_MS + 2 * ON_MS)
        self.assertGreater(lit, BUDGET_MS // 2)

    def test_disable_turns_off(self):
        ft, c = self.clock()
        c.learn(NOON, 0)
        P = self.pin()
        led = Notifier(c, True, P)
        led.set_waiting(True)
        while not led.lit:
            ft.t += 10
            led.poll()
        led.set_enabled(False)
        self.assertFalse(led.lit)


class TestInactiveSeason(unittest.TestCase):
    """3 of 8 never play: nothing waits for them, nobody is punished, every ship agrees."""

    @classmethod
    def setUpClass(cls):
        cls.saved = [dict(p) for p in S.PROFILES]
        S.PROFILES[4]["p"] = 0.0
        cls.p = load(PACK)
        cls.st, cls.authored, _, cls.log = S.reference_season(cls.p, seed=11)
        cls.ref = cls.st.digest()

    @classmethod
    def tearDownClass(cls):
        S.PROFILES[:] = cls.saved

    def test_three_never_play(self):
        authors = {R.ship(r) for _, r in self.authored}
        self.assertEqual(authors & {4, 5, 6}, set())

    def test_all_ships_agree(self):
        for scen in ("instant", "gossip", "reverse", "bursty"):
            ships = S.deliver(self.p, self.authored, scen)
            self.assertTrue(all(s.st.digest() == self.ref for s in ships), scen)

    def test_everything_closes(self):
        out = self.st.story
        opens = {O.O_DEC_OPEN: 0, O.O_DIL_OPEN: 0, O.O_RES_OPEN: 0}
        closes = {O.O_DEC_CLOSE: 0, O.O_DIL_CLOSE: 0, O.O_RES_CLOSE: 0}
        dil_inactive = []
        for i in range(0, len(out), 8):
            code = out[i + 1]
            if code in opens:
                opens[code] += 1
            if code in closes:
                closes[code] += 1
            if code == O.O_DIL_CLOSE and out[i + 3] in (4, 5, 6):
                dil_inactive.append(out[i + 5])
        still_open = len(self.st.pend)
        self.assertEqual(sum(opens.values()), sum(closes.values()) + still_open)
        for it in self.st.pend:
            self.assertGreaterEqual(it[3], self.p.season)    # only ones due after the end
        self.assertTrue(all(x == 1 for x in dil_inactive))   # their astronauts decided

    def test_inactive_drops_kept_and_no_streak_shame(self):
        t = E.load_table(TABLE)
        en = E.Engage(t, self.p.voyage_key, self.p.season)
        local = E.Local(self.p.season)
        for c in (4, 5, 6):
            v = E.view(en, local, self.p, self.st, self.log, c, 600)
            self.assertEqual(len(v["drops"]), self.p.season)            # every day still there
            self.assertTrue(all(d[3] == 0 for d in v["drops"]))          # all still openable
            self.assertEqual((v["streak"]["cur"], v["streak"]["best"]), (0, 0))
            self.assertEqual(v["gifts"]["asks"], [])                     # asks to them lapsed

    def test_no_guilt_words(self):
        words = re.compile(r"\b(miss(ed|ing) you|fail(ed)?|lost (your|the) streak|shame|lazy|"
                           r"abandon|neglect|let (the|your) crew down|disappoint)", re.I)
        for name in ("drops", "jobs", "gifts", "collections"):
            with open(os.path.join(ROOT, "content", "engage", name + ".json"), encoding="utf-8") as f:
                data = json.load(f)
            for _, s in _texts(data):
                self.assertIsNone(words.search(s), (name, s))
        web = ""
        path = os.path.join(ROOT, "web", "engage.js")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                web = f.read()
        for s in re.findall(r'"([^"]{12,})"', web):
            self.assertIsNone(words.search(s), s)


def _texts(o, w=""):
    if isinstance(o, str):
        yield w, o
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _texts(v, w)
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _texts(v, w)


if __name__ == "__main__":
    unittest.main(verbosity=1)
