#!/usr/bin/env python3
"""Compiler and content tests: card-language features (roster tags, cliffhanger hooks)
and house-style checks over the real card set. Run: python3 game/tests/test_content.py"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import lvc                              # noqa: E402
from lv import ops as O                 # noqa: E402
from lv.chlog import ChoiceLog          # noqa: E402
from lv.engine import Engine            # noqa: E402
from lv.pack import Pack                # noqa: E402
from lv.state import State, N           # noqa: E402

FK = b"test-fleet-key-not-secret"
CONTENT = os.path.join(ROOT, "content")


def mini_content(cards, roster=None):
    """A throwaway content dir: the real fleet.lv and system.json, custom roster and cards."""
    d = tempfile.mkdtemp(prefix="lvc-")
    shutil.copy(os.path.join(CONTENT, "fleet.lv"), d)
    shutil.copy(os.path.join(CONTENT, "system.json"), d)
    names = ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian", "Marco"]
    if roster is None:
        roster = "\n".join("crew %s ship Ship 0%d%s" % (n, i + 1, "   tag mech" if n == "Diego" else "")
                           for i, n in enumerate(names))
    with open(os.path.join(d, "roster.lv"), "w") as f:
        f.write(roster + "\n")
    os.mkdir(os.path.join(d, "cards"))
    with open(os.path.join(d, "cards", "10_test.lv"), "w") as f:
        f.write(cards + "\ncard end_x\ntype ending\ntext The end.\n")
    return d


def season(pack):
    st = State(pack)
    eng = Engine(pack, st, ChoiceLog(FK))
    days = []
    for _ in range(pack.season):
        eng.tick()
        days.append(bytes(st.out))
    return st, days


def events(out, card_idx):
    for i in range(0, len(out), 8):
        e = out[i:i + 8]
        if e[1] == O.O_EVENT and e[2] == card_idx:
            yield e


TAG_CARD = """
card bracket
type beat
weight 50
cooldown 1
roles A
when tag A mech
text {A} {A:looks} at the bracket.
"""


class TestTags(unittest.TestCase):
    def test_tag_binds_only_tagged_crew(self):
        d = mini_content(TAG_CARD)
        pack, text, ctx = lvc.build(d)
        self.assertEqual(ctx.errors, [])
        p = Pack(pack)
        st, days = season(p)
        seen = [e[3] for out in days for e in events(out, 0)]
        self.assertTrue(seen, "the tagged card never fired")
        self.assertEqual(set(seen), {5})  # Diego is crew index 5

    def test_unknown_tag_is_an_error(self):
        d = mini_content(TAG_CARD.replace("tag A mech", "tag A pilot"))
        _, _, ctx = lvc.build(d)
        self.assertTrue(any("tag" in e for e in ctx.errors), ctx.errors)

    def test_tags_never_leak_into_text_json(self):
        d = mini_content(TAG_CARD)
        _, text, _ = lvc.build(d)
        self.assertNotIn("mech", repr(text["crew"]) + repr(text["ships"]))

    def test_ship_name_stops_at_tag(self):
        cr = lvc.parse_crew("crew Diego ship Ship 06 tag mech tag cad flagship".split())
        self.assertEqual(cr["ship"], "Ship 06")
        self.assertEqual(cr["tags"], ["mech", "cad"])
        self.assertTrue(cr["flagship"])


def hook_cards(n):
    out = []
    for i in range(n):
        out.append("""
card h%d
type event
hook
once
days 2 40
roles A
when cond A ok
do who hook_who A
text At 23:40 something happens to {A}. (%d)

card r%d
type event
due
once
days 2 42
roles A
when fired h%d
when is A hook_who
text {A} {A:sorts} it out. (%d)
""" % (i, i, i, i, i))
    filler = """
card filler
type beat
weight 50
cooldown 1
roles A
text {A} {A:makes} coffee.

card ev
type event
cooldown 1
roles A
text {A} {A:checks} the dosimeter.
"""
    return "".join(out) + filler


class TestHooks(unittest.TestCase):
    def build(self, n=12):
        pack, text, ctx = lvc.build(mini_content(hook_cards(n)))
        self.assertEqual(ctx.errors, [])
        return Pack(pack), text

    def test_hook_is_last_line_and_resolves_next_day(self):
        p, text = self.build()
        ids = [c["id"] for c in text["cards"]]
        st, days = season(p)
        hook_days = []
        for d, out in enumerate(days, 1):
            ent = [out[i:i + 8] for i in range(0, len(out), 8)]
            for k, e in enumerate(ent):
                if e[1] == O.O_EVENT and ids[e[2]].startswith("h"):
                    self.assertEqual(k, len(ent) - 1, "hook not last on day %d" % d)
                    hook_days.append((d, ids[e[2]], e[3]))
        self.assertGreaterEqual(len(hook_days), 4, hook_days)
        for (d, hid, who) in hook_days:
            nxt = [e for e in events(days[d], ids.index("r" + hid[1:]))]
            self.assertEqual(len(nxt), 1, "resolver for %s missing on day %d" % (hid, d + 1))
            self.assertEqual(nxt[0][3], who, "resolver bound someone else")
        gaps = [b[0] - a[0] for a, b in zip(hook_days, hook_days[1:])]
        self.assertTrue(all(g >= O.HOOK_GAP for g in gaps), gaps)
        self.assertTrue(all(d <= p.season - 2 for d, _, _ in hook_days))

    def test_text_json_marks_hooks(self):
        _, text = self.build(2)
        marked = [c["id"] for c in text["cards"] if c.get("h")]
        self.assertEqual(marked, ["h0", "h1"])

    def test_hook_without_resolver_is_an_error(self):
        src = hook_cards(1).replace("when fired h0", "when day >= 2")
        _, _, ctx = lvc.build(mini_content(src))
        self.assertTrue(any("no resolver" in e for e in ctx.errors), ctx.errors)

    def test_hook_must_be_once_event_and_end_early(self):
        src = hook_cards(1).replace("hook\nonce\ndays 2 40", "hook\ndays 2 41")
        _, _, ctx = lvc.build(mini_content(src))
        msg = " ".join(ctx.errors)
        self.assertIn("needs `once`", msg)
        self.assertIn("last 2 days", msg)


class TestHouseStyle(unittest.TestCase):
    """The real card set stays inside content/STYLE.md."""

    @classmethod
    def setUpClass(cls):
        cls.pack, cls.text, cls.ctx = lvc.build(CONTENT)
        cls.cards = cls.ctx.cards

    def test_compiles(self):
        self.assertEqual(self.ctx.errors, [])

    def test_no_style_warnings(self):
        self.assertEqual([w for w in self.ctx.warnings if w.startswith("style:")], [])

    def test_retired_tics_stay_retired(self):
        # STYLE.md rounds 4-8 retired these; they kept creeping back, so they are
        # linted here over every card, option and system string.
        tics = [r"\bnobody\b", r"\breads? it twice\b", r"\btap(e|es|ed|ing)\b[^.]*\b(above|to the|wall)",
                r"\bpin(s|ned)\b[^.]*\b(above|up\b|wall)", r"\bpinned up\b", r"galley wall",
                r"\b(go|goes|went|gone|going) quiet\b", r"since Starbase", r"\bslowly\b",
                r"doesn't mention", r"\bNeither of them\b", r"\bby itself\b", r"it has moved",
                r"\bsleeve\b[^.]*\bsleeve\b",
                # round 20: shared habit openers, the doubled tie clause, the training tag
                r"Every data drop", r"\bLast (mail|video) before entry", r"\bno strays\b",
                r"flight director takes it", r"as training\. It is\."]
        strs = []

        def walk(x, where):
            if isinstance(x, str):
                strs.append((where, x))
            elif isinstance(x, dict):
                for k, v in x.items():
                    walk(v, where + "." + str(k))
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, "%s[%d]" % (where, i))
        walk(self.text, "text")
        hits = [(w, t) for t in tics for w, s in strs if re.search(t, s, re.I)]
        self.assertEqual(hits, [])

    def test_lint_catches_the_bad_examples(self):
        bad = """
