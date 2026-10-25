#!/usr/bin/env python3
"""Second person: every ship reads its own astronaut as "you".

Story text is shared by all eight ships; sim/render.py and web/render.js turn the
viewer's own crew member into you/your/yours/yourself at render time (tokens in
content/STYLE.md). For each of the 8 viewers this renders the reference season the way
the phone does (sim/season.py writes build/season_story.bin) and checks that:

  * no narration names the viewer (quoted speech may: people call each other by name);
  * the grammar holds: no "you checks", "you is", "You's", no lowercase "you" opening a
    sentence and no capital "You" in the middle of one;
  * with no viewer, every line is exactly as written (sim/out/narrative.txt is that).

It also renders every card, system and engagement string with each of its roles as the
viewer, so lines the reference season never reaches are checked too, and writes
build/season_you.json for tests/render_check.mjs (render.js must match, per viewer).
Run after sim/season.py: python3 tests/test_you_voice.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lv import ops as O                    # noqa: E402
from sim.render import Renderer, NONE      # noqa: E402

B = os.path.join(ROOT, "build")
text = json.load(open(os.path.join(B, "text.json"), encoding="utf-8"))
try:
    eng = json.load(open(os.path.join(B, "engage.json"), encoding="utf-8"))
except OSError:
    eng = None
story = open(os.path.join(B, "season_story.bin"), "rb").read()
crew = text["crew"]
fails = []

# Third-person verbs the content marks for agreement ({A:checks}): after a bare "you"
# they mean a marker is missing.
SRC = json.dumps(text) + json.dumps(eng or {})
LEX = set(re.findall(r"\{(?:A|B|T|AB):([a-z]+s)\}", SRC)) - {"yours", "theirs", "themselves", "always", "its"}


def narration(s):
    """The line with quoted speech blanked out (straight and curly quotes)."""
    return re.sub(r'"[^"]*"|\u201c[^\u201d]*\u201d', '""', s)


def grammar(where, s):
    n = narration(s)
    checks = [
        (r"\byou(?:\s+\w+ly)?\s+(is|was|has|does|isn't|wasn't|hasn't|doesn't)\b", "you + is/was/has/does"),
        (r"\b[Yy]ou's\b", "You's"),
        (r"^\s*you\b|[.!?]\s+you\b", "lowercase you opening a sentence"),
        (r"[a-z,;]\s+(You|Your|Yours|Yourself)\b", "capital You mid-sentence"),
        (r"\b[Yy]our(?=\s+(?:now|is|was|comes|goes)\b)", "your where yours is meant"),
    ]
    for rx, what in checks:
        m = re.search(rx, n)
        if m:
            fails.append("%s: %s: ...%s..." % (where, what, n[max(0, m.start() - 40):m.end() + 20]))
    for m in re.finditer(r"\b[Yy]ou(?:\s+\w+ly)?\s+([a-z]+s)\b", n):
        if m.group(1) in LEX:
            fails.append("%s: you + %s: ...%s..." % (where, m.group(1), n[max(0, m.start() - 40):m.end() + 20]))


def phone_lines(rd):
    """What the phone's log shows (web/app.html story()): others' instructions in the
    owner wording, others' private questions as the lead only, self chores folded."""
    t = rd.t
    owner = [dict(a, you=a.get("owner") or a["you"]) for a in t["actions"]]
    rd.ties, rd.vcards = 0, {}
    for i in range(0, len(story), 8):
        e = story[i:i + 8]
        code = e[1]
        if code == O.O_ACT and e[6] == 1 and e[4] != 0:
            continue
        if code == O.O_ACT and e[3] != rd.me and not e[6]:
            keep, t["actions"] = t["actions"], owner
            s = rd.entry(e)
            t["actions"] = keep
        elif code == O.O_DIL_OPEN and e[3] != rd.me:
            rd.roles[e[2]] = (e[3], NONE)
            s = rd.fill(t["sys"]["dil_open"], e[3])
        else:
            s = rd.entry(e)
        if s:
            yield e[0], s.strip()


out = {}
total = 0
for me in range(len(crew)):
    name = re.compile(r"\b%s\b" % re.escape(crew[me]))
    seen = []
    for day, s in phone_lines(Renderer(text, eng, me)):
        seen.append(("FD %d" % day, s))
    for day, s in Renderer(text, eng, me).reader(story):
        seen.append(("reader FD %d" % day, s))
    epi = Renderer(text, eng, me).epilogue(story)
    for c, s in epi.items():
        seen.append(("epilogue %s" % crew[c], s))
    for where, s in seen:
        total += 1
        if name.search(narration(s)):
            fails.append("ship %d reads its own name in narration (%s)" % (me + 1, where))
        grammar("ship %d %s" % (me + 1, where), s)
    rd = Renderer(text, eng, me)
    out[me] = {"lines": ["%d\t%s" % (d, s) for d, s in rd.lines(story)],
               "epilogue": {str(c): s for c, s in Renderer(text, eng, me).epilogue(story).items()}}

# No viewer: as written (the committed narrative is the third-person reference).
plain = "\n".join(s for _, s in Renderer(text, eng).lines(story))
written = open(os.path.join(ROOT, "sim/out/narrative.txt"), encoding="utf-8").read()
for s in plain.split("\n"):
    if s and s not in written:
        fails.append("no-viewer line differs from sim/out/narrative.txt")
        break

# Every string, every role as the viewer (dummy names keep real ones out of the output).
dummy = dict(text, crew=["Ann", "Bea", "Cy"] + ["X%d" % i for i in range(len(crew) - 3)])
strings = []
for i, c in enumerate(text["cards"]):
    k = "card %d" % i  # by number, so a failure names no story
    strings += [(k, c["t"])] + [(k, o[0] + " || " + o[1]) for o in c["o"]]


def walk(x, path):
    if isinstance(x, str):
        strings.append((path, x))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, "%s.%d" % (path, i))
    elif isinstance(x, dict):
        for k, v in x.items():
            walk(v, path + "." + k)


walk({k: text[k] for k in ("actions", "sys", "epi") if k in text}, "text")
if eng:
    walk(eng, "engage")
fills = []
for where, s in strings:
    roles = [r for r in "ABT" if re.search(r"\{%s[}:?']" % r, s)] or (["A"] if where.startswith("text.epi") else [])
    if "{AB" in s:
        roles = sorted(set(roles) | {"A", "B"})
    for r in roles:
        me = {"A": 0, "B": 1, "T": 2}[r]
        got = Renderer(dummy, eng, me).fill(s, 0, 1, T=2)
        fills.append([s, me, got])
        total += 1
        if re.search(r"\b(Ann|Bea|Cy)\b", narration(got)) and {"A": "Ann", "B": "Bea", "T": "Cy"}[r] in narration(got):
            fails.append("%s as %s: the viewer is named in narration" % (where, r))
        grammar("%s as %s" % (where, r), got)

out["fills"] = fills
json.dump(out, open(os.path.join(B, "season_you.json"), "w", encoding="utf-8"), ensure_ascii=False)
if fails:
    print("\n".join(fails[:40]))
    print("you-voice: %d problem(s)" % len(fails))
    sys.exit(1)
print("you-voice: 8 viewers, %d lines rendered in second person, no self-naming narration, grammar clean" % total)
