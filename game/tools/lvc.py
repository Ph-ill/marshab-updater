#!/usr/bin/env python3
"""lvc: compile and validate The Long Voyage story pack.

Reads content/fleet.lv, content/roster.lv, content/system.json and content/cards/*.lv. Writes:
  build/pack.bin       binary logic table the Pico runs (no text at all)
  build/text.json      card text and templates the phone renders (minified)
  build/text.json.gz   what the Pico actually serves to phones

Usage: python3 tools/lvc.py [--content DIR] [--out DIR] [--check] [--verbose] [-h|--help]
--check validates only and writes nothing. Exit code 1 on any error.
--verbose also lists bookkeeping notes (flags set but never checked). They name
story flags, so they are off by default; warnings and errors go to stderr.
-h/--help prints this text and exits without compiling anything.

Card format (one card per `card` line, indentation only matters for option effects):

  card dec_galley                 # id: lowercase letters, digits, _
  type decision                   # event | beat | decision | dilemma | rescue | ending
  days 5 14                       # first and last flight day it can fire
  weight 10                       # relative chance among eligible cards (default 10)
  once                            # fire at most once per season
  due                             # fire whenever eligible (callbacks), no dice roll
  clue [core [GROUP]]             # second-read clue (text.json "reread"); core clues
                                  #   must fire before the reveal in every season. Cards
                                  #   sharing a GROUP are alternatives: one is enough
  reveal                          # the payoff card(s) (text.json "reveal")
  title A Proper Title           # endings: shown as a heading (text.json "ti")
  each crew                       # clone the card once per astronaut: clone N binds
                                  #   role A to crew N only and fills {habit} from that
                                  #   astronaut's `habit "..."` line in roster.lv
  hook                            # cliffhanger event: last line of its day; needs a
                                  #   `due` resolver with `when fired <this card>`
  cooldown 6                      # days before it can fire again (repeatable cards)
  duration 2                      # days a decision/dilemma/rescue stays open
  roles A B                       # crew roles to bind (A first)
  lean curious fix wait           # tie-break/default: axis, option if >= 0, option if < 0
  default send                    # rescue: option used when nobody answers
  when trait A curious >= 10      # condition (see COND_SYNTAX below)
  when tag A mech                 # A is a crew member tagged `mech` in roster.lv
  when !is A cook_who             # A is not the crew member a `who` var names
  text {A} wants to fix it.       # phone template; {A} {B} are crew names
  do set seen_rock                # effect when the card fires (see EFFECT_SYNTAX)
  option fix | Fix it now | {A} opens the panel.
    set galley_fixed              # option effects, indented
"""
import gzip
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from lv import ops as O  # noqa: E402

TYPES = {"event": O.EVENT, "beat": O.BEAT, "decision": O.DECISION,
         "dilemma": O.DILEMMA, "rescue": O.RESCUE, "ending": O.ENDING}
CMP = {">=": "GE", "<=": "LE"}
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEASON_DAYS = 42


class PackError(Exception):
    pass


class Ctx:
    def __init__(self):
        self.flags = []
        self.vars = []
        self.flag_set = {}   # name -> where set
        self.flag_read = {}
        self.var_set = {}
        self.var_read = {}
        self.errors = []
        self.warnings = []
        self.crew = []       # roster lines, for `when tag`
        self.mix = {}        # category -> card count (see check_mix)

    def flag(self, name, where, setting):
        if not ID_RE.match(name):
            raise PackError("bad flag name %r" % name)
        if name not in self.flags:
            self.flags.append(name)
        (self.flag_set if setting else self.flag_read).setdefault(name, where)
        return self.flags.index(name)

    def var(self, name, where, setting):
        if not ID_RE.match(name):
            raise PackError("bad var name %r" % name)
        if name not in self.vars:
            self.vars.append(name)
        (self.var_set if setting else self.var_read).setdefault(name, where)
        return self.vars.index(name)


def sbyte(v):
    v = int(v)
    if v < -128 or v > 127:
        raise PackError("value %d out of range -128..127" % v)
    return v & 255


def ubyte(v):
    v = int(v)
    if v < 0 or v > 255:
        raise PackError("value %d out of range 0..255" % v)
    return v


def role(tok, card):
    if tok not in O.ROLES[: card["nroles"]]:
        raise PackError("role %s not declared (roles %s)" % (tok, O.ROLES[: card["nroles"]]))
    return O.ROLES.index(tok)


def axis(tok):
    if tok not in O.AXES:
        raise PackError("unknown trait %r (use %s)" % (tok, ", ".join(O.AXES)))
    return O.AXES.index(tok)


def res(tok):
    if tok not in O.RESOURCES:
        raise PackError("unknown resource %r" % tok)
    return O.RESOURCES.index(tok)


