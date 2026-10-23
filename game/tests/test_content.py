#!/usr/bin/env python3
"""Compiler and content tests: card-language features (roster tags, cliffhanger hooks)
and house-style checks over the real card set. Run: python3 game/tests/test_content.py"""
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
from lv.state import State              # noqa: E402

FK = b"test-fleet-key-not-secret"
CONTENT = os.path.join(ROOT, "content")


def mini_content(cards, roster=None):
    """A throwaway content dir: the real fleet.lv and system.json, custom roster and cards."""
    d = tempfile.mkdtemp(prefix="lvc-")
    shutil.copy(os.path.join(CONTENT, "fleet.lv"), d)
    shutil.copy(os.path.join(CONTENT, "system.json"), d)
    names = ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian"]
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
text {A} looks at the bracket.
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
text {A} sorts it out. (%d)
""" % (i, i, i, i, i))
    filler = """
card filler
type beat
weight 50
cooldown 1
roles A
text {A} makes coffee.

card ev
type event
cooldown 1
roles A
text {A} checks the dosimeter.
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
        src = "".join("card fix%d\ntype beat\ncat repair%s\nroles A\ntext {A} fixes thing %d.\n\n"
                      % (i, " skill" if i < 2 else "", i) for i in range(3))
        src += "card ok1\ntype beat\ncat life\nroles A\ntext {A} sleeps.\n\ncard un\ntype beat\nroles A\ntext {A} waits.\n"
        _, _, ctx = lvc.build(mini_content(src))
        msg = " ".join(ctx.warnings)
        self.assertIn("repair/fault", msg)
        self.assertIn("skill flavor", msg)
        self.assertIn("no `cat` line", msg)

    def test_bad_category_is_an_error(self):
        _, _, ctx = lvc.build(mini_content("card x\ntype beat\ncat plumbing\nroles A\ntext {A}.\n"))
        self.assertTrue(any("cat is" in e for e in ctx.errors))

    def test_slow_burn_lint(self):
        src = ("card early\ntype beat\ncat life\ndays 2 20\nroles A\ntext {A} feels a chill. Something is wrong.\n\n"
               "card early_m\ntype beat\ncat mystery\ndays 5 20\nroles A\ntext {A} logs a number.\n\n"
               "card late\ntype beat\ncat mystery\ndays 30 40\nroles A\ntext {A} feels a chill.\n")
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
        st.spot[:] = bytes([9, 9, 0, 9, 9, 9, 1])
        order = eng._cast_order(0)
        self.assertEqual(order[:2], [2, 6])  # bucket 0 first, ties rotate from start
        self.assertEqual(sorted(order), list(range(7)))
        st.spot[:] = bytes(7)
        self.assertEqual(eng._cast_order(3), [3, 4, 5, 6, 0, 1, 2])
        self.assertEqual(E.FAIR_BUCKET, 2)

    def test_spot_survives_snapshot(self):
        st = State(self.p)
        st.spot[:] = bytes([1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(State.load(st.dump()).spot, st.spot)

    def test_spotlight_spread_over_seasons(self):
        sys.path.insert(0, os.path.join(ROOT, "sim"))
        from season import reference_season
        tot = [0] * 7
        for seed in range(1, 31):
            st = reference_season(Pack(self.p.data), seed=seed)[0]
            out = st.story
            for i in range(0, len(out), 8):
                if out[i + 1] in (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN):
                    for x in (out[i + 3], out[i + 4]):
                        if x < 7:
                            tot[x] += 1
        mean = sum(tot) / 7.0
        for v in tot:
            self.assertLess(abs(v - mean) / mean, 0.10, tot)

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
        # days 35-40, a window card on day 41, no blank story day 38-39, and an
        # epilogue line for every astronaut.
        from render import Renderer
        cat = {i: c["cat"] for i, c in enumerate(lvc.build(CONTENT)[2].cards)}
        ids = [c["id"] for c in text["cards"]]
        window = {ids.index("a_window_hail"), ids.index("a_window_quiet")}
        opens = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN)
        ends = {}
        for i in range(300):
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            st = reference_season(Pack(self.p.data), seed=1000 + i, voyage_key=key)[0]
            self.assertEqual(fair_play(st, text), [], "season %d" % i)
            ends[st.ending] = ends.get(st.ending, 0) + 1
            out = st.story
            myst, days = {}, set()
            for k in range(0, len(out), 8):
                if out[k + 1] in opens:
                    days.add(out[k])
                    if cat[out[k + 2]] == "mystery":
                        myst[out[k]] = myst.get(out[k], 0) + 1
            for d in range(35, 41):
                self.assertEqual(myst.get(d, 0), 1, "season %d day %d" % (i, d))
            self.assertTrue(days >= {38, 39}, "season %d" % i)
            self.assertTrue(any(out[k + 1] == O.O_EVENT and out[k + 2] in window and out[k] == 41
                                for k in range(0, len(out), 8)), "season %d" % i)
            self.assertEqual(len(Renderer(text).epilogue(out)), 7, "season %d" % i)
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
        src = ("card pick\ntype event\ndue\nonce\ndays 1 1\nroles A\ntext {A} is picked.\ndo who own A\n\n"
               "card other\ntype event\ndue\nonce\ndays 2 2\nroles A\nwhen !is A own\ntext {A} is not.\n")
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

    def test_core_groups_and_titles(self):
        src = ("card c1\ntype event\nclue core g\ndays 2 3\nroles A\ntext {A} sees one.\n\n"
               "card c2\ntype event\nclue core g\ndays 2 3\nroles A\ntext {A} sees two.\n\n"
               "card c3\ntype event\nclue core\ndays 2 3\nroles A\ntext {A} sees three.\n\n"
               "card fin\ntype ending\ntitle A Proper Title\nwhen fired c3\ntext Fin.\n")
        _, text, ctx = lvc.build(mini_content(src))
        self.assertEqual(ctx.errors, [])
        ids = [c["id"] for c in text["cards"]]
        self.assertEqual(text["core"], [[ids.index("c1"), ids.index("c2")], [ids.index("c3")]])
        self.assertEqual(text["cards"][ids.index("fin")]["ti"], "A Proper Title")

    def test_crossings_only_in_transfer_windows(self):
        # Each astronaut has a home ship; crossings happen only on transfer-window days,
        # and only to a crewmate who is at home, so a ship holds at most 2.
        src = "card idle\ntype beat\ndays 1 42\nweight 5\nroles A\ntext {A} reads.\n"
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
                held = [0] * 7
                for c in range(7):
                    held[st.loc[c]] += 1
                self.assertLessEqual(max(held), 2)
        self.assertGreater(moved, 0)

    def test_only_some_conditions_negate(self):
        src = "card bad\ntype event\ndays 2 3\nroles A\nwhen !var x >= 1\ntext {A} waits.\n"
        _, _, ctx = lvc.build(mini_content(src))
        self.assertTrue(any("negated" in e for e in ctx.errors), ctx.errors)


if __name__ == "__main__":
    unittest.main()