card bad
type beat
roles A
text As a controls engineer, {A} forgot the seals again. By month four it was just a glitch. Kim laughs.
"""
        _, _, ctx = lvc.build(mini_content(bad))
        msg = " ".join(ctx.warnings)
        for needle in ("name-checks", "butt of the joke", "cheap resolution", "calendar", "names Kim"):
            self.assertIn(needle, msg)

    def test_every_hook_resolves(self):
        ids = [c["id"] for c in self.text["cards"]]
        hooks = [c["id"] for c in self.text["cards"] if c.get("h")]
        self.assertGreaterEqual(len(hooks), 8)
        for h in hooks:
            self.assertIn("r_" + h[2:], ids)

    def test_content_mix(self):
        # STYLE.md "Content mix": repairs <= 25%, skill flavor <= ~1 in 6, all tagged.
        mix, n = self.ctx.mix, len(self.text["cards"])
        self.assertEqual(sum(v for k, v in mix.items() if k != "skill"), n)
        self.assertLessEqual(mix["repair"], lvc.MAX_REPAIR * n)
        self.assertLessEqual(mix["skill"], lvc.MAX_SKILL * n)
        for cat in ("wonder", "mystery", "human", "life", "mission", "arrival", "grim"):
            self.assertGreater(mix[cat], 0, cat)
        print("\n" + lvc.mix_line(self.ctx), file=sys.stderr)

    def test_mix_lint_fails_a_repair_heavy_deck(self):
        src = "".join("card fix%d\ntype beat\ncat repair%s\nroles A\ntext {A} {A:fixes} thing %d.\n\n"
                      % (i, " skill" if i < 2 else "", i) for i in range(3))
        src += "card ok1\ntype beat\ncat life\nroles A\ntext {A} {A:sleeps}.\n\ncard un\ntype beat\nroles A\ntext {A} {A:waits}.\n"
        _, _, ctx = lvc.build(mini_content(src))
        msg = " ".join(ctx.warnings)
        self.assertIn("repair/fault", msg)
        self.assertIn("skill flavor", msg)
        self.assertIn("no `cat` line", msg)

    def test_bad_category_is_an_error(self):
        _, _, ctx = lvc.build(mini_content("card x\ntype beat\ncat plumbing\nroles A\ntext {A}.\n"))
        self.assertTrue(any("cat is" in e for e in ctx.errors))

    def test_slow_burn_lint(self):
        src = ("card early\ntype beat\ncat life\ndays 2 20\nroles A\ntext {A} {A:feels} a chill. Something is wrong.\n\n"
               "card early_m\ntype beat\ncat mystery\ndays 5 20\nroles A\ntext {A} {A:logs} a number.\n\n"
               "card late\ntype beat\ncat mystery\ndays 30 40\nroles A\ntext {A} {A:feels} a chill.\n")
        _, _, ctx = lvc.build(mini_content(src))
        ws = [w for w in ctx.warnings if "keep days" in w or "cat mystery but" in w]
        self.assertTrue(any("early " in w and "chill" in w for w in ws))
        self.assertTrue(any("early_m" in w for w in ws))
        self.assertFalse(any(" late " in w for w in ws))

    def test_mystery_ramp(self):
        # STYLE.md "The slow burn": nothing in days 1-10, most of the thread after 25.
        phases = [0, 0, 0, 0]
        for c in self.cards:
            if c["cat"] == "mystery":
                d0 = c["days"][0]
                phases[0 if d0 <= 10 else 1 if d0 <= 24 else 2 if d0 <= 36 else 3] += 1
        self.assertEqual(phases[0], 0)
        self.assertLess(phases[1], phases[2])
        self.assertGreater(phases[3], 0)
        print("mystery cards by first day, phases 1-4:", phases, file=sys.stderr)

    def test_second_read_clues(self):
        # STORY_BIBLE.md: 6-12 fair-play clues (a core group's variants count once),
        # at least two in the earliest phase.
        rr = self.text["reread"]
        grouped = {i for g in self.text["core"] if len(g) > 1 for i in g[1:]}
        self.assertTrue(6 <= len([i for i in rr if i not in grouped]) + 1 <= 12)  # +1: system text
        early = [i for i in rr if self.cards[i]["days"][0] <= 10]
        self.assertGreaterEqual(len(early), 2)
        self.assertTrue(all(self.cards[i]["clue"] for i in rr))

    def test_mech_twin_is_not_exclusive(self):
        # The tagged twin must have an untagged sibling so anyone can draw the card.
        ids = [c["id"] for c in self.text["cards"]]
        for i in ids:
            if i.endswith("_m"):
                self.assertIn(i[:-2], ids)



class TestThreadConsistency(unittest.TestCase):
    """Facts the late thread states more than once must agree wherever they appear."""

    @classmethod
    def setUpClass(cls):
        _, cls.text, _ = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] for c in cls.text["cards"]}
        pack, _, _ = lvc.build(CONTENT)
        cls.pack = pack

    def _seasons(self, n=300):
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        for i in range(n):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            yield i, reference_season(Pack(self.pack), seed=1000 + i, voyage_key=key)[0].story

    def test_wake_all_is_always_followed_by_a_hold(self):
        # The patch says ON HELLO: WAKE ALL. Every scene that answers with a hello must
        # send the HOLD on the next tick, and no card may fall back to a "safe hold".
        self.assertIn("ON HELLO, WAKE ALL", self.t["a_patch"])
        for cid in ("a_window_hail", "a_suit_plan", "end_through", "end_close", "end_patience"):
            self.assertIn("HOLD", self.t[cid], cid)
        strs = [c["t"] for c in self.text["cards"]] + \
            [o[1] for c in self.text["cards"] for o in c.get("o", [])]
        self.assertEqual([s for s in strs if re.search(r"safe[- ]hold", s, re.I)], [])

    def test_battery_forecast_only_shortens(self):
        # The battery forecast may tighten as data comes in, never lengthen: "a week or
        # two after landing" (r_band / c2_cold) before "a few nights after landing".
        rank = {"r_band": ("a week or two after", 2), "c2_cold": ("a week or two after", 2),
                "c_hail": ("a few nights after landing, not weeks", 1)}
        for cid, (phrase, _) in rank.items():
            self.assertIn(phrase, self.t[cid], cid)
        ids = [c["id"] for c in self.text["cards"]]
        bad, full = [], 0
        for i, out in self._seasons():
            seen = [ids[out[k + 2]] for k in range(0, len(out), 8)
                    if out[k + 1] == O.O_EVENT and ids[out[k + 2]] in rank]
            rs = [rank[c][1] for c in seen]
            full += len(seen) >= 2
            if rs != sorted(rs, reverse=True):
                bad.append((i, seen))
        self.assertGreater(full, 250)
        self.assertEqual(bad, [])

    def test_no_visit_lines_on_the_day_of_a_crossing(self):
        # Someone who crossed today has not been aboard "since the last crossing".
        ids = [c["id"] for c in self.text["cards"]]
        pat = re.compile(r"\{A\}[^.]*\b(still aboard|since the last crossing|visiting since)", re.I)
        bad = []
        for i, out in self._seasons():
            moved = set()
            for k in range(0, len(out), 8):
                d, code, card, a = out[k:k + 4]
                if code == O.O_MOVE:
                    moved.add((d, a))
                elif code == O.O_EVENT and (d, a) in moved and pat.search(self.t[ids[card]]):
                    bad.append((i, d, ids[card]))
        self.assertEqual(bad, [])

    def _events(self, out, ids):
        return [(out[k], ids[out[k + 2]], out[k + 3]) for k in range(0, len(out), 8)
                if out[k + 1] == O.O_EVENT]

    def test_band_hook_waits_for_the_second_flash(self):
        # The night-gap hook must not name or lean on the lit pixel, and may only fire
        # once the pixel is established as a fixed ground spot (after m_flash2).
        self.assertNotIn("pixel", self.t["h_band"])
        ids = [c["id"] for c in self.text["cards"]]
        bad, fired = [], 0
        for i, out in self._seasons():
            ev = self._events(out, ids)
            hb = [d for d, c, _ in ev if c == "h_band"]
            if not hb:
                continue
            fired += 1
            f2 = [d for d, c, _ in ev if c == "m_flash2"]
            f1 = [d for d, c, _ in ev if c == "m_flash1"]
            if not f2 or hb[0] < f2[0] or (f1 and hb[0] == f1[0]):
                bad.append(i)
        self.assertEqual(bad, [])
        self.assertGreater(fired, 30)

    def test_knock_hook_stays_with_the_carrier_finder(self):
        # Whoever found the old-channel carrier owns the knock: h_band and its resolver
        # r_band go to the same astronaut as m_carrier.
        ids = [c["id"] for c in self.text["cards"]]
        bad = []
        for i, out in self._seasons():
            ev = self._events(out, ids)
            car = [a for _, c, a in ev if c == "m_carrier"]
            for _, c, a in ev:
                if c in ("h_band", "r_band") and (not car or a != car[0]):
                    bad.append((i, c))
        self.assertEqual(bad, [])

    def test_aerocapture_is_narrated_once(self):
        # e_entry_wait (day 42) narrates the aerocapture; no day-41 card may narrate it too
        # (looking ahead to it, "before aerocapture", is fine).
        ids = [c["id"] for c in self.text["cards"]]
        pat = re.compile(r"upper atmosphere|(?<!before )aerocaptur|into the long orbit", re.I)
        bad = []
        for i, out in self._seasons():
            ev = self._events(out, ids)
            if not any(c == "e_entry_wait" for _, c, _ in ev):
                continue
            bad += [(i, c) for d, c, _ in ev if d == 41 and pat.search(self.t[c])]
        self.assertEqual(bad, [])

    def _system(self):
        with open(os.path.join(CONTENT, "system.json"), encoding="utf-8") as f:
            return json.load(f)

    def _cached(self):
        # One 300-season run shared by the round-18 checks below.
        if not hasattr(TestThreadConsistency, "_runs"):
            TestThreadConsistency._runs = list(self._seasons())
        return TestThreadConsistency._runs

    def test_the_twist_is_an_expired_challenge(self):
        # Cargo 2 heard every hail (a_log: all late) and every knock carries a
        # fresh challenge (m_key); the patch keeps the challenge good for one tick.
        # Nothing may say it stopped listening.
        # Round 19: the patch (a_patch) carries the history and the four card lines;
        # a_report carries only the meaning, in one plain sentence.
        self.assertIn("ANSWER INSIDE ONE TICK", self.t["a_patch"])
        self.assertIn("all late", self.t["a_log"])
        self.assertIn("fresh challenge", self.t["m_key"])
        self.assertIn("sent it up twice", self.t["a_patch"])
        self.assertIn("neither upload was ever acknowledged", self.t["a_patch"])
        self.assertIn("Every one arrived after it had stopped waiting.", self.t["a_report"])
        strs = [c["t"] for c in self.text["cards"]]
        self.assertEqual([x for x in strs if re.search(r"LISTEN 1 TICK|stopped listening", x)], [])
        # The handshake comes off the laminated card, which always fires before day 41.
        for cid in ("a_window_hail", "a_suit_plan", "end_through", "end_patience"):
            self.assertIn("laminated card", self.t[cid], cid)
        ids = [c["id"] for c in self.text["cards"]]
        for i, out in self._cached():
            ev = self._events(out, ids)
            self.assertTrue(any(c == "sharpie2" and d < 41 for d, c, _ in ev), "season %d" % i)
        # Day 40 ends on the meaning: the report is the day's last card.
        for i, out in self._cached():
            d40 = [c for d, c, _ in self._events(out, ids) if d == 40]
            self.assertEqual(d40[-1], "a_report", "season %d" % i)

    def test_water_rationing_is_one_ship_and_crossings_keep_windows(self):
        # Rationing applies to the failing ship (the other six trim to send water),
        # and the repair crossing happens in a transfer window, after prebreathe.
        cards = {c["id"]: c for c in self.text["cards"]}
        degrade = [o[1] for o in cards["dec_water"].get("o", []) if "rationing" in o[1]]
        self.assertTrue(degrade and all("{A}'s ship goes on water rationing" in x for x in degrade))
        strs = [c["t"] for c in self.text["cards"]] + \
            [o[1] for c in self.text["cards"] for o in c.get("o", [])]
        self.assertEqual([x for x in strs if re.search(r"fleet (goes|went) on water rationing", x)], [])
        fails = [cid for cid in cards if cid.startswith("water_fail")]
        self.assertTrue(fails)
        for cid in fails:
            self.assertIn("prebreathe", self.t[cid], cid)
        ids = [c["id"] for c in self.text["cards"]]
        bad, seen = [], 0
        for i, out in self._cached():
            for d, c, _ in self._events(out, ids):
                if c in fails:
                    seen += 1
                    if d < O.TRANSFER_FROM or (d - O.TRANSFER_FROM) % O.TRANSFER_EVERY or d > O.TRANSFER_LAST_OUT:
                        bad.append((i, d, c))
        self.assertEqual(bad, [])
        self.assertGreater(seen, 30)

    def test_wrist_injury_rules_out_haircut_and_eva(self):
        # After the tether injury, the injured astronaut never cuts hair and never
        # resolves the iced-camera dilemma by going outside.
        ids = [c["id"] for c in self.text["cards"]]
        cam = ids.index("dil_eva_cam")
        go = [c for c in self.text["cards"] if c["id"] == "dil_eva_cam"][0]
        bad, hurt = [], 0
        for i, out in self._cached():
            injured = {}
            for k in range(0, len(out), 8):
                d, code, card, a = out[k], out[k + 1], out[k + 2], out[k + 3]
                if code == O.O_EVENT and ids[card] == "crisis_eva":
                    injured.setdefault(a, d)
                    hurt += 1
                elif code == O.O_EVENT and ids[card] == "beat_haircut" and a in injured:
                    bad.append((i, d, "haircut"))
                elif code == O.O_DIL_CLOSE and card == cam and out[k + 4] == 0 and a in injured:
                    bad.append((i, d, "eva"))
        self.assertEqual(bad, [])
        self.assertGreater(hurt, 0)

    def test_bread_only_after_the_bread_scene(self):
        # The galley bread (beat_coffee) is a random beat; no other line may mention
        # the bread before it, and the daily fold lines never do.
        sysj = self._system()
        self.assertEqual([x for x in sysj["sys"]["fold_pool"] if "bread" in x], [])
        ids = [c["id"] for c in self.text["cards"]]
        bread = {c for c in ids if c != "beat_coffee" and re.search(r"\bbread", self.t[c], re.I)}
        bad = []
        for i, out in self._cached():
            baked = None
            for d, c, _ in self._events(out, ids):
                if c == "beat_coffee" and baked is None:
                    baked = d
                if c in bread and (baked is None or d < baked):
                    bad.append((i, d, c))
        self.assertEqual(bad, [])

    def test_ballot_line_needs_no_count(self):
        # "{n} ballots in" reads "1 ballots in"; the close line names no number.
        sysj = self._system()
        self.assertNotIn("{n}", sysj["sys"]["dec_close"])


class TestCompactPack(unittest.TestCase):
    """Cards are indices into Pack.data; the decoded Card view and the engine's
    per-category lists must agree with a straight read of the header bytes."""

    @classmethod
    def setUpClass(cls):
        pack, _, _ = lvc.build(CONTENT)
        cls.p = Pack(pack)

    def test_card_view_matches_header(self):
        p = self.p
        for i in range(p.ncards):
            c = p.cards[i]
            q = p.hdr[i]
            self.assertEqual(c.idx, i)
            self.assertEqual((c.type, c.weight, c.dmin, c.dmax, c.flags, c.cooldown,
                              c.duration, c.nroles, c.laxis, c.lpos, c.lneg),
                             tuple(p.data[q:q + 11]))
            self.assertEqual(c.conds, p.conds(i))
            self.assertEqual(c.nopt, p.nopt(i))
            self.assertEqual(p.opt(c, 0), p.opt(i, 0))
        self.assertEqual(len(list(p.cards)), p.ncards)

    def test_category_lists_partition_cards(self):
        p = self.p
        seen = list(p.due) + list(p.events) + list(p.beats) + list(p.hooks) + \
            list(p.decisions) + list(p.dilemmas) + list(p.endings)
        rescues = [c.idx for c in p.cards if c.type == O.RESCUE]
        self.assertEqual(sorted(seen + rescues), list(range(p.ncards)))
        for i in p.hooks:
            self.assertTrue(p.cards[i].flags & O.F_HOOK)
        for i in p.events:
            self.assertEqual(p.cards[i].type, O.EVENT)
            self.assertFalse(p.cards[i].flags & (O.F_DUE | O.F_HOOK))
        for lst in (p.events, p.beats, p.decisions):
            self.assertEqual(list(lst), sorted(lst))


class TestFairCasting(unittest.TestCase):
    """Role casting tries the least-featured crew first (Engine._cast_order), so the
    spotlight evens out without anyone being locked out of a card."""

    def setUp(self):
        pack, _, _ = lvc.build(CONTENT)
        self.p = Pack(pack)

    def test_order_prefers_least_featured(self):
        from lv import engine as E
        st = State(self.p)
        eng = Engine(self.p, st, ChoiceLog(FK))
        st.spot[:] = bytes([9, 9, 0, 9, 9, 9, 1, 9])
        order = eng._cast_order(0)
        self.assertEqual(order[:2], [2, 6])  # bucket 0 first, ties rotate from start
        self.assertEqual(sorted(order), list(range(N)))
        st.spot[:] = bytes(N)
        self.assertEqual(eng._cast_order(3), [3, 4, 5, 6, 7, 0, 1, 2])
        self.assertEqual(E.FAIR_BUCKET, 2)

    def test_spot_survives_snapshot(self):
        st = State(self.p)
        st.spot[:] = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(State.load(st.dump()).spot, st.spot)

    def test_spotlight_spread_over_seasons(self):
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        tot = [0] * N
        for seed in range(1, 31):
            st = reference_season(Pack(self.p.data), seed=seed)[0]
            out = st.story
            for i in range(0, len(out), 8):
                if out[i + 1] in (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN):
                    for x in (out[i + 3], out[i + 4]):
                        if x < N:
                            tot[x] += 1
        mean = sum(tot) / float(N)
        for v in tot:
            self.assertLess(abs(v - mean) / mean, 0.10, tot)

    def test_presence_matches_text_over_300_seasons(self):
        # Text that places someone must agree with where the engine has them. Over the
        # same 300 seasons as the fair-play test, replaying each season's crossings:
        # "{A}'s ship" in an opening line means A is at home; "{A}, visiting", "{A} {A:is}
        # still aboard", "{A}, aboard on a visit" or "{A} {A:happens} to be aboard" means A is
        # away, on B's ship; a rescue option where "{B} {B:brings}
        # it over" or "{B} {B:rides} the line" means B was on another ship when it opened.
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        _, text, _ = lvc.build(CONTENT)
        cards = text["cards"]
        exempt = set()
        opens = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN)
        checks, bad = 0, []
        for i in range(300):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            out = reference_season(Pack(self.p.data), seed=1000 + i, voyage_key=key)[0].story
            loc, opened = list(range(N)), {}
            for k in range(0, len(out), 8):
                d, code, card, a, b = out[k:k + 5]
                if code == O.O_MOVE:
                    loc[a] = out[k + 5]
                    continue
                if code in opens:
                    cid, t = cards[card]["id"], cards[card]["t"]
                    if code == O.O_DIL_OPEN:
                        b = O.NONE
                    if code == O.O_RES_OPEN:
                        opened[card] = (a, b, loc[a] if a < N else None, loc[b] if b < N else None)
                    if a < N and "{A}'s ship" in t and cid not in exempt:
                        checks += 1
                        if loc[a] != a:
                            bad.append((i, d, cid, "A not home"))
                    if a < N and re.search(r"\{A\},? (visiting|(?:\{A:is\}|is) still aboard|aboard on a visit|(?:\{A:happens\}|happens) to be aboard)", t):
                        checks += 1
                        if loc[a] == a or (b < N and (loc[b] != b or loc[a] != b)):
                            bad.append((i, d, cid, "A not visiting B"))
                if code == O.O_RES_CLOSE and card in opened:
                    a0, b0, la, lb = opened.pop(card)
                    o = cards[card]["o"]
                    if b0 < N and a < len(o) and re.search(r"\{B\} (?:\{B:)?(brings|rides)", o[a][1]):
                        checks += 1
                        if la == lb:
                            bad.append((i, d, cards[card]["id"], "B already aboard"))
        self.assertGreater(checks, 5000)
        self.assertEqual(bad, [], "%d of %d presence checks failed" % (len(bad), checks))

    def test_tile_and_eva_casting_over_300_seasons(self):
        # Round 14 regressions. A line about the struck heat-shield tile must name the
        # astronaut whose tile r_strike found, and an ending (which can't bind that
        # person) must not mention the tile at all. Nobody whose wrist crisis_eva
        # injured is sent outside afterwards (dil_eva_cam, r_strike).
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        _, text, _ = lvc.build(CONTENT)
        cards = text["cards"]
        ids = [c["id"] for c in cards]
        for c in cards:
            if c["id"].startswith("end_"):
                self.assertNotRegex(c["t"], r"(?i)\b(tile|hinge)", c["id"])
        opens = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN)
        bad, tiles, evas = [], 0, 0
        for i in range(300):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            out = reference_season(Pack(self.p.data), seed=1000 + i, voyage_key=key)[0].story
            tile_who = hurt = None
            for k in range(0, len(out), 8):
                d, code, card, a, b = out[k:k + 5]
                if code not in opens:
                    continue
                cid, t = ids[card], cards[card]["t"]
                if cid == "crisis_eva":
                    hurt = a
                if cid in ("dil_eva_cam", "r_strike"):
                    evas += 1
                    if a == hurt:
                        bad.append((i, d, cid, "injured astronaut outside"))
                if cid == "r_strike":
                    tile_who = a
                elif re.search(r"(?i)\b(the|a|one|its) ([\w-]+ )?tile\b", t):
                    tiles += 1
                    if tile_who is None or tile_who not in (a, b):
                        bad.append((i, d, cid, "tile line names the wrong astronaut"))
        self.assertGreater(evas, 50)
        self.assertEqual(bad, [])

    def test_ending_and_prop_roles_match_who_did_it_over_300_seasons(self):
        # Round 15 regressions. Every ending role that a line credits with an earlier
        # act must be the astronaut who did it, and props stay in the right hands:
        #   all endings: A ("who wanted to answer") proposed the hello in dec_signal;
        #   end_long_orbit: B ("who argued to wait") is dec_arrival's B;
        #   end_through / end_lights: B is the pilot of the gusty entry (e_entry_hold*);
        #   p_packer_note: the locker line goes to the stash keeper, before it's shared;
        #   a_recall_shared: the last pack never goes to the one who already got one;
        #   water_fail: no splinted wrist rides the line.
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        _, text, _ = lvc.build(CONTENT)
        ids = [c["id"] for c in text["cards"]]
        opens = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN, O.O_END)
        bad, seen = [], {}
        for i in range(300):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            out = reference_season(Pack(self.p.data), seed=1000 + i, voyage_key=key)[0].story
            first = {}
            for k in range(0, len(out), 8):
                d, code, card, a, b = out[k:k + 5]
                if code in opens:
                    first.setdefault(ids[card], (d, a, b))

            def check(label, ok):
                seen[label] = seen.get(label, 0) + 1
                if not ok:
                    bad.append((i, label))
            end = [c for c in first if c.startswith("end_")]
            self.assertEqual(len(end), 1, "season %d" % i)
            end = end[0]
            _, ea, eb = first[end]
            if "dec_signal" in first:
                check("ending A proposed the hello", ea == first["dec_signal"][1])
            if end == "end_long_orbit":
                check("long orbit B argued to wait", eb == first["dec_arrival"][2])
            if end in ("end_through", "end_lights"):
                pilot = [first[c][1] for c in ("e_entry_hold", "e_entry_hold_q") if c in first]
                check("%s B flew the gusty entry" % end, pilot == [eb])
            if "p_packer_note" in first:
                st = first.get("dil_stash")
                check("packer note locker holder", st is not None and st[1] == first["p_packer_note"][1]
                      and ("stash_found" not in first or first["stash_found"][0] > first["p_packer_note"][0]))
            if "a_recall_shared" in first:
                check("last pack to a new hand", first["a_recall_shared"][2] != first["stash_found"][2])
            if "water_fail" in first and "crisis_eva" in first and first["crisis_eva"][0] < first["water_fail"][0]:
                check("no splint on the line", first["water_fail"][2] != first["crisis_eva"][1])
        self.assertEqual(bad, [])
        self.assertGreater(seen.get("ending A proposed the hello", 0), 250)
        self.assertGreater(seen.get("long orbit B argued to wait", 0), 20)

    def test_fair_play_and_endings_over_300_seasons(self):
        # Every season must deliver the core clue set before the reveal, and every
        # ending must be reachable at a real rate (>= 5%). Same seasons and keys as
        # `sim/season.py --seasons 300`, which also fails on an unfair season.
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season, fair_play
        _, text, _ = lvc.build(CONTENT)
        self.assertGreaterEqual(len(text["core"]), 6)
        self.assertTrue(text["reveal"])
        # The climax schedule (STORY_BIBLE.md): exactly one mystery card on each of
        # days 35-40, a window card on day 41, at least two story cards on every
        # day 34-42, an epilogue line for every astronaut, a coda line, and each
        # personal thread's late beat (c_*) for its owner.
        from render import Renderer
        cat = {i: c["cat"] for i, c in enumerate(lvc.build(CONTENT)[2].cards)}
        ids = [c["id"] for c in text["cards"]]
        window = {ids.index("a_window_hail"), ids.index("a_window_quiet")}
        opens = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN)
        thread_beats = {ids.index(x) for x in ("c_letter", "c_dose", "c_list", "c_song", "c_theory", "c_hail")}
        entry = {ids.index(x) for x in ("e_entry_hold", "e_entry_hold_q", "e_entry_wait", "e_entry_clear")}
        half = {ids.index(x) for x in ("signal_reply", "signal_echo")}
        whole = {ids.index(x) for x in ("m_key", "r_dark", "r_dark_a")}
        ends = {}
        for i in range(300):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            st = reference_season(Pack(self.p.data), seed=1000 + i, voyage_key=key)[0]
            self.assertEqual(fair_play(st, text), [], "season %d" % i)
            ends[st.ending] = ends.get(st.ending, 0) + 1
            out = st.story
            myst, days = {}, {}
            for k in range(0, len(out), 8):
                if out[k + 1] in opens:
                    days[out[k]] = days.get(out[k], 0) + 1
                    if cat[out[k + 2]] == "mystery":
                        myst[out[k]] = myst.get(out[k], 0) + 1
            for d in range(35, 41):
                self.assertEqual(myst.get(d, 0), 1, "season %d day %d" % (i, d))
            for d in range(34, 43):
                self.assertGreaterEqual(days.get(d, 0), 2, "season %d day %d" % (i, d))
            fired = {out[k + 2] for k in range(0, len(out), 8) if out[k + 1] == O.O_EVENT}
            self.assertTrue(thread_beats <= fired, "season %d" % i)
            self.assertTrue(any(out[k + 1] == O.O_EVENT and out[k + 2] in window and out[k] == 41
                                for k in range(0, len(out), 8)), "season %d" % i)
            self.assertEqual(len(Renderer(text).epilogue(out)), N, "season %d" % i)
            self.assertEqual(len(fired & entry), 1, "entry scene, season %d" % i)
            # The signal arrives in order: half a frame first, then the whole frame.
            hd = [out[k] for k in range(0, len(out), 8) if out[k + 1] == O.O_EVENT and out[k + 2] in half]
            wd = [out[k] for k in range(0, len(out), 8) if out[k + 1] == O.O_EVENT and out[k + 2] in whole]
            self.assertEqual(len(hd), 1, "half frame, season %d" % i)
            self.assertTrue(1 <= len(wd) <= 2, "whole frame, season %d" % i)
            self.assertLess(hd[0], min(wd), "half frame before whole frame, season %d" % i)
            self.assertIn(ids.index("m_key"), fired, "key decode, season %d" % i)
            self.assertIsNotNone(Renderer(text).coda(out), "season %d" % i)
            # Entry prep: no window crossings out after day 32 (a late rescue can still
            # carry someone across until 38), nobody crosses at all on
            # days 40-42, and every astronaut still flying is home for entry.
            for k in range(0, len(out), 8):
                if out[k + 1] == O.O_MOVE:
                    self.assertLess(out[k], 40, "crossing on day %d, season %d" % (out[k], i))
                    if out[k] > 38:
                        self.assertEqual(out[k + 3], out[k + 5], "outbound on day %d, season %d" % (out[k], i))
            for c in range(N):
                if st.cond[c] != O.COND_HOME:
                    self.assertEqual(st.loc[c], c, "astronaut %d away at entry, season %d" % (c, i))
        n_end = sum(1 for c in text["cards"] if c["id"].startswith("end_"))
        self.assertEqual(len(ends), n_end)
        self.assertGreaterEqual(min(ends.values()), 15, ends)

    def test_climax_is_clear(self):
        # No cliffhangers after day 36, nothing resolves after 37, and the last
        # days belong to arrival, the reveal and the endings.
        import glob, re
        for f in glob.glob(os.path.join(CONTENT, "cards", "*.lv")):
            with open(f) as fh:
                src = fh.read()
            for b in re.split(r"(?m)^(?=card )", src):
                m = re.match(r"card (\w+)", b)
                d = re.search(r"(?m)^days (\d+) (\d+)$", b)
                if not m or not d:
                    continue
                hi, cat = int(d.group(2)), re.search(r"(?m)^cat (\w+)", b).group(1)
                if re.search(r"(?m)^hook$", b):
                    self.assertLessEqual(hi, 36, m.group(1))
                elif re.search(r"(?m)^when fired h_", b):
                    self.assertLessEqual(hi, 37, m.group(1))
                elif cat not in ("arrival", "ending") and not re.search(r"(?m)^reveal$", b):
                    self.assertLessEqual(hi, 39, m.group(1))

class TestRound2Language(unittest.TestCase):
    """`!is`, `clue core GROUP` and `title`."""

    def test_negated_is_excludes_the_named_crew(self):
        src = ("card pick\ntype event\ndue\nonce\ndays 1 1\nroles A\ntext {A} {A:is} picked.\ndo who own A\n\n"
               "card other\ntype event\ndue\nonce\ndays 2 2\nroles A\nwhen !is A own\ntext {A} {A:is} not.\n")
        pack, text, ctx = lvc.build(mini_content(src))
        self.assertEqual(ctx.errors, [])
        _, days = season(Pack(pack))
        story = b"".join(days)
        ids = [c["id"] for c in text["cards"]]
        a = [e[3] for e in events(story, ids.index("pick"))]
        b = [e[3] for e in events(story, ids.index("other"))]
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertNotEqual(a[0], b[0])

    def test_ending_names_crew_through_is(self):
        # The ending entry carries two roles, read straight from the `is` vars: no
        # casting, so one astronaut may fill both, and the choice of ending is unchanged.
        src = ("card pick\ntype event\ndue\nonce\ndays 1 1\nroles A\ntext {A} {A:is} picked.\ndo who own A\n\n"
               "card other\ntype event\ndue\nonce\ndays 2 2\nroles A\nwhen !is A own\ntext {A} {A:is} not.\n"
               "do who two A\n\n"
               "card fin\ntype ending\nroles A B\nwhen fired other\nwhen is A own\nwhen is B two\n"
               "text {A} and {B} land.\n\n"
               "card fin2\ntype ending\nroles A B\nwhen is A own\nwhen is B own\ntext {A} {A:lands}; {B} {B:waves}.\n")
        pack, text, ctx = lvc.build(mini_content(src))
        self.assertEqual(ctx.errors, [])
        from sim.render import Renderer
        ids = [c["id"] for c in text["cards"]]
        st, days = season(Pack(pack))
        story = b"".join(days)
        a = [e[3] for e in events(story, ids.index("pick"))][0]
        b = [e[3] for e in events(story, ids.index("other"))][0]
        end = [story[i:i + 8] for i in range(0, len(story), 8) if story[i + 1] == O.O_END]
        self.assertEqual(len(end), 1)
        self.assertEqual((end[0][2], end[0][3], end[0][4]), (ids.index("fin"), a, b))
        line = Renderer(text).entry(end[0])
        self.assertIn("%s and %s land." % (text["crew"][a], text["crew"][b]), line)
        # Same var twice: one person in both roles, not a failed cast.
        src2 = src.replace("when fired other\n", "when fired nothing_here\n").replace(
            "card other\n", "card nothing_here\ntype event\ndays 40 40\nroles A\nwhen !fired pick\ntext {A}.\n\ncard other\n")
        pack, text, ctx = lvc.build(mini_content(src2))
        self.assertEqual(ctx.errors, [])
        st, days = season(Pack(pack))
        story = b"".join(days)
        end = [story[i:i + 8] for i in range(0, len(story), 8) if story[i + 1] == O.O_END][0]
        self.assertEqual(text["cards"][end[2]]["id"], "fin2")
        self.assertEqual(end[3], end[4])
        self.assertNotEqual(end[3], O.NONE)

    def test_ending_role_tests_are_limited(self):
        src = ("card pick\ntype event\ndue\nonce\ndays 1 1\nroles A\ntext {A}.\ndo who own A\n\n"
               "card fin\ntype ending\nroles A B\nwhen same A B\ntext {A} and {B}.\n")
        _, _, ctx = lvc.build(mini_content(src))
        self.assertTrue(any("only with `is`" in e for e in ctx.errors), ctx.errors)

    def test_core_groups_and_titles(self):
        src = ("card c1\ntype event\nclue core g\ndays 2 3\nroles A\ntext {A} {A:sees} one.\n\n"
               "card c2\ntype event\nclue core g\ndays 2 3\nroles A\ntext {A} {A:sees} two.\n\n"
               "card c3\ntype event\nclue core\ndays 2 3\nroles A\ntext {A} {A:sees} three.\n\n"
               "card fin\ntype ending\ntitle A Proper Title\nwhen fired c3\ntext Fin.\n")
        _, text, ctx = lvc.build(mini_content(src))
        self.assertEqual(ctx.errors, [])
        ids = [c["id"] for c in text["cards"]]
        self.assertEqual(text["core"], [[ids.index("c1"), ids.index("c2")], [ids.index("c3")]])
        self.assertEqual(text["cards"][ids.index("fin")]["ti"], "A Proper Title")

    def test_crossings_only_in_transfer_windows(self):
        # Each astronaut has a home ship; crossings happen only on transfer-window days,
        # and only to a crewmate who is at home, so a ship holds at most 2.
        src = "card idle\ntype beat\ndays 1 42\nweight 5\nroles A\ntext {A} {A:reads}.\n"
        pack, _, _ = lvc.build(mini_content(src))
        moved = 0
        for seed in range(30):
            p = Pack(pack)
            p.voyage_key = bytes([seed, 7]) + b"cross!"
            st = State(p)
            eng = Engine(p, st, ChoiceLog(FK))
            for _ in range(42):
                eng.tick()
                for i in range(0, len(st.out), 8):
                    if st.out[i + 1] == O.O_MOVE:
                        d = st.out[i]
                        self.assertTrue(d >= O.TRANSFER_FROM and (d - O.TRANSFER_FROM) % O.TRANSFER_EVERY == 0, d)
                        moved += 1
                held = [0] * N
                for c in range(N):
                    held[st.loc[c]] += 1
                self.assertLessEqual(max(held), 2)
        self.assertGreater(moved, 0)

    def test_only_some_conditions_negate(self):
        src = "card bad\ntype event\ndays 2 3\nroles A\nwhen !var x >= 1\ntext {A} {A:waits}.\n"
        _, _, ctx = lvc.build(mini_content(src))
        self.assertTrue(any("negated" in e for e in ctx.errors), ctx.errors)


class TestCli(unittest.TestCase):
    """lvc's command line: --help must not compile, and story flags stay off stdout."""

    def run_lvc(self, *args):
        import subprocess
        return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "lvc.py")] + list(args),
                              capture_output=True, text=True)

    def test_help_does_not_compile(self):
        out = tempfile.mkdtemp(prefix="lvc-out-")
        for flag in ("--help", "-h"):
            r = self.run_lvc(flag, "--out", out)
            self.assertEqual(r.returncode, 0)
            self.assertIn("Usage:", r.stdout)
            self.assertNotIn("ok:", r.stdout)
            self.assertNotIn("warning:", r.stdout + r.stderr)
            self.assertEqual(r.stderr, "")
        self.assertEqual(os.listdir(out), [])

    def test_epilogue_fallback_fills_every_astronaut(self):
        # With the final state, the epilogue gives every astronaut a line even in seasons
        # whose story log leaves someone out (other seeds, no voyage key).
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        from render import Renderer
        p, text, _ = lvc.build(CONTENT)
        for i in range(60):
            st = reference_season(Pack(p), seed=7 + 13 * i)[0]
            lines = Renderer(text).epilogue(st.story, st)
            self.assertEqual(sorted(lines), list(range(N)), "seed %d" % (7 + 13 * i))
            self.assertTrue(all(lines.values()))
        # Even a log with no story lines at all yields one per astronaut.
        lines = Renderer(text).epilogue(b"", st)
        self.assertEqual(sorted(lines), list(range(N)))

    def test_flag_names_only_with_verbose(self):
        out = tempfile.mkdtemp(prefix="lvc-out-")
        r = self.run_lvc("--check", "--out", out)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("never checked", r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok:"), r.stdout)


class TestHabitSlot(unittest.TestCase):
    """roster.lv `habit "..."` plus `each crew` cards: per-astronaut text, compiled in."""

    SRC = "card hab\ntype beat\neach crew\nonce\nweight 50\nroles A\ntext On shift: {habit}\n"

    def roster(self, habits):
        names = ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian", "Marco"]
        return "\n".join('crew %s ship Ship 0%d%s' % (n, i + 1, (' habit "%s"' % habits[i]) if habits[i] else "")
                         for i, n in enumerate(names))

    def test_clones_bind_only_their_astronaut(self):
        hs = ["{A} {A:hums}.", None, "{A} {A:whistles}.", None, None, None, None, None]
        pack, text, ctx = lvc.build(mini_content(self.SRC, self.roster(hs)))
        self.assertEqual(ctx.errors, [])
        ids = [c["id"] for c in text["cards"]]
        self.assertEqual(ids[:N], ["hab_%d" % i for i in range(1, N + 1)])
        self.assertEqual(text["cards"][0]["t"], "On shift: {A} {A:hums}.")
        self.assertEqual(text["cards"][1]["t"], "On shift: " + lvc.HABIT_DEFAULT)
        self.assertNotIn("{habit}", repr(text))
        seen = {}
        for seed in range(40):
            p = Pack(pack)
            p.voyage_key = bytes([seed, 3]) + b"habits"
            _, days = season(p)
            for out in days:
                for k in range(N):
                    for e in events(out, k):
                        seen.setdefault(k, set()).add(e[3])
        for k, who in seen.items():
            self.assertEqual(who, {k})

    def test_bad_habit_is_an_error(self):
        hs = ["hums a lot", None, None, None, None, None, None, None]
        _, _, ctx = lvc.build(mini_content(self.SRC, self.roster(hs)))
        self.assertTrue(any("habit" in e for e in ctx.errors), ctx.errors)

    def test_habit_slot_outside_each_crew_is_an_error(self):
        _, _, ctx = lvc.build(mini_content(self.SRC.replace("each crew\n", "")))
        self.assertTrue(any("habit" in e for e in ctx.errors), ctx.errors)

    def test_real_roster_parses_habits(self):
        fleet = lvc.parse_fleet(os.path.join(CONTENT, "fleet.lv"), os.path.join(CONTENT, "roster.lv"))
        self.assertEqual(len(fleet["crew"]), N)
        for cr in fleet["crew"]:
            self.assertIn("{A}", cr["habit"])
            self.assertTrue(cr["ship"].startswith("Ship 0"), cr["ship"])


class TestRound19(unittest.TestCase):
    """Round 19: reveal readability, continuity fixes, page headings, crew quirks."""

    @classmethod
    def setUpClass(cls):
        cls.pack, cls.text, cls.ctx = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] for c in cls.text["cards"]}
        cls.o = {c["id"]: [o[1] for o in c.get("o", [])] for c in cls.text["cards"]}
        cls.cards = {c["id"]: c for c in cls.ctx.cards}

    @classmethod
    def runs(cls):
        if not hasattr(cls, "_runs"):
            sys.path.insert(0, os.path.join(ROOT, "sim"))
            from season import reference_season
            cls._runs = []
            for i in range(300):
                key = bytes([(i >> 8) & 255, i & 255]) + b"season"
                cls._runs.append(reference_season(Pack(cls.pack), seed=1000 + i, voyage_key=key)[0].story)
        return cls._runs

    def test_reveal_reads_at_a_glance(self):
        # Day 40: the patch carries the history and four short card lines; the meaning
        # lands in a_report as one plain sentence with no all-caps telemetry.
        rep = self.t["a_report"]
        self.assertIn('"It heard every hail. Every one arrived after it had stopped waiting."', rep)
        self.assertIsNone(re.search(r"\b[A-Z]{2,}(?:[ ,:·]+[A-Z0-9]{2,}){2,}", rep), rep)
        self.assertIn("low-res pass", self.t["a_patch"])
        self.assertIn("low-res pass", self.t["l_manifest"])
        ids = [c["id"] for c in self.text["cards"]]
        self.assertLess(ids.index("a_patch"), ids.index("a_report"))

    def test_day_41_says_why_a_hello_is_or_isnt_safe(self):
        self.assertIn("One tick awake is all a cold battery can spare", self.t["a_window_hail"])
        self.assertIn("gets no second try", self.t["a_window_quiet"])

    def test_hopper_stays_alive_on_day_37(self):
        for cid in ("m_checked", "m_checked_g"):
            self.assertIn("Nearest is the hopper", self.t[cid], cid)
            # Round 25: no neon dismissal of Cargo 2; l_manifest keeps the fair "scar" line.
            self.assertIn("crater rims and old landing ellipses", self.t[cid], cid)
            self.assertNotIn("Cargo 2", self.t[cid], cid)

    def test_who_plant_and_silent_lighthouse_beat(self):
        self.assertIn("the next frame brings a new one", self.t["m_key"])
        self.assertIn('"24 h 37 m"', self.t["c_theory"])
        strs = list(self.t.values()) + [x for v in self.o.values() for x in v]
        self.assertEqual([x for x in strs if re.search(r"Mars time|strobe", x, re.I)], [])

    def test_continuity_fixes(self):
        self.assertNotRegex(self.t["p_garden_none"], r"(?i)ration")
        story = dict(self.text["epi"]["story"]) if isinstance(self.text["epi"]["story"][0][0], str) else None
        lines = [l for _, l in self.text["epi"]["story"]]
        self.assertEqual([l for l in lines if re.search(r"aloud,? at Mars", l)], [])
        self.assertIn("Every few weeks", self.t["l_transfer"])
        self.assertIn("A visit bends the rule", self.t["l_transfer"])
        self.assertIn("the last tanker quietly put back", self.t["a_recall_photo"])
        self.assertNotIn("{B}'s birthday", self.t["p_birthday"])
        self.assertEqual(tuple(self.cards["dec_halfway"]["days"]), (24, 24))
        self.assertLessEqual(self.cards["l_reboot"]["days"][1], 5)
        self.assertIn("millisieverts", self.t["storm_dose"])

    def test_engineering_fixes(self):
        # Fault detection does its job and still loses: it isolates the wrong jet.
        self.assertIn("Fault detection flagged", self.t["r_thruster"])
        self.assertIn("isolated a healthy one", self.t["r_thruster"])
        for cid in ("r_dark", "r_dark_a"):
            self.assertIn("still feeding the watchdog", self.t[cid], cid)
            self.assertIn("pulled power by hand", self.t[cid], cid)

    def test_endings_round_19(self):
        self.assertIn("and {A:answers} anyway", self.t["end_close"])
        self.assertIn("spare power in hand", self.t["end_close"])
        self.assertNotIn("argued to wait", self.t["end_long_orbit"])
        self.assertIn("All eight. The ninth gave us its night.", self.t["end_friend"])
        for cid in ("end_through", "a_descent_hold", "a_descent_hold_q"):
            self.assertIn("two antennas", self.t[cid], cid)
            self.assertIn("rim", self.t[cid], cid)
        for cid in ("a_descent_hold", "a_descent_hold_q"):
            self.assertIn("never a weather alternate", self.t[cid], cid)

    def test_grim_blades_are_grounded(self):
        self.assertIn('"contingency, crew, 1"', self.t["g_count"])
        self.assertIn("next-of-kin forms", self.t["storm_shelter2"])
        self.assertIn("COMMIT", self.t["l_departure"])

    def test_page_heading(self):
        from sim.render import page_heading
        self.assertEqual(page_heading(1), "LOG PAGE 01 · DAY 1")
        self.assertEqual(page_heading(6), "LOG PAGE 06 · DAY 6")
        self.assertEqual(page_heading(7), "LOG PAGE 07 · DAYS 7–11")
        self.assertEqual(page_heading(8), "LOG PAGE 08 · DAYS 12–16")
        self.assertEqual(page_heading(24), "LOG PAGE 24 · DAYS 92–96")

    def test_pages_are_not_crowded(self):
        # Round 19: 57% of seasons had a page of 8+ reader lines; keep it under 45%.
        from sim.render import Renderer
        import collections
        crowded = 0
        for out in self.runs():
            c = collections.Counter(day for day, _ in Renderer(self.text).reader(out))
            crowded += any(v >= 8 for v in c.values())
        self.assertLess(crowded, 135, crowded)

    def test_quirk_lines_render_only_for_their_owner(self):
        # roster.lv habits -> `each habit N` clones: quirk_N_K binds role A to crew K-1.
        ids = [c["id"] for c in self.text["cards"]]
        quirk = {i: int(cid.rsplit("_", 1)[1]) - 1 for i, cid in enumerate(ids) if cid.startswith("quirk_")}
        n_crew = len(self.text["crew"])
        self.assertEqual(len(quirk), sum(len(c["habits"]) for c in lvc.parse_fleet(os.path.join(CONTENT, "fleet.lv"), os.path.join(CONTENT, "roster.lv"))["crew"] if c["habits"]))
        for i, k in quirk.items():
            self.assertNotIn("{habit}", self.text["cards"][i]["t"])
        touches = [0] * n_crew
        for out in self.runs():
            for k in range(0, len(out), 8):
                if out[k + 1] == O.O_EVENT and out[k + 2] in quirk:
                    self.assertEqual(out[k + 3], quirk[out[k + 2]], ids[out[k + 2]])
                    touches[out[k + 3]] += 1
        for c, n in enumerate(touches):
            self.assertTrue(2.0 <= n / 300 <= 4.0, (self.text["crew"][c], n / 300))

    def test_each_habit_skips_placeholder_and_missing(self):
        src = "card q\ntype beat\neach habit 2\nonce\nweight 50\nroles A\ntext {habit}\n"
        names = ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian", "Marco"]
        hs = {"Kim": ' habit "{A} {A:hums}." habit "{A} {A:whistles}."',
              "Jai": ' habit "%s" habit "%s"' % (lvc.HABIT_DEFAULT, lvc.HABIT_DEFAULT),
              "Diego": ' habit "{A} {A:draws}."'}
        roster = "\n".join("crew %s ship Ship 0%d%s" % (n, i + 1, hs.get(n, "")) for i, n in enumerate(names))
        _, text, ctx = lvc.build(mini_content(src, roster))
        self.assertEqual(ctx.errors, [])
        qs = [c for c in text["cards"] if c["id"].startswith("q_")]
        self.assertEqual([(c["id"], c["t"]) for c in qs], [("q_3", "{A} {A:whistles}.")])


