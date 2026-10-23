# Python mirror of web/render.js: turns 8-byte story entries plus text.json into lines.
# The Pico never builds sentences; the phone does this, and the simulator uses this copy.
import re

from lv import ops as O

NONE = 255


class Renderer:
    def __init__(self, text):
        self.t = text
        self.roles = {}  # card -> (A, B) from the entry that opened it

    def name(self, c):
        return self.t["crew"][c] if c != NONE and c < len(self.t["crew"]) else "someone"

    def fill(self, tpl, A=NONE, B=NONE, **kw):
        def sub(m):
            k = m.group(1)
            if k == "A":
                return self.name(A)
            if k == "B":
                return self.name(B)
            return str(kw.get(k, m.group(0)))
        return re.sub(r"\{(\w+)\}", sub, tpl)

    def entry(self, e):
        day, code, card, a, b, c, d, _ = e
        t, sy = self.t, self.t["sys"]
        cd = t["cards"][card] if card != NONE else None
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
                lead = self.fill(sy["dec_tie"], opt=opt, n=b)
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
        if code == O.O_SHORT:
            return sy["short"]
        if code == O.O_END:
            return sy["end"] + " " + cd["t"]
        return None

    def lines(self, out, routine=False):
        # Yields (day, text). routine=False hides self-chosen chores, which the phone
        # folds into a one-line "the rest of the crew kept the ship running".
        for i in range(0, len(out), 8):
            e = out[i:i + 8]
            if not routine and e[1] == O.O_ACT and e[6] == 1 and e[4] != 0:
                continue
            s = self.entry(e)
            if s:
                yield e[0], s.strip()
