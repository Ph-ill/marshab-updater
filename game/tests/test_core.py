#!/usr/bin/env python3
"""Core unit tests (CPython). Run from anywhere: python3 game/tests/test_core.py"""
import hmac
import hashlib
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lv import record as R              # noqa: E402
from lv.chlog import ChoiceLog, NEW, DUP, REPLACED, STALE, BAD  # noqa: E402
from lv.prng import Rng, day_seed       # noqa: E402
from lv.pack import load                # noqa: E402
from lv.state import State              # noqa: E402
from lv.engine import Engine            # noqa: E402

FK = b"test-fleet-key-not-secret"
PACK = os.path.join(ROOT, "build", "pack.bin")


class TestPrng(unittest.TestCase):
    def test_known_sequence(self):
        r = Rng(1)
        # xorshift32 (13, 17, 5) from seed 1
        self.assertEqual([r.next() for _ in range(3)], [270369, 67634689, 2647435461])

    def test_zero_seed_is_not_stuck(self):
        r = Rng(0)
        self.assertNotEqual(r.next(), 0)

    def test_below_in_range(self):
        r = Rng(12345)
        self.assertTrue(all(0 <= r.below(7) < 7 for _ in range(1000)))

    def test_day_seed_depends_on_key_and_day(self):
        k = bytes(8)
        self.assertNotEqual(day_seed(k, 1), day_seed(k, 2))
        self.assertNotEqual(day_seed(k, 1), day_seed(b"\x01" + bytes(7), 1))


class TestRecord(unittest.TestCase):
    def test_hmac_matches_stdlib(self):
        for n in (0, 9, 64, 65, 200):
            key = bytes(range(n % 256))[:n] if n else b"k"
            msg = bytes(range(9))
            self.assertEqual(R.hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())

    def test_roundtrip_fields(self):
        r = R.encode(FK, R.VOTE, 3, 1, 513, 9, 4, 1)
        self.assertEqual(len(r), R.LEN)
        self.assertTrue(R.valid(FK, r))
        self.assertEqual((R.kind(r), R.ship(r), R.delay(r), R.seq(r), R.day(r), R.eff_day(r)),
                         (R.VOTE, 3, 1, 513, 9, 10))

    def test_tamper_and_wrong_key(self):
        r = bytearray(R.encode(FK, R.ACTION, 1, 1, 1, 2, 0, 0, 3))
        self.assertFalse(R.valid(b"other", bytes(r)))
        r[5] ^= 1
        self.assertFalse(R.valid(FK, bytes(r)))


class TestMerge(unittest.TestCase):
    def test_merge_results(self):
        log = ChoiceLog(FK)
        a = R.encode(FK, R.ACTION, 2, 1, 5, 4, 0, 0, 1)
        b = R.encode(FK, R.ACTION, 2, 1, 6, 4, 1, 2, 0)   # same key, newer seq
        self.assertEqual(log.merge(a), NEW)
        self.assertEqual(log.merge(a), DUP)
        self.assertEqual(log.merge(b), REPLACED)
        self.assertEqual(log.merge(a), STALE)
        self.assertEqual(log.merge(b[:-1] + bytes([b[-1] ^ 1])), BAD)
        self.assertEqual(len(log), 1)

    def test_two_votes_same_day_both_kept(self):
        log = ChoiceLog(FK)
        log.merge(R.encode(FK, R.VOTE, 1, 1, 1, 8, 3, 0))
        log.merge(R.encode(FK, R.VOTE, 1, 1, 2, 8, 5, 1))
        self.assertEqual(len(log), 2)

    def test_order_independent(self):
        rnd = random.Random(3)
        recs = []
        for i in range(300):
            recs.append(R.encode(FK, rnd.choice((R.ACTION, R.VOTE, R.NOTE)), rnd.randrange(7),
                                 rnd.choice((1, 3)), rnd.randrange(4), rnd.randrange(1, 8),
                                 rnd.randrange(3), rnd.randrange(2), rnd.randrange(7)))
        digests = set()
        for _ in range(5):
            rnd.shuffle(recs)
            log = ChoiceLog(FK)
            for r in recs + recs[:50]:
                log.merge(r)
            digests.add(log.digest())
        self.assertEqual(len(digests), 1)

    def test_unknown_schema_kept_not_used(self):
        log = ChoiceLog(FK)
        r = bytearray(R.encode(FK, R.ACTION, 1, 1, 1, 2, 0))
        r[0] = (R.ACTION << 4) | 2
        body = bytes(r[:9])
        r = body + R.hmac_sha256(FK, body)[:4]
        self.assertEqual(log.merge(r), NEW)
        self.assertEqual(log.effective(3), [])
        self.assertIn(r, log.all_records())


@unittest.skipUnless(os.path.exists(PACK), "run tools/lvc.py first")
class TestEngine(unittest.TestCase):
    def setUp(self):
        self.pack = load(PACK)

    def run_days(self, log, days):
        st = State(self.pack)
        eng = Engine(self.pack, st, log)
        for _ in range(days):
            eng.tick()
        return st

    def test_snapshot_roundtrip(self):
        st = self.run_days(ChoiceLog(FK), 10)
        self.assertEqual(State.load(st.dump()).dump(), st.dump())

    def test_resume_from_snapshot_equals_straight_run(self):
        log = ChoiceLog(FK)
        straight = self.run_days(log, 20)
        st = self.run_days(log, 7)
        st = State.load(st.dump())
        eng = Engine(self.pack, st, log)
        for _ in range(13):
            eng.tick()
        self.assertEqual(st.digest(), straight.digest())

    def test_nobody_plays_still_finishes(self):
        st = self.run_days(ChoiceLog(FK), self.pack.season)
        self.assertNotEqual(st.ending, 255)

    def test_late_record_changes_story_and_replay_converges(self):
        log = ChoiceLog(FK)
        base = self.run_days(log, 12).digest()
        log.merge(R.encode(FK, R.ACTION, 0, 3, 1, 5, 0, 0, 1))   # gift to crew 1, effect day 8
        late = self.run_days(log, 12).digest()
        self.assertNotEqual(base, late)


if __name__ == "__main__":
    unittest.main(verbosity=1)