class TestEightShips(unittest.TestCase):
    """The fleet is eight ships: roster, engine sizes, record fields and story counts agree."""

    @classmethod
    def setUpClass(cls):
        cls.p, cls.text, cls.ctx = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] for c in cls.text["cards"]}

    def test_sizes_agree(self):
        from lv import codes as K, record as R
        self.assertEqual(N, 8)
        self.assertEqual(lvc.N_CREW, N)
        self.assertEqual(K.N, N)
        self.assertEqual(Pack(self.p).ncrew, N)
        self.assertEqual(len(self.text["crew"]), N)
        # The author field is 4 bits; the admin author must sit outside the crew range.
        self.assertTrue(N <= R.ADMIN_SHIP < 16)
        self.assertEqual(len(ChoiceLog(FK).seq_vector()), N)
        st = State(Pack(self.p))
        self.assertEqual(len(st.bonds), N * N)
        self.assertEqual(st.loc, bytearray(range(N)))
        # dil_seen keeps one bit per crew in a byte: the eighth crew is bit 7.
        st.dil_seen[0] |= 1 << (N - 1)
        self.assertEqual(State.load(st.dump()).dil_seen[0], 128)

    def test_log_shards_merge_like_one_table(self):
        # chlog shards records by 8-day blocks; order, length, seq vector and the
        # admin exclusion must read as if it were one table, for all eight ships.
        import random
        from lv import record as R
        recs = []
        for day in range(0, 43):
            for ship in list(range(N)) + [R.ADMIN_SHIP]:
                recs.append(R.encode(FK, R.VOTE, ship, 1, 100 + day, day, 3, ship % 2))
        a, b = ChoiceLog(FK), ChoiceLog(FK)
        for r in recs:
            a.merge(r)
        rnd = random.Random(5)
        rnd.shuffle(recs)
        for r in recs:
            b.merge(r)
        self.assertEqual(len(a), len(recs))
        self.assertEqual(a.all_records(), b.all_records())
        self.assertEqual(a.digest(), b.digest())
        keys = [R.key(r) for r in a.all_records()]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(a.seq_vector(), [142] * N)
        self.assertEqual([s for s, _ in a.answers(R.VOTE, 3, 10, 20)], list(range(N)))

    def test_roster_order_and_marco(self):
        crew = self.text["crew"]
        self.assertEqual(crew[:7], ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian"])
        self.assertEqual(crew[7], "Marco")
        fleet = lvc.parse_fleet(os.path.join(CONTENT, "fleet.lv"), os.path.join(CONTENT, "roster.lv"))
        marco = fleet["crew"][7]
        self.assertEqual(marco["ship"], "Ship 08")
        self.assertEqual(len(marco["habits"]), 4)

    def test_crew_mask_for_ship_eight(self):
        # C_CREW is a byte mask: crew index 7 is 0x80, and the clone binds only Marco.
        for k in (1, 2, 3):
            cid = "quirk_%d_8" % k
            self.assertIn(cid, self.t)
            self.assertNotIn("{habit}", self.t[cid])
        src = "card q\ntype beat\neach crew\nonce\nweight 50\nroles A\ntext {habit}\n"
        _, text, ctx = lvc.build(mini_content(src))
        self.assertEqual(ctx.errors, [])
        self.assertEqual(len([c for c in text["cards"] if c["id"].startswith("q_")]), N)

    def test_story_counts_are_eight(self):
        blob = "\n".join(self.t.values()) + json.dumps(self.text)
        for bad in ("past six ships", "Six ships", "All seven", "all seven", "the eighth plugged",
                    "The eighth", "other six", "six displays", "Seven pilots", "seven blind"):
            self.assertNotIn(bad, blob, bad)
        for cid in ("end_lights", "end_long_orbit", "end_patience", "end_friend", "end_close"):
            self.assertIn("All eight", self.t[cid], cid)
            self.assertIn("ninth", self.t[cid], cid)
        self.assertIn("Eight down, seven to fly", self.t["end_through"])
        self.assertIn("Eight ships light their engines", self.t["l_departure"])


class TestRound20(unittest.TestCase):
    """Round 20: engineer corrections, loose threads closed, endings, habit lines, tie wording."""

    @classmethod
    def setUpClass(cls):
        cls.p, cls.text, cls.ctx = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] for c in cls.text["cards"]}
        cls.o = {c["id"]: [o[1] for o in c.get("o", [])] for c in cls.text["cards"]}
        cls.blob = json.dumps(cls.text, ensure_ascii=False)

    def test_engineer_corrections(self):
        self.assertIn("Every crew spent the night", self.t["r_flare"])
        self.assertNotIn("Seven crews", self.blob)
        self.assertIn("already smaller than the Moon looks from home", self.t["beat_watch"])
        self.assertIn("half a minute a question", self.o["dil_dose"][0])
        self.assertIn("five days out", self.t["a_descent_clear"])
        self.assertIn("a shade under 10.96 seconds", self.t["m_carrier"])
        self.assertIn("A two-hour orbit would show; a week of residuals is too sparse", self.t["m_alias"])
        self.assertIn("past a hundred millisieverts", self.t["storm_dose"])
        self.assertIn("five days of HOLD", self.t["end_lights"])
        # Dry seed survives freezing; wet-packed germination trays do not.
        self.assertIn("germination trays", self.t["end_long_orbit"])
        self.assertNotIn("seed stock", self.t["end_long_orbit"])
        self.assertIn("{B} {B:calls} the roll, ship by ship", self.t["end_long_orbit"])

    def test_loose_threads_closed(self):
        # The hopper's "intermittent beacon" was the knock, booked to the wrong name.
        self.assertIn("booked to the hopper's beacon", self.t["a_report"])
        self.assertIn("Nothing in Mars orbit speaks the old channel", self.t["a_report"])
        # The relay's last-week pulse was Cargo 2 in cruise; only Cargo 2 has a landing ellipse.
        self.assertIn("the relay's \"spin\" was it", self.t["m_reveal"])
        self.assertIn("landing ellipse", self.t["m_reveal"])
        self.assertNotIn("relay's misses", self.t["m_reveal"])
        self.assertIn("only for the hopper's beacon", self.t["m_carrier"])
        # p_dream's margin note pays off where the clicks are heard.
        self.assertIn("rain, car roof", self.t["p_dream"])
        self.assertIn("log margin", self.t["m_listen"])
        # The flashing pixel is the patch's lamp.
        self.assertIn("a lamp for eyes, a knock for radios", self.t["a_patch"])
        self.assertNotIn("TIMEOUT", self.t["a_patch"])

    def test_wording_bugs(self):
        self.assertNotIn("flight director takes it", self.blob)
        for opt in self.o["dec_arrival"]:
            self.assertNotIn("flight director", opt)
        self.assertIn("crystals", self.t["l_crystals"])
        self.assertIn("cook overnight", self.t["l_crystals"])
        self.assertIn("since the first scrap", self.t["signal_echo"])
        self.assertNotIn("It's been a long week", self.t["stash_found"])

    def test_tie_wording_varies(self):
        tie = self.text["sys"]["dec_tie"]
        self.assertIsInstance(tie, list)
        self.assertGreaterEqual(len(tie), 4)
        self.assertEqual(len(set(tie)), len(tie))
        for x in tie:
            self.assertIn("{n} ballots", x)
            self.assertIn("{opt}", x)
            self.assertNotIn("votes", x)
        self.assertNotIn("Help is on the way", self.text["sys"]["res_close"])

    def test_tie_wording_steps_through_the_pool(self):
        # Each tie close takes the next wording, so a season repeats one only after
        # using them all; the reader and the phone (render.js) count the same way.
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        from render import Renderer
        pool = self.text["sys"]["dec_tie"]
        heads = [x.split("{n}")[0] + "|" + x.split("{n}")[1].split("{opt}")[0] for x in pool]
        seen_tie = 0
        for i in range(40):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            st = reference_season(Pack(self.p), seed=1000 + i, voyage_key=key)[0]
            used = []
            for _, s in Renderer(self.text).lines(st.story):
                for j, h in enumerate(heads):
                    a, b = h.split("|")
                    if s.startswith(a) and b in s:
                        used.append(j)
            seen_tie += bool(used)
            self.assertEqual(used, [k % len(pool) for k in range(len(used))], "season %d" % i)
        self.assertGreater(seen_tie, 20)

    def test_habit_lines_round_20(self):
        fleet = lvc.parse_fleet(os.path.join(CONTENT, "fleet.lv"), os.path.join(CONTENT, "roster.lv"))
        habits = [h for cr in fleet["crew"] for h in cr["habits"]]
        joined = " ".join(habits)
        for banned in ("Every data drop", "Last mail before entry", "Last video before entry",
                       "no strays", "retunes the pump", "names things", "measures twice",
                       "like a breach", "no cutscenes"):
            self.assertNotIn(banned, joined, banned)
        # Habit lines never touch life-support settings for a joke.
        self.assertIn("{A:writes} it a bass line", joined)
        # Kittens stay at home: any habit line about them arrives as mail.
        for h in habits:
            if "kitten" in h or "litter" in h:
                self.assertTrue("mail" in h or "word reaches" in h, h)

    def test_endings_round_20(self):
        self.assertIn("It never could stand being ignored.", self.t["end_lights"])
        self.assertNotIn("sulks", self.t["end_lights"])
        self.assertTrue(self.t["end_through"].startswith("Dust to the windows."))
        self.assertNotIn("wanted to answer all along", self.t["end_through"])
        self.assertIn("enough to get there, not back", self.t["end_friend"])
        self.assertIn("forklift photo", self.t["end_friend"])
        self.assertIn("{B:puts} a glove flat on the cold hull", self.t["end_close"])
        self.assertIn("By then it has nothing left to hear it with.", self.t["end_close"])

    def test_fold_pool_has_people(self):
        pool = self.text["sys"]["fold_pool"]
        self.assertFalse([x for x in pool if "spare fuses" in x])
        self.assertTrue([x for x in pool if "bedtime stories" in x])