def condition(tokens, card, ctx, where):
    t = tokens
    neg = t[0].startswith("!")
    w = t[0].lstrip("!")
    if w == "flag":
        return (O.C_NOFLAG if neg else O.C_FLAG, ctx.flag(t[1], where, False), 0, 0)
    if neg and w == "fired":
        return (O.C_NOTFIRED, ("card", t[1]), 0, 0)
    if neg and w == "is":
        return (O.C_ISNT, role(t[1], card), ctx.var(t[2], where, False), 0)
    if neg:
        raise PackError("only flag, fired and is can be negated")
    if w == "fired":
        return (O.C_FIRED, ("card", t[1]), 0, 0)
    if w == "var":
        return (getattr(O, "C_VAR_" + CMP[t[2]]), ctx.var(t[1], where, False), 0, sbyte(t[3]))
    if w == "since":
        if t[2] != ">=":
            raise PackError("since only supports >=")
        return (O.C_SINCE_GE, ctx.var(t[1], where, False), ubyte(t[3]), 0)
    if w == "res":
        return (getattr(O, "C_RES_" + CMP[t[2]]), res(t[1]), 0, sbyte(t[3]))
    if w == "trait":
        return (getattr(O, "C_TRAIT_" + CMP[t[3]]), role(t[1], card), axis(t[2]), sbyte(t[4]))
    if w == "bond":
        return (getattr(O, "C_BOND_" + CMP[t[3]]), role(t[1], card), role(t[2], card), sbyte(t[4]))
    if w == "morale":
        return (getattr(O, "C_MORALE_" + CMP[t[2]]), role(t[1], card), 0, sbyte(t[3]))
    if w == "same":
        return (O.C_SAME, role(t[1], card), role(t[2], card), 0)
    if w == "apart":
        return (O.C_APART, role(t[1], card), role(t[2], card), 0)
    if w == "cond":
        return (O.C_COND, role(t[1], card), O.CONDITIONS.index(t[2]), 0)
    if w == "idle":
        if t[2] != ">=":
            raise PackError("idle only supports >=")
        return (O.C_IDLE_GE, role(t[1], card), ubyte(t[3]), 0)
    if w == "kit_elsewhere":
        return (O.C_KIT_ELSE, role(t[1], card), 0, 0)
    if w == "bestbond":
        return (O.C_BESTBOND, role(t[1], card), role(t[2], card), 0)
    if w == "is":
        return (O.C_IS, role(t[1], card), ctx.var(t[2], where, False), 0)
    if w == "day":
        return (O.C_DAY_GE, 0, ubyte(t[2]), 0)
    if w == "home":
        return (O.C_HOME, role(t[1], card), 0, 0)
    if w == "away":
        return (O.C_AWAY, role(t[1], card), 0, 0)
    if w == "tag":
        # Resolved at compile time into a bitmask of the crew who carry the tag, so the
        # engine only tests a bit. An unknown tag is an error, not a silent "nobody".
        mask = 0
        for i, cr in enumerate(ctx.crew):
            if t[2] in cr["tags"]:
                mask |= 1 << i
        if not mask:
            raise PackError("no crew member in roster.lv has tag %r" % t[2])
        return (O.C_CREW, role(t[1], card), mask, 0)
    raise PackError("unknown condition %r" % " ".join(t))


def effect(tokens, card, ctx, where):
    t = tokens
    w = t[0]
    if w == "set":
        return (O.E_SET, ctx.flag(t[1], where, True), 0, 0)
    if w == "clr":
        return (O.E_CLR, ctx.flag(t[1], where, True), 0, 0)
    if w == "var":
        return (O.E_VADD, ctx.var(t[1], where, True), 0, sbyte(t[2]))
    if w == "mark":
        return (O.E_MARK, ctx.var(t[1], where, True), 0, 0)
    if w == "who":
        return (O.E_WHO, ctx.var(t[1], where, True), role(t[2], card), 0)
    if w == "res":
        return (O.E_RADD, res(t[1]), 0, sbyte(t[2]))
    if w == "trait":
        return (O.E_TRAIT, role(t[1], card), axis(t[2]), sbyte(t[3]))
    if w == "bond":
        return (O.E_BOND, role(t[1], card), role(t[2], card), sbyte(t[3]))
    if w == "morale":
        return (O.E_MORALE, role(t[1], card), 0, sbyte(t[2]))
    if w == "cond":
        return (O.E_COND, role(t[1], card), O.CONDITIONS.index(t[2]), 0)
    if w == "move":
        return (O.E_MOVE, role(t[1], card), role(t[2], card), 0)
    if w == "kit":
        return (O.E_KIT, role(t[1], card), 0, 0)
    if w == "kitfrom":
        return (O.E_KITFROM, role(t[1], card), role(t[2], card), 0)
    if w == "open":
        return (O.E_OPEN, ("card", t[1]), 0, 0)
    if w == "gohome":
        return (O.E_GOHOME, role(t[1], card), 0, 0)
    raise PackError("unknown effect %r" % " ".join(t))


