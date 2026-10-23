#!/usr/bin/env python3
"""Ship-to-ship sync protocol tests (CPython): lv/sync.py over the in-memory transport
(sim/link.py), so no radio is involved. The radio layer (lv/ble.py) is covered by
tests/mp_sync.py on a fake `bluetooth` module, under CPython and MicroPython."""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from lv import record as R              # noqa: E402
from lv import sync as S                # noqa: E402
from lv.chlog import ChoiceLog          # noqa: E402
from lv.engine import Engine            # noqa: E402
from lv.pack import load                # noqa: E402
from lv.state import State              # noqa: E402
from sim.link import LoopLink           # noqa: E402

FK = b"test-fleet-key-not-secret"
with open("build/season_log.bin", "rb") as f:
    RAW = f.read()
RECS = [RAW[i:i + R.LEN] for i in range(0, len(RAW), R.LEN)]


def node(ship, authors=None, recs=RECS, day=42):
    log = ChoiceLog(FK)
    for r in recs:
        if authors is None or R.ship(r) in authors:
            log.merge(r)
    return S.Node(log, ship, FK, day)


FULL = node(0).digest()


def sync(a, b, size=20, fault=None, cut=None, now=0):
    sa = S.Session(a, now, size, opener=True)
    sb = S.Session(b, now, size, opener=False)
    LoopLink(sa, sb, fault).run(now, cut=cut)
    return sa, sb


def faults(rng, drop=0, dup=0, reorder=0):
    def f(chunk, to):
        if rng.random() < drop:
            return []
        out = [(rng.randrange(1, 6) if rng.random() < reorder else 0, chunk)]
        if rng.random() < dup:
            out.append((rng.randrange(0, 6), chunk))
        return out
    return f


def unknown_rec(ship, seq):
    r = bytearray(R.encode(FK, R.GIFT, ship, 1, seq, 9, 1, 2, 0))
    r[0] = (r[0] & 0xF0) | (R.SCHEMA + 1)            # a schema from newer firmware
    r[9:13] = R.hmac_sha256(FK, bytes(r[:9]))[:4]
    return bytes(r)


class Advert(unittest.TestCase):
    def test_round_trip(self):
        n = node(3, (3,))
        adv = S.adv_data(n.advert(busy=True))
        self.assertLessEqual(len(adv), 31)
        p = S.parse_advert(adv)
        self.assertEqual((p["proto"], p["ship"], p["busy"], p["day"], p["n"]),
                         (S.PROTO, 3, True, 42, len(n.log)))
        self.assertEqual(p["digest"], n.digest())
        self.assertEqual(p["fid"], S.fleet_id(FK))
        self.assertNotEqual(S.fleet_id(b"another fleet"), S.fleet_id(FK))
        self.assertFalse(S.parse_advert(S.adv_data(n.advert()))["busy"])

    def test_foreign_and_broken(self):
        p = bytearray(node(1, ()).advert())
        p[0] = 0x4C                                      # someone else's company id
        self.assertIsNone(S.parse_advert(S.adv_data(bytes(p))))
        self.assertIsNone(S.parse_advert(b""))
        self.assertIsNone(S.parse_advert(b"\x02\x01\x06\x00"))
        self.assertIsNone(S.parse_advert(b"\x10\xff\xff\xffLV"))  # truncated
        # Our advert behind a device name still parses.
        adv = b"\x05\x09ship" + S.adv_data(node(2, ()).advert())
        self.assertEqual(S.parse_advert(adv)["ship"], 2)