class TestRound21(unittest.TestCase):
    """Round 21: galley-screen owner, light-time wording, occupancy, endings, plants, voice."""

    @classmethod
    def setUpClass(cls):
        _, cls.text, _ = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] + " " + " ".join(o[1] for o in c.get("o", [])) for c in cls.text["cards"]}

    def test_galley_screen_has_one_owner(self):
        with open(os.path.join(CONTENT, "cards", "55_voyage.lv")) as f:
            src = f.read()
        block = src[src.index("card l_handshake"):]
        block = block[:block.index("\ncard ", 1)]
        self.assertIn("when is A abort_who", block)
        self.assertIn("by pure coincidence, one galley screen boots to ONLINE", self.t["a_window_hail"])

    def test_light_time_says_what_it_measures(self):
        self.assertIn("a day this week", self.t["m_alias"])
        self.assertIn("one-way light time from Mars, thirty seconds now", self.t["m_overlay"])

    def test_no_one_name_on_many_ships(self):
        blob = json.dumps(self.text)
        self.assertNotIn("walked hulls", blob)
        self.assertIn("RECLAIMED. DRINK SPARINGLY.", blob)
        self.assertIn("over the link", self.t["p_movie"])
        self.assertIn("over the link", self.t["beat_coffee"])

    def test_endings_round_21(self):
        self.assertIn("up the old channel", self.t["end_long_orbit"])
        self.assertIn("{B} {B:calls} the roll, ship by ship", self.t["end_long_orbit"])
        self.assertIn("enough to get there, not back", self.t["end_friend"])
        self.assertIn("behind a door on ship power", self.t["end_close"])
        self.assertIn("the folded ship's last battery", self.t["end_through"])
        self.assertIn("panels, a mast, a winch", self.t["end_through"])
        blob = json.dumps(self.text)
        for gone in ("clearing its throat", "Slow, not stingy", "In time for the bit", "Then {A}, hoarse"):
            self.assertNotIn(gone, blob, gone)

    def test_tick_planted_before_the_patch(self):
        self.assertIn("INSIDE ONE TICK", self.t["sharpie2"])
        self.assertIn("beacon, dead since the week it tipped", self.t["a_report"])

    def test_cat_lines_are_separate(self):
        joined = " ".join(self.text["habits"]) if "habits" in self.text else json.dumps(self.text)
        self.assertNotIn("cat-proofs", joined)
        self.assertIn("Copy. Done. Next.", joined)