def parse_cards(path, ctx):
    cards = []
    card = None
    opt = None
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("text") else raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            where = "%s:%d" % (os.path.basename(path), n)
            indented = line[0] in " \t"
            body = line.strip()
            word, _, rest = body.partition(" ")
            try:
                if word == "card":
                    if not ID_RE.match(rest):
                        raise PackError("bad card id %r" % rest)
                    card = {"id": rest, "where": where, "type": None, "days": (1, SEASON_DAYS),
                            "weight": 10, "flags": 0, "cooldown": 0, "duration": 0, "nroles": 0,
                            "lean": None, "default": None, "conds": [], "effects": [],
                            "options": [], "text": "", "cat": None, "skill": False, "clue": False,
                            "core": None, "reveal": False, "title": "", "each": False}
                    cards.append(card)
                    opt = None
                    continue
                if card is None:
                    raise PackError("line before the first card")
                if indented and opt is not None and word not in ("option",):
                    opt["effects"].append((effect(body.split(), card, ctx, where), where))
                    continue
                opt = None if word != "option" else opt
                if word == "type":
                    card["type"] = TYPES[rest]
                elif word == "days":
                    a, b = rest.split()
                    card["days"] = (int(a), int(b))
                elif word == "weight":
                    card["weight"] = ubyte(rest)
                elif word == "once":
                    card["flags"] |= O.F_ONCE
                elif word == "due":
                    card["flags"] |= O.F_DUE
                elif word == "cat":
                    t = rest.split()
                    if not t or t[0] not in CATS or any(x != "skill" for x in t[1:]):
                        raise PackError("cat is `cat <%s> [skill]`" % "|".join(CATS))
                    card["cat"] = t[0]
                    card["skill"] = "skill" in t[1:]
                elif word == "clue":
                    card["clue"] = True  # listed in text.json "reread" for the end screen
                    t = rest.split()
                    if t[:1] == ["core"]:
                        # Must fire before the reveal in every season; a named group
                        # is satisfied by any one of its cards.
                        card["core"] = t[1] if len(t) > 1 else card["id"]
                elif word == "reveal":
                    card["reveal"] = True  # text.json "reveal"; the sim checks core clues precede it
                elif word == "title":
                    card["title"] = rest.strip()
                elif word == "hook":
                    card["flags"] |= O.F_HOOK
                elif word == "each":
                    if rest.strip() != "crew":
                        raise PackError("only `each crew` is supported")
                    card["each"] = True
                elif word == "cooldown":
                    card["cooldown"] = ubyte(rest)
                elif word == "duration":
                    card["duration"] = ubyte(rest)
                elif word == "roles":
                    rs = rest.split()
                    if rs != list(O.ROLES[: len(rs)]):
                        raise PackError("roles must be A, A B, A B C...")
                    card["nroles"] = len(rs)
                elif word == "lean":
                    card["lean"] = rest.split()
                elif word == "default":
                    card["default"] = rest.strip()
                elif word == "when":
                    card["conds"].append((condition(rest.split(), card, ctx, where), where))
                elif word == "do":
                    card["effects"].append((effect(rest.split(), card, ctx, where), where))
                elif word == "text":
                    card["text"] = rest.strip()
                elif word == "option":
                    parts = [p.strip() for p in rest.split("|")]
                    if len(parts) != 3:
                        raise PackError("option needs: name | button label | outcome text")
                    opt = {"name": parts[0], "label": parts[1], "text": parts[2], "effects": []}
                    card["options"].append(opt)
                else:
                    raise PackError("unknown keyword %r" % word)
            except (PackError, KeyError, ValueError, IndexError) as e:
                ctx.errors.append("%s: %s" % (where, e))
    return cards


def parse_crew(t):
    # crew <name> ship <ship words...> [quirk <q>] [tag <t>]... [flagship]
    cr = {"name": t[1], "quirk": None, "ship": "", "flagship": False, "tags": [], "habit": None}
    i = 2
    ship = []
    while i < len(t):
        if t[i] == "ship":
            i += 1
            while i < len(t) and t[i] not in ("quirk", "flagship", "tag"):
                ship.append(t[i])
                i += 1
            continue
        if t[i] == "quirk":
            cr["quirk"] = t[i + 1]
            i += 2
            continue
        if t[i] == "tag":
            cr["tags"].append(t[i + 1])
            i += 2
            continue
        if t[i] == "flagship":
            cr["flagship"] = True
        i += 1
    cr["ship"] = " ".join(ship)
    return cr


HABIT_RE = re.compile(r'\bhabit\s+"([^"]*)"')
# Used for anyone whose roster line has no habit yet. Deliberately generic: a real
# habit is something the player sends in, never something the writers invent.
HABIT_DEFAULT = "{A} keeps one small thing from home within reach of the console."


def split_habit(line):
    # `habit "..."` is free text, so it comes out before the line is split on spaces.
    m = HABIT_RE.search(line)
    if not m:
        return line, None
    return line[:m.start()] + line[m.end():], m.group(1).strip()