class Pair(unittest.TestCase):
    def check(self, a, b, sa, sb):
        self.assertTrue(sa.complete() and sb.complete(), (sa.why, sb.why))
        self.assertEqual(a.digest(), FULL)
        self.assertEqual(b.digest(), FULL)

    def test_clean_both_ways(self):
        for size in (20, 125, 244):
            a, b = node(0, (0, 2, 4, 6, 15)), node(1, (1, 3, 5, 7))
            sa, sb = sync(a, b, size)
            self.check(a, b, sa, sb)
            self.assertEqual(sa.added + sb.added, len(RECS))

    def test_only_what_is_missing(self):
        # B already has everything but ship 5's last week: only those records move.
        late = [r for r in RECS if R.ship(r) == 5 and R.day(r) > 34]
        a = node(0)
        b = node(1, recs=[r for r in RECS if r not in late])
        sa, sb = sync(a, b)
        self.check(a, b, sa, sb)
        self.assertEqual(sb.added, len(late))
        self.assertLess(sa.sent, 3 * len(late) + 20)  # its 8-day block, not the season

    def test_in_sync_is_quick(self):
        a, b = node(0), node(1)
        sa, sb = sync(a, b)
        self.check(a, b, sa, sb)
        self.assertEqual(sa.sent + sb.sent, 0)

    def test_fault_matrix(self):
        rng = random.Random(7)
        for drop, dup, reorder in ((0.05, 0, 0), (0, 0.2, 0), (0, 0, 0.3),
                                   (0.05, 0.05, 0.1), (0.15, 0.1, 0.2)):
            for size in (20, 125):
                a, b = node(0, (0, 2, 4, 6, 15)), node(1, (1, 3, 5, 7))
                tries = 0
                while a.digest() != FULL or b.digest() != FULL:
                    tries += 1
                    self.assertLess(tries, 6, (drop, dup, reorder, size))
                    sync(a, b, size, faults(rng, drop, dup, reorder))
                self.assertEqual(len(a.log), len(RECS), (drop, dup, reorder, size))

    def test_mid_transfer_disconnect_keeps_progress(self):
        a, b = node(0, (0, 2, 4, 6, 15)), node(1, (1, 3, 5, 7))
        sa, sb = sync(a, b, 20, cut=60)
        self.assertFalse(sa.complete() and sb.complete())
        moved = len(a.log) + len(b.log) - len(RECS)
        self.assertGreater(moved, 0)                       # completed messages were kept
        sa, sb = sync(a, b, 20, now=100000)                # the next encounter finishes
        self.check(a, b, sa, sb)
        self.assertEqual(sa.added + sb.added, len(RECS) - moved)   # and only the rest moves

    def test_silent_peer_times_out(self):
        a = node(0)
        sa = S.Session(a, 0, 20)
        now = 0
        while sa.state == S.RUN and now < 60000:
            now += 100
            sa.pump(lambda c: True, now)
        self.assertEqual(sa.state, S.FAIL)
        self.assertLessEqual(now, S.SESSION_MS)
        self.assertIn(sa.retries, (S.RETRIES - 1, S.RETRIES))

    def test_garbage_and_forged_records(self):
        a, b = node(0, (0,)), node(1, (1,))
        sa = S.Session(a, 0, 20, opener=False)
        sa.feed(b"\xff\x00\x00\x00junk", 0)              # truncated: ignored
        for mid in range(1, 200):                          # never-finished messages
            sa.feed(bytes((4, mid, 0, 16)) + b"abcd", 0)
        self.assertLessEqual(len(sa.parts), 2)             # bounded, whatever arrives
        sa.feed(bytes((1, 201, 0, 1)) + b"X", 0)            # unknown message type
        self.assertEqual(sa.state, S.RUN)
        sa.feed(bytes((2, 202, 0, 1)) + b"H\x09", 0)        # HELLO from protocol 9
        self.assertEqual((sa.state, sa.why), (S.FAIL, "proto"))
        bad = bytearray(RECS[0])
        bad[5] ^= 1                                       # tag no longer matches
        self.assertEqual(a.merge([bytes(bad)]), 0)
        self.assertEqual(len(b.log), len([r for r in RECS if R.ship(r) == 1]))

    def test_hash_collision_falls_back_to_everything(self):
        class Blind(S.Node):
            def buckets(self):
                return bytes(2 * S.NB)                    # every bucket "matches"
        a = Blind(node(0, (0, 2, 4, 6, 15)).log, 0, FK, 42)
        b = Blind(node(1, (1, 3, 5, 7)).log, 1, FK, 42)
        self.assertIsNone(a.wanted(b.buckets()))
        self.assertIsNone(a.wanted(b"\x00\x01"))           # unusable hashes: same answer
        sa, sb = sync(a, b)
        self.check(a, b, sa, sb)

    def test_unknown_records_relay(self):
        u = unknown_rec(4, 900)
        a, b, c = node(0, (0,)), node(1, (1,)), node(2, (2,))
        self.assertEqual(a.merge([u]), 1)
        sync(a, b)
        sync(b, c)
        self.assertEqual(c.log.unknown, [u])
        sync(a, c)
        self.assertEqual(c.log.unknown, [u])               # no duplicate
        self.assertEqual(len(c.log), len([r for r in RECS if R.ship(r) in (0, 1, 2)]))


class Fleet(unittest.TestCase):
    """8 ships, each starting with only what its own crew wrote (ship 0 also holds the
    admin records), meeting in random pairs: everyone converges, whatever the order,
    and the story replayed from the synced log matches the reference season."""

    PACK = load("build/pack.bin")
    EXPECT = [ln.strip() for ln in open("build/season_expect.txt") if ln.strip()]

    def fleet(self):
        return [node(s, (s, 15) if s == 0 else (s,)) for s in range(8)]

    def replay(self, log):
        st = State(self.PACK)
        bad = 0
        for d in range(1, self.PACK.season + 1):
            Engine(self.PACK, st, log).tick()
            bad += st.hexdigest() != self.EXPECT[d - 1]
        return bad

    def test_random_encounter_orders(self):
        for seed in range(4):
            rng = random.Random(seed)
            ships = self.fleet()
            meets = 0
            while any(n.digest() != FULL for n in ships):
                i, j = rng.sample(range(8), 2)
                f = faults(rng, 0.03, 0.03, 0.05) if seed & 1 else None
                sync(ships[i], ships[j], rng.choice((20, 125)), f, now=meets * 60000)
                meets += 1
                self.assertLess(meets, 400, seed)
            self.assertEqual(self.replay(ships[rng.randrange(8)].log), 0, seed)

    def test_inactive_ships_block_nobody(self):
        # Ships 5-7 never come near anyone: the rest still converge on what exists.
        ships = self.fleet()
        active = ships[:5]
        want = node(0, (0, 1, 2, 3, 4, 15)).digest()
        rng = random.Random(99)
        for _ in range(60):
            i, j = rng.sample(range(5), 2)
            sync(active[i], active[j])
        self.assertTrue(all(n.digest() == want for n in active))
        # One comes back weeks later and catches up in one encounter, both ways.
        late = ships[6]
        sa, sb = sync(late, active[2])
        self.assertTrue(sa.complete() and sb.complete())
        self.assertEqual(late.digest(), active[2].digest())


if __name__ == "__main__":
    unittest.main()