class TestRound22(unittest.TestCase):
    """Final pass: entry pins, owner bindings, new quirks from the crew."""

    @classmethod
    def setUpClass(cls):
        _, cls.text, cls.pack = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] + " " + " ".join(o[1] for o in c.get("o", [])) for c in cls.text["cards"]}
        with open(os.path.join(CONTENT, "roster.lv")) as f:
            cls.roster = {l.split()[1]: l for l in f if l.startswith("crew ")}

    def test_no_habit_pins_itself_to_entry(self):
        for cid, t in self.t.items():
            if cid.startswith("quirk_"):
                for bad in ("before entry", "entry eve", "last corridor burn"):
                    self.assertNotIn(bad, t, cid)

    def test_new_quirks_are_on_their_owners(self):
        want = {"Kim": ("Mango", "Dirt"), "Jai": ("fantasy football", "JetBlue", "wedding"),
                "Diego": ("three cats", "a stranger"), "Dorian": ("Wesley", "Uncrustables"),
                "Jacques": ("circuit board", "career", "chihuahua", "two cats"), "Michelle": ("Disney", "Tesla"),
                "Marco": ("Elgin", "BMW", "Mexico", "cologne")}
        for name, words in want.items():
            for w in words:
                self.assertIn(w, self.roster[name], (name, w))
                for other, line in self.roster.items():
                    if other != name and w not in ("two cats", "three cats", "a stranger", "wedding"):
                        self.assertNotIn(w, line, (other, w))
        self.assertNotIn("two cats", self.roster["Diego"])
        self.assertNotIn("both fed", self.roster["Diego"])

    def test_quirk_4_clones_only_for_real_fourth_habits(self):
        ids = {c["id"] for c in self.text["cards"]}
        self.assertNotIn("quirk_4_1", ids)
        for k in range(2, 9):
            self.assertIn("quirk_4_%d" % k, ids)

    def test_owner_bindings(self):
        src = "".join(open(os.path.join(CONTENT, "cards", f)).read() for f in ("55_voyage.lv",))
        block = src[src.index("card g_packer"):]
        block = block[:block.index("\ncard ", 1)]
        self.assertIn("when is A ow_theory", block)
        self.assertIn("Pump it on entry morning", self.t["c_dose"])

    def test_final_ending_wording(self):
        self.assertIn("every floodlight burning the charge", self.t["end_lights"])
        self.assertIn("By morning the trays are frozen", self.t["end_long_orbit"])
        self.assertIn("rover's spare battery went to heaters", self.t["end_close"])