def expand_each(cards, crew, ctx):
    # `each crew` cards become one clone per astronaut, so a per-person detail can live
    # in roster.lv and the phone renderer never needs a new template slot.
    out = []
    for c in cards:
        if not c["each"]:
            out.append(c)
            continue
        if c["nroles"] < 1:
            ctx.errors.append("%s: `each crew` needs role A" % c["where"])
            continue
        for i, cr in enumerate(crew):
            habit = cr.get("habit") or HABIT_DEFAULT
            k = dict(c)
            k["id"] = "%s_%d" % (c["id"], i + 1)
            k["each"] = False
            k["text"] = c["text"].replace("{habit}", habit)
            k["options"] = [dict(o, text=o["text"].replace("{habit}", habit)) for o in c["options"]]
            k["conds"] = list(c["conds"]) + [((O.C_CREW, 0, 1 << i, 0), c["where"])]
            out.append(k)
    return out


def seeded_quirk(key, name):
    # Starting traits for a crew member with no quirk: stable, spread over -30..30.
    h = hashlib.sha256(key + b"crew:" + name.encode("utf-8")).digest()
    return [h[i] % 61 - 30 for i in range(3)]


def parse_fleet(path, roster=None):
    fleet = {"crew": [], "ships": [], "quirks": {}, "res": [0, 0, 0], "medkits": 1, "key": None,
             "season": SEASON_DAYS}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#")[0].strip()
            if not line:
                continue
            t = line.split()
            if t[0] == "voyage_key":
                fleet["key"] = bytes.fromhex(t[1])
            elif t[0] == "quirk":
                vals = dict(zip(t[2::2], t[3::2]))
                fleet["quirks"][t[1]] = [int(vals.get(a, 0)) for a in O.AXES]
            elif t[0] == "crew":
                fleet["crew"].append(parse_crew(t))
            elif t[0] == "resources":
                vals = dict(zip(t[1::2], t[2::2]))
                fleet["res"] = [int(vals[r]) for r in O.RESOURCES]
            elif t[0] == "medkits":
                fleet["medkits"] = int(t[1])
            elif t[0] == "season":
                fleet["season"] = int(t[1])
    if roster and os.path.exists(roster):
        with open(roster, encoding="utf-8") as f:
            for raw in f:
                line, habit = split_habit(raw.split("#")[0])
                t = line.split()
                if t and t[0] == "crew":
                    cr = parse_crew(t)
                    cr["habit"] = habit
                    fleet["crew"].append(cr)
    for cr in fleet["crew"]:
        if cr["quirk"] is None and fleet["key"]:
            q = "~" + cr["name"]
            fleet["quirks"][q] = seeded_quirk(fleet["key"], cr["name"])
            cr["quirk"] = q
    return fleet


GENDERED = re.compile(r"\b(he|she|him|her|his|hers|himself|herself)\b", re.I)


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def check_pronouns(cards, system, ctx):
    # The crew are real coworkers: card text never assumes anyone's gender.
    for c in cards:
        texts = [c["text"]] + [o["label"] for o in c["options"]] + [o["text"] for o in c["options"]]
        for t in texts:
            m = GENDERED.search(t)
            if m:
                ctx.errors.append("%s: gendered pronoun %r; use a name or 'they'" % (c["where"], m.group(0)))
    for t in _strings(system):
        m = GENDERED.search(t)
        if m:
            ctx.errors.append("system.json: gendered pronoun %r in %r" % (m.group(0), t[:40]))


# House-style lint (content/STYLE.md). Warnings, not errors: a human reads the
# narrative before anything ships, but these are the mistakes that sting.
SKILL_NAMECHECK = re.compile(r"\b(controls?|automation|mechanical|design|software|electrical) engineer", re.I)
DEMEANING = re.compile(r"\b(forgot|forgets|forgetting|clumsy|lazy|useless|incompetent|careless|"
                       r"screw(s|ed)? up|mess(es|ed)? up|idiot\w*|stupid|dumb)\b", re.I)
CHEAP = re.compile(r"\b(it was nothing|just a glitch|false alarm|all a dream)\b", re.I)
CALENDAR = re.compile(r"\b(months|month (one|two|three|four|five|six|\d))\b", re.I)
MAX_TEXT, MAX_LABEL = 300, 28
MAX_PAYOFF = 420   # reveal cards and the arrival-day cards (days 40+) may run longer
ROLE_CONDS = (O.C_TRAIT_GE, O.C_TRAIT_LE, O.C_BOND_GE, O.C_BOND_LE, O.C_SAME, O.C_APART,
              O.C_COND, O.C_IDLE_GE, O.C_MORALE_LE, O.C_MORALE_GE, O.C_KIT_ELSE,
              O.C_BESTBOND, O.C_HOME, O.C_AWAY, O.C_CREW, O.C_ISNT)
