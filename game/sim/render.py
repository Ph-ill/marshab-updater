# Python mirror of web/render.js: turns 8-byte story entries plus text.json into lines.
# The Pico never builds sentences; the phone does this, and the simulator uses this copy.
import re

from lv import ops as O

NONE = 255


def page_heading(day):
    """Log page heading. Pages 1-6 are one flight day each (launch week); from page 7
    each page covers five flight days: page NN starts on day 7 + 5*(NN-7).
    web/render.js has no copy yet; tests/render_check.mjs mirrors it (web hand-off)."""
    if day <= 6:
        a = b = day
    else:
        a = 7 + 5 * (day - 7)
        b = a + 4
    return "LOG PAGE %02d \u00b7 %s" % (day, ("DAY %d" % a) if a == b else ("DAYS %d\u2013%d" % (a, b)))


VOICE_CARDS = 2  # web/render.js uses the same cap

class Renderer:
    def __init__(self, text, eng=None):
        self.t = text
        self.e = eng     # build/engage.json, optional: without it gift lines are skipped
        self.roles = {}  # card -> (A, B) from the entry that opened it
        self.ties = 0    # tie closes seen so far: steps through sys.dec_tie
        self.vcards = {}  # crew -> cards that printed their voice this season
        self.card = NONE

    def name(self, c):
        return self.t["crew"][c] if c != NONE and c < len(self.t["crew"]) else "someone"

    def voice(self, c):
        # A crewmate's own sign-off (roster.lv `voice`), for {Av}/{Bv}. Each crewmate's
        # voice prints on at most VOICE_CARDS cards a season; later cards get "Noted."
        v = self.t.get("voice") or []
        if c == NONE or c >= len(v):
            return "Out."
        seen = self.vcards.setdefault(c, [])
        if self.card not in seen:
            if len(seen) >= VOICE_CARDS:
                return "Noted."
            seen.append(self.card)
        return v[c]

    def fill(self, tpl, A=NONE, B=NONE, **kw):
        def sub(m):
            k = m.group(1)
            if k == "A":
                return self.name(A)
            if k == "B":
                return self.name(B)
            if k in ("Av", "Bv"):
                return self.voice(A if k == "Av" else B)
            return str(kw.get(k, m.group(0)))
        return re.sub(r"\{(\w+)\}", sub, tpl)

    def entry(self, e):
        day, code, card, a, b, c, d, _ = e
        t, sy = self.t, self.t["sys"]
        cd = t["cards"][card] if card != NONE else None
        self.card = card
        if code == O.O_EVENT:
            s = self.fill(cd["t"], a, b)
            if c != NONE:
                s += " " + self.fill(cd["o"][c][1], a, b)
            return s
        if code in (O.O_DEC_OPEN, O.O_RES_OPEN):
            self.roles[card] = (a, b)
            opts = " / ".join(self.fill(o[0], a, b) for o in cd["o"])
            lead = sy["dec_open"] if code == O.O_DEC_OPEN else sy["res_open"]
            return "%s %s [%s] %s" % (lead, self.fill(cd["t"], a, b), opts, "")
        if code == O.O_DIL_OPEN:
            self.roles[card] = (a, NONE)
            return self.fill(sy["dil_open"], a) + " " + self.fill(cd["t"], a)
        if code in (O.O_DEC_CLOSE, O.O_RES_CLOSE):
            A, B = self.roles.get(card, (NONE, NONE))
            opt = self.fill(cd["o"][a][0], A, B)
            if code == O.O_RES_CLOSE:
                lead = self.fill(sy["res_default" if c else "res_close"], opt=opt)
            elif c == 1:
                lead = self.fill(sy["dec_lean"], opt=opt)
            elif c == 2:
                # dec_tie may be a list: each tie close in the log takes the next
                # wording, so a season's ties never repeat (render.js does the same).
                tie = sy["dec_tie"]
                if isinstance(tie, list):
                    tie = tie[self.ties % len(tie)]
                    self.ties += 1
                lead = self.fill(tie, opt=opt, n=b)
            else:
                lead = self.fill(sy["dec_close"], opt=opt, n=b)
            return lead + " " + self.fill(cd["o"][a][1], A, B)
        if code == O.O_DIL_CLOSE:
            opt = cd["o"][b][0]
            lead = self.fill(sy["dil_self" if c else "dil_you"], a, opt=opt)
            return lead + " " + self.fill(cd["o"][b][1], a)
        if code == O.O_ACT:
            act = t["actions"][b]
            tpl = act["self" if d else "you"]
            ax = t["axis_words"][e[7]][1 if c == 0 else 0] if b == 1 and e[7] < 3 else ""
            res = t["res_words"][e[7]] if b == 2 and e[7] < 3 else ""
            return self.fill(tpl, a, axis=ax, res=res, T=self.name(c))
        if code == O.O_MOVE:
            tpl = sy["home"] if c == a else sy["move"]
            return self.fill(tpl, a, S=t["ships"][c])
        if code == O.O_NOTE:
            return self.fill(sy["note"], a, T=self.name(c), line=t["notes"][b])
        if code == O.O_GIFT:
            g = self.e and self.e["gifts"]
            if not g or b >= len(g["items"]) or d > 2:
                return None
            return self.fill(g["sys"][("give", "ask", "answer")[d]], a, T=self.name(c), item=g["items"][b][0])
        if code == O.O_SHORT:
            return sy["short"]
        if code == O.O_END:
            return sy["end"] + " " + self.fill(cd["t"], a, b)
        return None

    def lines(self, out, routine=False):
        # Yields (day, text). routine=False hides self-chosen chores, which the phone
        # folds into a one-line "the rest of the crew kept the ship running".
        self.ties = 0
        self.vcards = {}
        for i in range(0, len(out), 8):
            e = out[i:i + 8]
            if not routine and e[1] == O.O_ACT and e[6] == 1 and e[4] != 0:
                continue
            s = self.entry(e)
            if s:
                yield e[0], s.strip()

    ECHO = (O.O_ACT, O.O_MOVE, O.O_NOTE)

    def reader(self, out):
        # The reading view (sim/out/reader.txt; a hand-off for web/render.js): story
        # lines in full, and each day's system echoes (actions, crossings, notes) folded
        # into one "around the fleet" line. Self-chosen chores are left out, and so is
        # anyone who had a scene of their own that day, so a quiet day may have no fold
        # line at all. The fold goes before the day's hook (a cliffhanger stays last)
        # and never on the final day. sys.fold_pool varies the wording by day; sys.fold
        # is the fallback. The ending gets its title as a heading.
        pool = self.t["sys"].get("fold_pool") or [self.t["sys"].get("fold", "Around the fleet: {who}.")]
        cards = self.t["cards"]
        crew = len(self.t["crew"])
        last = out[len(out) - 8] if out else 0
        STORY = (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN)

        used = []

        def fold(day, folded, seen):
            names = []
            for c in folded:
                if c not in names and c not in seen and c < crew:
                    names.append(c)
            if not names or day >= last:
                return None
            who = [self.name(c) for c in names]
            if len(names) >= crew:
                who = [self.t["sys"].get("fold_all", "everyone")]
            who = who[0] if len(who) == 1 else ", ".join(who[:-1]) + " and " + who[-1]
            # Each fold takes the next line of the pool, starting from the first fold's
            # day, so a season never repeats a fold line until the pool runs out.
            if not used:
                used.append(day)
            k = used[0] + len(used) - 1
            used.append(day)
            return self.fill(pool[k % len(pool)], who=who, n=len(names))

        def flush(day, lines, folded, seen, hook_at):
            # Thinned: the fold appears on quiet days (at most one story line) and on
            # every third day otherwise, so it reads as an occasional note, not a tic.
            # Once the pool is used up, only quiet days still get one.
            spare = len(used) <= len(pool)
            f = fold(day, folded, seen) if (len(lines) <= 1 or (day % 3 == 0 and spare)) else None
            if f:
                lines.insert(len(lines) if hook_at is None else hook_at, f)
            for s in lines:
                yield day, s

        self.ties = 0
        self.vcards = {}
        day, lines, folded, seen, hook_at = None, [], [], set(), None
        for i in range(0, len(out), 8):
            e = out[i:i + 8]
            if e[0] != day:
                if day is not None:
                    yield from flush(day, lines, folded, seen, hook_at)
                day, lines, folded, seen, hook_at = e[0], [], [], set(), None
            if e[1] in self.ECHO:
                if not (e[1] == O.O_ACT and e[6] == 1 and e[4] != 0):
                    folded.append(e[3])
                continue
            if e[1] in STORY:
                seen.update(c for c in (e[3], e[4]) if c < crew)
            if e[1] == O.O_END:
                ti = cards[e[2]].get("ti")
                if ti:
                    lines.append(ti.upper())
            s = self.entry(e)
            if s:
                if e[1] == O.O_EVENT and cards[e[2]].get("h") and hook_at is None:
                    hook_at = len(lines)
                lines.append(s.strip())
        if day is not None:
            yield from flush(day, lines, folded, seen, hook_at)

    def coda(self, out):
        # Epilogue lines for someone who isn't crew (text.json epi.coda: a name and a
        # priority list of [card index, line]); the first card that fired, in any role,
        # picks the line. Kept apart from epilogue() so that stays one line per astronaut.
        cd = self.t.get("epi", {}).get("coda")
        if not cd:
            return None
        fired = set(out[i + 2] for i in range(0, len(out), 8)
                    if out[i + 1] in (O.O_EVENT, O.O_END, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN))
        for card, line in cd["lines"]:
            if card in fired:
                return cd["name"], line
        return None

    def epilogue(self, out, st=None):
        # One story line per astronaut for the end screen: text.json epi.story is a
        # priority list of [card index, line]; an astronaut gets the first line whose
        # card they were cast in as role A. Pure function of the story log; pass the
        # final state as st to fill gaps from traits and bonds (always one line per crew).
        first = {}
        for i in range(0, len(out), 8):
            code, card, a = out[i + 1], out[i + 2], out[i + 3]
            if code in (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN) and a != NONE:
                first.setdefault((card, a), True)
        lines = {}
        epi = self.t.get("epi", {})
        for card, line in epi.get("story", []):
            for c in range(len(self.t["crew"])):
                if c not in lines and (card, c) in first:
                    lines[c] = line
        if st is not None:
            self._epilogue_fallback(lines, epi, st)
        return lines

    def _epilogue_fallback(self, lines, epi, st, cut=20):
        # Anyone with no story line gets one from the end-of-season state, so the end
        # screen always has a line per astronaut: their strongest trait (epi.axis, a
        # [positive, negative] pair per axis) if it is past `cut`, else their closest
        # bond (epi.bond) if past `cut`, else epi.plain. A line already shown is
        # skipped. The phone needs the same rule; see STYLE.md "Epilogue".
        n = len(self.t["crew"])
        used = set(lines.values())
        for c in range(n):
            if c in lines:
                continue
            picks = []
            ax = epi.get("axis", [])
            for a in sorted(range(len(ax)), key=lambda a: -abs(st.trait(c, a))):
                v = st.trait(c, a)
                if abs(v) >= cut:
                    picks.append(ax[a][0 if v >= 0 else 1])
            if epi.get("bond"):
                for j in sorted((j for j in range(n) if j != c), key=lambda j: -st.bond(c, j)):
                    if st.bond(c, j) >= cut:
                        picks.append(self.fill(epi["bond"], T=self.name(j)))
                    break
            picks.append(epi.get("plain", ""))
            line = next((p for p in picks if p and p not in used), picks[-1])
            if line:
                lines[c] = line
                used.add(line)