class TestRound24(unittest.TestCase):
    """Pass 1: crew voices, shipped text without ids, grim beats, hooks, physics."""

    @classmethod
    def setUpClass(cls):
        _, cls.text, cls.pack = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] + " " + " ".join(o[1] for o in c.get("o", [])) for c in cls.text["cards"]}

    def test_every_crewmate_has_a_distinct_voice(self):
        v = self.text["voice"]
        self.assertEqual(len(v), len(self.text["crew"]))
        self.assertEqual(len(set(v)), len(v))
        for line in v:
            self.assertTrue(0 < len(line) <= 40, line)

    def test_voice_slot_renders_the_owners_voice(self):
        from sim.render import Renderer
        r = Renderer(self.text)
        for c, name in enumerate(self.text["crew"]):
            self.assertEqual(r.fill("{A}: {Av}", A=c), name + ": " + self.text["voice"][c])
        self.assertEqual(r.fill("{Bv}", B=255), "Out.")
        used = [cid for cid, t in self.t.items() if "{Av}" in t or "{Bv}" in t]
        self.assertGreaterEqual(len(used), 6, used)

    def test_shipped_text_has_no_ids(self):
        import contextlib
        import io
        tmp = tempfile.mkdtemp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                lvc.main(["--out", tmp])
            with open(os.path.join(tmp, "text.json"), encoding="utf-8") as f:
                ship = json.load(f)
            with open(os.path.join(tmp, "text.dev.json"), encoding="utf-8") as f:
                dev = json.load(f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(all("id" not in c for c in ship["cards"]))
        self.assertEqual([c["id"] for c in dev["cards"]], [c["id"] for c in self.text["cards"]])
        self.assertEqual([c["t"] for c in ship["cards"]], [c["t"] for c in dev["cards"]])

    def test_grim_cards_and_hooks(self):
        for cid in ("g_ledger", "h_smoke", "h_tank", "r_smoke", "r_tank", "m_hopper"):
            self.assertIn(cid, self.t)
        self.assertIn("Tolerance has a column for crew", self.t["g_ledger"])
        self.assertIn("spare fans now reads zero", self.t["r_smoke"])
        self.assertIn("austerity", self.t["r_tank"])
        pool = self.text["sys"]["fold_pool"]
        self.assertEqual([x for x in pool if "spoon" in x], [])
        self.assertTrue(any("water ledger" in x for x in pool))

    def test_physics_round_24(self):
        self.assertNotIn("hundred million", " ".join(self.t.values()))
        with open(os.path.join(CONTENT, "roster.lv"), encoding="utf-8") as f:
            roster = f.read()
        self.assertNotIn("hundred million", roster)
        self.assertIn("tens of millions of kilometres", roster)
        self.assertNotIn("eight minutes late", roster)
        self.assertIn("already smaller than the Moon looks from home", self.t["beat_watch"])

    def test_endings_round_24(self):
        self.assertIn("Thirty-three: a click", self.t["end_patience"])
        self.assertIn("NO GO", self.t["end_through"])
        self.assertIn("{B} {B:makes} it eight", self.t["end_long_orbit"])

    def test_fold_lines_never_repeat_in_a_season(self):
        from sim.render import Renderer
        import collections
        pool = [p.split("}", 1)[1] for p in self.text["sys"]["fold_pool"]]
        if not hasattr(TestRound19, "pack"):
            TestRound19.setUpClass()
        for out in TestRound19.runs()[:60]:
            c = collections.Counter(p for _, s in Renderer(self.text).reader(out) for p in pool if s.endswith(p))
            self.assertTrue(all(n == 1 for n in c.values()), c)


class TestRound25(unittest.TestCase):
    """Pass 2: voice cap, quirk facts as moments, fairer suspects, galley screen."""

    @classmethod
    def setUpClass(cls):
        _, cls.text, cls.pack = lvc.build(CONTENT)
        cls.t = {c["id"]: c["t"] + " " + " ".join(o[1] for o in c.get("o", [])) for c in cls.text["cards"]}

    def test_voice_prints_on_at_most_two_cards_a_season(self):
        from sim.render import Renderer, VOICE_CARDS
        self.assertEqual(VOICE_CARDS, 2)
        if not hasattr(TestRound19, "pack"):
            TestRound19.setUpClass()
        crew, voices = self.text["crew"], self.text["voice"]
        self.assertEqual(voices[crew.index("Marco")], "Capacity: one.")
        for out in TestRound19.runs()[:100]:
            r = Renderer(self.text)
            list(r.reader(out))
            for c in r.vcards.values():
                self.assertLessEqual(len(c), 2)
        jac = voices[crew.index("Jacques")]
        for out in TestRound19.runs()[:100]:
            n = sum(s.count(jac) for _, s in Renderer(self.text).reader(out))
            self.assertLessEqual(n, 2)

    def test_no_hard_coded_sign_off(self):
        for cid in ("m_alias", "signal_reply", "c_hail"):
            self.assertIn("{Av}", self.t[cid], cid)
            self.assertNotIn("Out.", self.t[cid], cid)

    def test_requested_quirk_facts_stay(self):
        with open(os.path.join(CONTENT, "roster.lv"), encoding="utf-8") as f:
            roster = {l.split()[1]: l for l in f if l.startswith("crew ")}
        for name, words in {"Michelle": ("Disney", "Tesla"), "Jai": ("JetBlue", "wedding"),
                            "Marco": ("Elgin", "BMW", "Mexico")}.items():
            for w in words:
                self.assertIn(w, roster[name], (name, w))
        self.assertNotIn("Copy. Done. Next.", roster["Jacques"].split("habit", 1)[1])

    def test_suspects_stay_open(self):
        for cid in ("m_checked", "m_checked_g"):
            self.assertNotIn("scar in a photo", self.t[cid])
        self.assertIn("scar in a low-res pass", self.t["l_manifest"])
        self.assertIn("{A} {A:circles} it", self.t["m_hopper"])
        self.assertNotIn("pen down", self.t["m_hopper"])
        self.assertIn("Tolerance has a column for crew", self.t["g_ledger"])
        self.assertIn("a relay, a hopper, Cargo 2", self.t["g_ledger"])
        self.assertIn("flare forecast", self.t["m_dropout"])

    def test_galley_screen_closes_in_unanswered_endings(self):
        self.assertIn("pure coincidence", self.t["a_window_hail"])
        for cid in ("end_through", "end_patience"):
            self.assertIn("pure coincidence, a galley screen", self.t[cid], cid)
        self.assertIn("galley screen blinks ONLINE, then OFFLINE", self.t["end_close"])

    def test_through_the_dust_is_consistent(self):
        self.assertNotIn("upright", self.t["e_entry_hold_q"])
        self.assertIn("the brown closes over the window", self.t["e_entry_hold_q"])
        self.assertNotIn("Radar", self.t["end_through"])
        epi = " ".join(l for _, l in self.text["epi"]["story"])
        self.assertNotIn("upright", epi)
        self.assertNotIn("blamed a pump", epi)
        self.assertIn("the next crew's germination trays", self.t["end_long_orbit"])
        self.assertIn("Week three, storm spent", self.t["end_patience"])
        self.assertIn("{AB:They} drive home cold", self.t["end_close"])


if __name__ == "__main__":
    unittest.main()