MAX_ENDING = 640   # an ending is a landing scene, the recorder line on unanswered branches, and the coda
PAYOFF_FROM = 40


# Content mix (STYLE.md, "Content mix"). Every card carries `cat <category>`; add
# `skill` when the text leans on controls/mechanical flavor. Compile-time only: the
# category never reaches the pack or text.json.
CATS = ("repair", "wonder", "mystery", "human", "life", "mission", "arrival", "grim", "ending")
MAX_REPAIR = 0.25   # hardware faults and fixes
MAX_SKILL = 0.18    # roughly 1 card in 6 or fewer


def check_mix(cards, ctx):
    if not any(c["cat"] for c in cards):
        return  # an uncategorized deck (e.g. a test fixture) is not judged
    mix = dict((k, 0) for k in CATS)
    mix["skill"] = 0
    for c in cards:
        if not c["cat"]:
            ctx.warnings.append("style: %s %s has no `cat` line" % (c["where"], c["id"]))
            continue
        mix[c["cat"]] += 1
        mix["skill"] += c["skill"]
    n = len(cards)
    ctx.mix = mix
    if mix["repair"] > MAX_REPAIR * n:
        ctx.warnings.append("style: mix: %d of %d cards are repair/fault (max %d%%)"
                            % (mix["repair"], n, int(MAX_REPAIR * 100)))
    if mix["skill"] > MAX_SKILL * n:
        ctx.warnings.append("style: mix: %d of %d cards carry skill flavor (max %d%%)"
                            % (mix["skill"], n, int(MAX_SKILL * 100)))


# Slow burn (STYLE.md, "The slow burn"). Nothing uncanny before day 11: cards that
# can fire earlier may not use spooky vocabulary, may not be `cat mystery`, and a
# cliffhanger that can fire before day 25 may not be `cat mystery`.
QUIET_UNTIL = 11
UNCANNY_HOOKS_FROM = 25
SPOOKY = re.compile(r"\b(eerie\w*|impossible|strange\w*|wrong|chill\w*|uncanny|creep\w*|spooky|"
                    r"ghost\w*|haunt\w*|ominous\w*|unexplained|sinister|nobody (says|knows) why|"
                    r"no one (says|knows) why|not from earth|hair on)\b", re.I)


def check_ramp(cards, ctx):
    for c in cards:
        d0, w = c["days"][0], c["where"]
        if d0 >= QUIET_UNTIL:
            continue
        for t in [c["text"]] + [o["text"] for o in c["options"]]:
            m = SPOOKY.search(t)
            if m:
                ctx.warnings.append("style: %s %s can fire on day %d and says %r; keep days 1-%d quiet"
                                    % (w, c["id"], d0, m.group(0), QUIET_UNTIL - 1))
        if c["cat"] == "mystery":
            ctx.warnings.append("style: %s %s is cat mystery but can fire on day %d (min %d)"
                                % (w, c["id"], d0, QUIET_UNTIL))
    for c in cards:
        if c["flags"] & O.F_HOOK and c["cat"] == "mystery" and c["days"][0] < UNCANNY_HOOKS_FROM:
            ctx.warnings.append("style: %s %s is an uncanny cliffhanger before day %d; early hooks stay grounded"
                                % (c["where"], c["id"], UNCANNY_HOOKS_FROM))


def mix_line(ctx):
    n = sum(v for k, v in ctx.mix.items() if k != "skill")
    if not n:
        return ""
    return "mix: " + ", ".join("%s %d (%d%%)" % (k, v, round(100.0 * v / n))
                               for k, v in ctx.mix.items() if v)


def check_style(cards, fleet, ctx):
    names = [cr["name"] for cr in fleet["crew"]]
    for c in cards:
        w = c["where"]
        parts = [("text", c["text"])] + [("option " + o["name"], o["text"]) for o in c["options"]]
        for what, t in parts:
            for n in names:
                if re.search(r"\b%s\b" % re.escape(n), t):
                    ctx.warnings.append("style: %s %s names %s; use {A}/{B} so any crew member fits" % (w, what, n))
            for rx, why in ((SKILL_NAMECHECK, "name-checks a job; keep skill flavor implicit"),
                            (DEMEANING, "may make a crewmate the butt of the joke"),
                            (CHEAP, "cheap resolution"),
                            (CALENDAR, "pins calendar time; use flight days")):
                m = rx.search(t)
                if m:
                    ctx.warnings.append("style: %s %s %r %s" % (w, what, m.group(0), why))
            cap = (MAX_ENDING if c["type"] == O.ENDING else
                   MAX_PAYOFF if (c["reveal"] or c["days"][0] >= PAYOFF_FROM) else MAX_TEXT)
            if len(t) > cap:
                ctx.warnings.append("style: %s %s is %d chars (max %d on a phone)" % (w, what, len(t), cap))
        for o in c["options"]:
            if len(o["label"]) > MAX_LABEL:
                ctx.warnings.append("style: %s button %r is long (max %d)" % (w, o["label"], MAX_LABEL))


