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


if __name__ == "__main__":
    unittest.main()
