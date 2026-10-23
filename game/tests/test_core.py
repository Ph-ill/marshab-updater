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

from lv import codes as K               # noqa: E402
from lv import record as R              # noqa: E402
from lv.chlog import ChoiceLog, NEW, DUP, REPLACED, STALE, BAD  # noqa: E402
from lv.prng import Rng, day_seed       # noqa: E402
from lv.pack import load                # noqa: E402
from lv.state import State              # noqa: E402
from lv.engine import Engine            # noqa: E402
from lv import codes as K               # noqa: E402

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
            # Authors and targets over the whole fleet (K.N ships), the eighth included.
            recs.append(R.encode(FK, rnd.choice((R.ACTION, R.VOTE, R.NOTE)), rnd.randrange(K.N),
                                 rnd.choice((1, 3)), rnd.randrange(4), rnd.randrange(1, 8),
                                 rnd.randrange(3), rnd.randrange(2), rnd.randrange(K.N)))
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


class TestCodes(unittest.TestCase):
    SALT = bytes(range(16))

    def book(self):
        return K.CodeBook(K.make_config(["1234", "0000", None, "9999", "4711", "2024", "0420"], self.SALT))

    def test_known_digest(self):
        # The same vector is checked on the updater side (tests/unit.test.mjs), so the
        # browser and the board agree on how a code is hashed.
        self.assertEqual(K.digest(self.SALT, 0, "1234"),
                         "0cc8d81bab788a28b5390ce71859e989a5b3e623b8e1cb44c6bfadccc5ff03e4")

    def test_right_wrong_and_unset(self):
        b = self.book()
        self.assertEqual(b.check(0, "1234", 0), (K.OK, 0))
        self.assertEqual(b.check(0, "1235", 0), (K.WRONG, 4))
        self.assertEqual(b.check(1, "1234", 0), (K.WRONG, 4))   # codes are per person
        self.assertEqual(b.check(2, "1234", 0), (K.NO_CODE, 0))
        self.assertEqual(b.check(K.N, "1234", 0), (K.BAD, 0))
        self.assertEqual(b.check(0, "12a4", 0), (K.BAD, 0))
        self.assertEqual(b.check(0, "123", 0), (K.BAD, 0))

    def test_lockout_after_five_wrong(self):
        b = self.book()
        got = [b.check(3, "0000", 1000)[0] for _ in range(5)]
        self.assertEqual(got, [K.WRONG] * 4 + [K.LOCKED])
        # Even the right code is refused while locked, and the wait counts down.
        self.assertEqual(b.check(3, "9999", 1000), (K.LOCKED, 300))
        self.assertEqual(b.check(3, "9999", 1000 + 60000), (K.LOCKED, 240))
        self.assertEqual(b.check(3, "9999", 1000 + 299001), (K.LOCKED, 1))
        # Other crew members aren't affected.
        self.assertEqual(b.check(0, "1234", 1000), (K.OK, 0))
        # After five minutes there's a fresh set of five tries.
        self.assertEqual(b.check(3, "0001", 1000 + K.LOCK_MS), (K.WRONG, 4))
        self.assertEqual(b.check(3, "9999", 1000 + K.LOCK_MS), (K.OK, 0))

    def test_right_code_resets_the_count(self):
        b = self.book()
        for _ in range(4):
            b.check(4, "0000", 0)
        self.assertEqual(b.check(4, "4711", 0), (K.OK, 0))
        self.assertEqual(b.check(4, "0000", 0), (K.WRONG, 4))

    def test_phone_remembered_for_the_flight_day_only(self):
        b = self.book()
        b.remember("192.168.4.2|ua", 4, 8)
        self.assertEqual(b.recall("192.168.4.2|ua", 8), 4)
        self.assertIsNone(b.recall("192.168.4.3|ua", 8))
        self.assertIsNone(b.recall("192.168.4.2|ua", 9))
        self.assertIsNone(b.recall("192.168.4.2|ua", 8))   # day 9 cleared it
        b.remember("p", 1, 9)
        b.remember("p", 2, 9)                              # signing in as someone else replaces
        self.assertEqual(b.recall("p", 9), 2)
        b.forget("p")
        self.assertIsNone(b.recall("p", 9))

    def test_remembered_list_is_bounded(self):
        b = self.book()
        for i in range(K.MAX_PHONES + 5):
            b.remember("p%d" % i, 0, 1)
        self.assertEqual(len(b.phones), K.MAX_PHONES)
        self.assertIsNone(b.recall("p0", 1))
        self.assertEqual(b.recall("p%d" % (K.MAX_PHONES + 4), 1), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