def validate(cards, ctx, fleet, system):
    check_pronouns(cards, system, ctx)
    check_style(cards, fleet, ctx)
    check_mix(cards, ctx)
    check_ramp(cards, ctx)
    ids = [c["id"] for c in cards]
    for c in cards:
        w = c["where"]
        if ids.count(c["id"]) > 1:
            ctx.errors.append("%s: duplicate card id %s" % (w, c["id"]))
        if c["type"] is None:
            ctx.errors.append("%s: %s has no type" % (w, c["id"]))
            continue
        d0, d1 = c["days"]
        if not (1 <= d0 <= d1 <= fleet["season"]):
            ctx.errors.append("%s: days %d..%d outside 1..%d" % (w, d0, d1, fleet["season"]))
        if not c["text"]:
            ctx.errors.append("%s: %s has no text" % (w, c["id"]))
        for m in re.findall(r"\{(\w+)\}", c["text"] + "".join(o["text"] for o in c["options"])):
            if m in O.ROLES and O.ROLES.index(m) >= c["nroles"]:
                ctx.errors.append("%s: text uses {%s} but the card binds %d role(s)" % (w, m, c["nroles"]))
            elif m not in O.ROLES and m not in ("n",):
                ctx.errors.append("%s: unknown template slot {%s}" % (w, m))
        names = [o["name"] for o in c["options"]]
        voted = c["type"] in (O.DECISION, O.DILEMMA, O.RESCUE)
        if voted and len(names) < 2:
            ctx.errors.append("%s: %s needs at least 2 options" % (w, c["id"]))
        if voted and not c["duration"]:
            ctx.errors.append("%s: %s needs a duration" % (w, c["id"]))
        if c["type"] == O.DILEMMA and c["nroles"] < 1:
            ctx.errors.append("%s: a dilemma needs role A (whose owner decides)" % w)
        if c["type"] == O.RESCUE and c["default"] not in names:
            ctx.errors.append("%s: rescue %s needs `default <option>`" % (w, c["id"]))
        if c["type"] in (O.DECISION, O.DILEMMA) and not c["lean"]:
            ctx.errors.append("%s: %s needs a lean so nobody has to vote" % (w, c["id"]))
        if c["options"] and c["type"] in (O.EVENT, O.BEAT) and not c["lean"]:
            ctx.errors.append("%s: an event with options needs a lean to pick one" % w)
        if c["lean"]:
            if len(c["lean"]) != 3 or c["lean"][0] not in O.AXES:
                ctx.errors.append("%s: lean is `<axis> <option if >= 0> <option if < 0>`" % w)
            else:
                for o in c["lean"][1:]:
                    if o not in names:
                        ctx.errors.append("%s: lean names unknown option %s" % (w, o))
        if c["type"] == O.ENDING and (c["options"] or c["effects"]):
            ctx.errors.append("%s: endings have no options or effects" % w)
        if c["flags"] & O.F_DUE and not (c["flags"] & O.F_ONCE) and not c["cooldown"]:
            ctx.errors.append("%s: a due card needs once or a cooldown or it fires every day" % w)
        for (op, a, b, cc), where in c["conds"] + c["effects"] + [e for o in c["options"] for e in o["effects"]]:
            if isinstance(a, tuple):
                if a[1] not in ids:
                    ctx.errors.append("%s: unknown card %s" % (where, a[1]))
                elif op == O.E_OPEN:
                    tgt = cards[ids.index(a[1])]
                    if tgt["type"] not in (O.RESCUE, O.DECISION, O.DILEMMA):
                        ctx.errors.append("%s: open needs a rescue, decision or dilemma" % where)
    for c in cards:
        if not c["flags"] & O.F_HOOK:
            continue
        w = c["where"]
        if c["type"] != O.EVENT or c["flags"] & O.F_DUE:
            ctx.errors.append("%s: a hook must be a plain event (not due)" % w)
        if not c["flags"] & O.F_ONCE:
            ctx.errors.append("%s: a hook needs `once`" % w)
        if c["days"][1] > fleet["season"] - 2:
            ctx.errors.append("%s: a hook can't fire in the last 2 days; end its days by %d"
                              % (w, fleet["season"] - 2))
        resolvers = [r for r in cards if r["flags"] & O.F_DUE and r["type"] in (O.EVENT, O.BEAT)
                     and any(op == O.C_FIRED and a == ("card", c["id"]) for (op, a, _, _), _ in r["conds"])]
        if not resolvers:
            ctx.errors.append("%s: hook %s has no resolver (a due event with `when fired %s`)"
                              % (w, c["id"], c["id"]))
        for r in resolvers:
            if r["days"][1] < c["days"][1] + 1:
                ctx.errors.append("%s: resolver %s must run to day %d or later"
                                  % (r["where"], r["id"], c["days"][1] + 1))
    endings = [c for c in cards if c["type"] == O.ENDING]
    if not endings:
        ctx.errors.append("no ending cards")
    elif [k for k, _ in endings[-1]["conds"] if k[0] != O.C_IS]:
        ctx.errors.append("%s: the last ending (the fallback) may only name crew (`is`), "
                          "nothing that could fail" % endings[-1]["where"])
    # An ending is chosen before anyone is cast, so a role there can only be named
    # through `is X var` (the engine reads the var); any other role test would pass
    # unchecked.
    for c in endings:
        for k, _ in c["conds"]:
            if k[0] in ROLE_CONDS:
                ctx.errors.append("%s: an ending can name crew only with `is`" % c["where"])
    for f in ctx.flags:
        if f not in ctx.flag_set:
            ctx.errors.append("%s: flag %s is checked but never set" % (ctx.flag_read[f], f))
        elif f not in ctx.flag_read:
            ctx.warnings.append("%s: flag %s is set but never checked" % (ctx.flag_set[f], f))
    for v in ctx.vars:
        if v not in ctx.var_set:
            ctx.errors.append("%s: var %s is checked but never set" % (ctx.var_read[v], v))
    if fleet["key"] is None or len(fleet["key"]) != 8:
        ctx.errors.append("fleet.lv: voyage_key must be 8 bytes of hex")
    if len(fleet["crew"]) != 7:
        ctx.errors.append("roster.lv: need exactly 7 crew lines")
    if len(set(cr["name"] for cr in fleet["crew"])) != len(fleet["crew"]):
        ctx.errors.append("roster.lv: crew names must be unique")
    for cr in fleet["crew"]:
        h = cr.get("habit")
        if h is not None and (not h or "{A}" not in h or re.search(r"\{(?!A\})", h)):
            ctx.errors.append("roster.lv: %s's habit must be one sentence about {A} (no other slots)"
                              % cr["name"])
        if cr["quirk"] not in fleet["quirks"]:
            ctx.errors.append("fleet.lv: crew %s has unknown quirk %s" % (cr["name"], cr["quirk"]))
    if len(ctx.flags) > 128 or len(ctx.vars) > 32:
        ctx.errors.append("too many flags (max 128) or vars (max 32)")
    for k in ("actions", "notes", "sys"):
        if k not in system:
            ctx.errors.append("system.json: missing %s" % k)


