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


if __name__ == "__main__":
    unittest.main()