def ops_bytes(lst, ids):
    out = bytearray([len(lst)])
    for (op, a, b, c), _ in lst:
        if isinstance(a, tuple):
            a = ids.index(a[1])
        out += bytes((op, a, b, c))
    return bytes(out)


def encode_card(c, ids):
    names = [o["name"] for o in c["options"]]
    if c["lean"]:
        la, lp, ln = O.AXES.index(c["lean"][0]), names.index(c["lean"][1]), names.index(c["lean"][2])
    elif c["default"]:
        la, lp, ln = O.NONE, names.index(c["default"]), names.index(c["default"])
    else:
        la = lp = ln = O.NONE
    b = bytearray((c["type"], c["weight"], c["days"][0], c["days"][1], c["flags"], c["cooldown"],
                   c["duration"], c["nroles"], la, lp, ln))
    b += ops_bytes(c["conds"], ids)
    b += ops_bytes(c["effects"], ids)
    b.append(len(c["options"]))
    for o in c["options"]:
        b += ops_bytes(o["effects"], ids)
    return bytes(b)


def build(content_dir):
    ctx = Ctx()
    fleet = parse_fleet(os.path.join(content_dir, "fleet.lv"), os.path.join(content_dir, "roster.lv"))
    ctx.crew = fleet["crew"]
    with open(os.path.join(content_dir, "system.json"), encoding="utf-8") as f:
        system = json.load(f)
    cards = []
    cdir = os.path.join(content_dir, "cards")
    for name in sorted(os.listdir(cdir)):
        if name.endswith(".lv"):
            cards += parse_cards(os.path.join(cdir, name), ctx)
    cards = expand_each(cards, fleet["crew"], ctx)
    # Endings must stay in priority order at the end; everything else keeps file order.
    cards = [c for c in cards if c["type"] != O.ENDING] + [c for c in cards if c["type"] == O.ENDING]
    if len(cards) > 250:
        ctx.errors.append("too many cards (max 250)")
    validate(cards, ctx, fleet, system)
    ctx.cards = cards
    if ctx.errors:
        return None, None, ctx
    ids = [c["id"] for c in cards]
    quirk_names = sorted(fleet["quirks"])
    body = bytearray()
    body += bytes((len(cards), len(ctx.flags), len(ctx.vars), 7, fleet["season"]))
    body += fleet["key"]
    body += bytes([ubyte(v) for v in fleet["res"]]) + bytes((fleet["medkits"],))
    body.append(len(quirk_names))
    for q in quirk_names:
        body += bytes([sbyte(v) for v in fleet["quirks"][q]])
    body += bytes([quirk_names.index(cr["quirk"]) for cr in fleet["crew"]])
    encoded = [encode_card(c, ids) for c in cards]
    table_start = 4 + 4 + len(body) + 2 * len(cards)
    off = table_start
    offsets = bytearray()
    for e in encoded:
        offsets += struct.pack("<H", off)
        off += len(e)
    payload = bytes(body) + bytes(offsets) + b"".join(encoded)
    pack_id = hashlib.sha256(payload).digest()[:4]
    pack = b"LVP1" + pack_id + payload
    # Epilogue story lines: [card id, line] in system.json become [card index, line].
    # For each astronaut the phone shows the first line whose card that astronaut
    # was cast in as role A (sim/render.py Renderer.epilogue).
    epi = dict(system.get("epi", {}))
    if "story" in epi:
        idx = {c["id"]: i for i, c in enumerate(cards)}
        bad = [cid for cid, _ in epi["story"] if cid not in idx]
        if bad and len(bad) < len(epi["story"]):  # a cut-down test deck may have none
            ctx.warnings.append("epi.story: unknown card(s) %s" % ", ".join(bad))
        epi["story"] = [[idx[cid], line] for cid, line in epi["story"] if cid in idx]
    if "coda" in epi:
        # {"name": ..., "lines": [[card id, line], ...]}: an epilogue line for someone
        # who isn't crew; the first listed card that fired picks it (Renderer.coda).
        idx = {c["id"]: i for i, c in enumerate(cards)}
        cd = epi["coda"]
        epi["coda"] = {"name": cd["name"], "lines": [[idx[cid], line] for cid, line in cd["lines"] if cid in idx]}
    text = {
        "pack": pack_id.hex(),
        "crew": [cr["name"] for cr in fleet["crew"]],
        "ships": [cr["ship"] for cr in fleet["crew"]],
        "flagship": next((i for i, cr in enumerate(fleet["crew"]) if cr["flagship"]), 0),
        "epi": epi,
        "cards": [dict({"id": c["id"], "t": c["text"], "o": [[o["label"], o["text"]] for o in c["options"]]},
                       **dict(({"h": 1} if c["flags"] & O.F_HOOK else {}),
                              **({"ti": c["title"]} if c["title"] else {})))
                  for c in cards],
        # Second read: card indices worth revisiting after the ending. The UI may list
        # the flight days these fired (from the story log) without explaining them.
        "reread": [i for i, c in enumerate(cards) if c["clue"]],
        # Fair play: these clue cards fire before any "reveal" card in every season
        # (sim/season.py --seasons asserts it).
        # Each entry is a group of alternatives (card indices): one per group must fire.
        "core": [[i for i, c in enumerate(cards) if c["core"] == g]
                 for g in sorted(set(c["core"] for c in cards if c["core"]),
                                 key=lambda g: min(i for i, c in enumerate(cards) if c["core"] == g))],
        "reveal": [i for i, c in enumerate(cards) if c["reveal"]],
        "actions": system["actions"],
        "notes": system["notes"],
        "axis_words": system.get("axis_words", []),
        "res_words": system.get("res_words", []),
        "sys": system["sys"],
        "axes": list(O.AXES),
        "res": list(O.RESOURCES),
    }
    return pack, text, ctx


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    content = os.path.join(os.path.dirname(HERE), "content")
    out = os.path.join(os.path.dirname(HERE), "build")
    check = "--check" in argv
    verbose = "--verbose" in argv or "-v" in argv
    if "--content" in argv:
        content = argv[argv.index("--content") + 1]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    pack, text, ctx = build(content)
    # Warnings and errors go to stderr so stdout stays a one-line summary. The
    # "set but never checked" notes name story flags, so only --verbose shows them.
    notes = [w for w in ctx.warnings if "is set but never checked" in w]
    for w in ctx.warnings:
        if w in notes and not verbose:
            continue
        print("warning:", w, file=sys.stderr)
    if notes and not verbose:
        print("note: %d unused flag(s); run with --verbose to list them" % len(notes), file=sys.stderr)
    for e in ctx.errors:
        print("error:", e, file=sys.stderr)
    if ctx.errors:
        print("%d error(s); nothing written" % len(ctx.errors), file=sys.stderr)
        return 1
    tj = json.dumps(text, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    tgz = gzip.compress(tj, 9, mtime=0)
    n = len(text["cards"])
    print("ok: %d cards, %d flags, %d vars; pack.bin %d B, text.json %d B, gzip %d B; pack id %s"
          % (n, len(ctx.flags), len(ctx.vars), len(pack), len(tj), len(tgz), text["pack"]))
    if ctx.mix:
        print(mix_line(ctx))
    if not check:
        os.makedirs(out, exist_ok=True)
        for name, data in (("pack.bin", pack), ("text.json", tj), ("text.json.gz", tgz)):
            with open(os.path.join(out, name), "wb") as f:
                f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
