# The engagement layer: daily drops, timed jobs, watch streaks, crewmate gifts and the
# "something is waiting for you" list that drives the home screen and the LED.
#
# Rules for this file, so the story stays the same on every ship:
#  * Drops and jobs are pure functions of (voyage key, flight day, ship). Every ship can
#    work out anyone's, nothing is stored, nothing is sent over the radio.
#  * Streaks and gifts are pure functions of the merged choice log (GIFT records are
#    ordinary signed records; lv/engine.py applies their small story effect).
#  * The only ship-local state is Local: which drops you've opened here and what was
#    waiting the last time you looked. It changes what the page highlights, never the story.
#  * Nothing here punishes anyone. A drop you never open stays openable all season, a
#    missed day is covered by your astronaut (2 per flight week), an ask nobody answers
#    just lapses.
# Integer maths only; runs unchanged on CPython and MicroPython.
from lv import record as R
from lv.prng import Rng, day_seed

S_DROP = 0x20    # day_seed salts (+ ship). 0 is the story tick, 1 the setup.
S_OFF = 0x28
S_JOB = 0x30

GRACE_PER_WEEK = 2
WEEK = 7

# "Waiting" keys: kind * 65536 + detail.
W_DROP = 1       # detail = day
W_JOB = 2        # detail = day (only once its finish time has passed)
W_GIFT = 3       # detail = (day * 8 + from) * 4 + mode
W_VOTE = 4       # detail = card * 64 + opened day
W_DIL = 5        # detail = card * 64 + opened day
W_HOOK = 6       # detail = day the cliffhanger fired (tonight's last line)
W_RESOLVED = 7   # detail = day its resolution fired (this morning)


class Table:
    """build/engage.bin (tools/lve.py): odds, counts and windows. No text."""

    def __init__(self, data):
        data = bytes(data)
        if data[:4] != b"LVE1":
            raise ValueError("not an engage table")
        p = 4
        n = data[p]
        p += 1
        self.pct = data[p:p + n]
        p += n
        self.count = data[p:p + n]
        p += n
        self.pity = data[p]
        self.job_pct = data[p + 1]
        nj = data[p + 2]
        p += 3
        self.jobs = []   # (h0, h1, weights)
        for _ in range(nj):
            h0, h1, no = data[p], data[p + 1], data[p + 2]
            self.jobs.append((h0, h1, list(data[p + 3:p + 3 + no])))
            p += 3 + no
        ng = data[p]
        self.gift_flags = data[p + 1:p + 1 + ng]
        self.ask_days = data[p + 1 + ng]
        self.size = len(data)


def load_table(path):
    with open(path, "rb") as f:
        return Table(f.read())


class Engage:
    def __init__(self, table, voyage_key, season, n=7):
        self.t = table
        self.vk = bytes(voyage_key)
        self.season = season
        self.n = n
        self._drops = [None] * n

    # ---- daily drop ----------------------------------------------------------------
    def drops(self, ship):
        """bytearray: [2*d] = tier, [2*d+1] = item within the tier, for d = 1..season.
        Items in a tier come round in order from a per-ship offset (no repeats until the
        tier runs out). If `pity` days pass without the top tier, the next drop is one."""
        got = self._drops[ship]
        if got is not None:
            return got
        t = self.t
        nt = len(t.pct)
        top = nt - 1
        out = bytearray(2 * (self.season + 1))
        o = Rng(day_seed(self.vk, 0, S_OFF + ship))
        offs = [o.below(c) for c in t.count]
        seen = [0] * nt
        last_top = 0
        for d in range(1, self.season + 1):
            roll = Rng(day_seed(self.vk, d, S_DROP + ship)).below(100)
            tier, acc = top, 0
            for i in range(nt):
                acc += t.pct[i]
                if roll < acc:
                    tier = i
                    break
            if t.pity and tier != top and d - last_top >= t.pity:
                tier = top
            if tier == top:
                last_top = d
            out[2 * d] = tier
            out[2 * d + 1] = (offs[tier] + seen[tier]) % t.count[tier]
            seen[tier] += 1
        self._drops[ship] = out
        return out

    def drop(self, ship, day):
        b = self.drops(ship)
        return b[2 * day], b[2 * day + 1]

    # ---- timed job -----------------------------------------------------------------
    def job(self, ship, day):
        """None, or (job index, finish minute of the local day, outcome index). All fixed by
        the seed: the clock only decides when the phone may show the outcome."""
        t = self.t
        if not t.jobs:
            return None
        r = Rng(day_seed(self.vk, day, S_JOB + ship))
        if not r.chance(t.job_pct):
            return None
        j = r.below(len(t.jobs))
        h0, h1, w = t.jobs[j]
        done = h0 * 60 + r.below((h1 - h0) * 4) * 15
        return j, done, r.weighted(w)


# ---- from the choice log -----------------------------------------------------------
def active_days(log, ship, season):
    """bytearray(season + 2): 1 on every flight day this ship authored any record."""
    a = bytearray(season + 2)
    for r in log.recs.values():
        if R.ship(r) == ship:
            d = R.day(r)
            if 1 <= d <= season:
                a[d] = 1
    return a


def streak(active, today, grace=GRACE_PER_WEEK):
    """Watch-duty streak through `today`. Today never breaks it (the day isn't over).
    A missed day while a streak is running is covered by your astronaut, up to `grace`
    per flight week (FD 1-7, 8-14, ...). Returns (current, best, covered days)."""
    cur = best = used = 0
    wk = -1
    covered = []
    for d in range(1, today + 1):
        w = (d - 1) // WEEK
        if w != wk:
            wk, used = w, 0
        if active[d]:
            cur += 1
        elif d == today:
            pass
        elif cur and used < grace:
            used += 1
            cur += 1
            covered.append(d)
        else:
            cur = 0
        if cur > best:
            best = cur
    return cur, best, covered


def gifts(log, you, today, ask_days):
    """Gift traffic for crew `you`. Returns (inbox, outbox, open_asks, sent) where inbox and
    outbox are lists of (day, other crew, item, mode) sorted by day then crew, open_asks
    are asks to you from the last `ask_days` days you haven't answered, and sent is
    (gave today, asked today)."""
    inbox, outbox, answered = [], [], []
    gave = asked = False
    for k in sorted(log.recs):
        r = log.recs[k]
        if R.kind(r) != R.GIFT:
            continue
        frm, d, item, to, mode = R.ship(r), R.day(r), r[5], r[6], r[7]
        if to == you and frm != you:
            inbox.append((d, frm, item, mode))
        elif frm == you and to != you:
            outbox.append((d, to, item, mode))
            if mode == R.GIFT_ANSWER:
                answered.append((to, item, d))
            if d == today:
                if mode == R.GIFT_GIVE:
                    gave = True
                elif mode == R.GIFT_ASK:
                    asked = True
    asks = []
    for d, frm, item, mode in inbox:
        if mode != R.GIFT_ASK or d + ask_days <= today:
            continue
        done = False
        for to, it, ad in answered:
            if to == frm and it == item and ad >= d:
                done = True
        if not done:
            asks.append((d, frm, item, mode))
    return inbox, outbox, asks, (gave, asked)


# ---- ship-local ------------------------------------------------------------------------
class Local:
    """What only this ship knows: drops opened here, and the waiting list as it was at each
    crew member's last visit (so the LED and the NEW tags only flag what's changed)."""

    def __init__(self, season, n=7):
        self.season = season
        self.n = n
        self.nb = (season + 8) // 8
        self.opened = [bytearray(self.nb) for _ in range(n)]
        self.seen = [[] for _ in range(n)]
        self.dirty = False

    def is_open(self, c, d):
        return (self.opened[c][d >> 3] >> (d & 7)) & 1

    def open(self, c, d):
        if 1 <= d <= self.season and not self.is_open(c, d):
            self.opened[c][d >> 3] |= 1 << (d & 7)
            self.dirty = True
            return True
        return False

    def visit(self, c, keys):
        # Returns the keys that are new since c last looked, then remembers these.
        new = [k for k in keys if k not in self.seen[c]]
        if new or len(keys) != len(self.seen[c]):
            self.seen[c] = list(keys)
            self.dirty = True
        return new

    def unseen(self, c, keys):
        for k in keys:
            if k not in self.seen[c]:
                return True
        return False

    def dump(self):
        b = bytearray(b"LVL1")
        b.append(self.season)
        for c in range(self.n):
            b += self.opened[c]
            b.append(len(self.seen[c]))
            for k in self.seen[c]:
                b += bytes((k & 255, (k >> 8) & 255, (k >> 16) & 255))
        return bytes(b)

    @classmethod
    def load(cls, data, n=7):
        data = bytes(data)
        if data[:4] != b"LVL1":
            raise ValueError("bad local file")
        s = cls(data[4], n)
        p = 5
        for c in range(n):
            s.opened[c] = bytearray(data[p:p + s.nb])
            p += s.nb
            m = data[p]
            p += 1
            for _ in range(m):
                s.seen[c].append(data[p] | (data[p + 1] << 8) | (data[p + 2] << 16))
                p += 3
        return s


# ---- what's waiting ---------------------------------------------------------------------
def hooks_today(pack, st):
    """(day a cliffhanger fired tonight or 0, day its resolution fired this morning or 0).
    Read from the cards' fired days, so it costs nothing to keep. F_HOOK = 4 (lv/ops.py)."""
    tonight = resolved = 0
    for c in pack.cards:
        if c.flags & 4:
            f = st.fired[c.idx]
            if f == st.day:
                tonight = f
            elif f and f == st.day - 1:
                resolved = st.day
    return tonight, resolved


def waiting(eng, local, pack, st, log, you, minute):
    """Keys for everything worth a look for crew `you` today. `minute` is the local minute
    of the day from the learned clock, or None if the ship doesn't know the time (a job
    then never counts as done, so the LED stays dark rather than guess)."""
    from lv import ops as O
    d = st.day
    keys = []
    if d < 1:
        return keys
    if not local.is_open(you, d):
        keys.append(W_DROP * 65536 + d)
    j = eng.job(you, d)
    if j is not None and minute is not None and minute >= j[1]:
        keys.append(W_JOB * 65536 + d)
    inbox, _, _, _ = gifts(log, you, d, eng.t.ask_days)
    for gd, frm, item, mode in inbox:
        if gd + eng.t.ask_days > d:
            keys.append(W_GIFT * 65536 + (gd * 8 + frm) * 4 + mode)
    mine = {}    # (kind, card) -> latest day you answered it (any delivery delay)
    for r in log.recs.values():
        k = R.kind(r)
        if (k == R.VOTE or k == R.DILEMMA) and R.ship(r) == you:
            t = (k, r[5])
            if R.day(r) > mine.get(t, -1):
                mine[t] = R.day(r)
    for it in st.pend:
        ctype, idx, opened = it[0], it[1], it[2]
        if ctype == O.DILEMMA:
            if it[4] != you:
                continue
            kind, w = R.DILEMMA, W_DIL
        else:
            kind, w = R.VOTE, W_VOTE
        if mine.get((kind, idx), -1) < opened:
            keys.append(w * 65536 + idx * 64 + opened)
    tonight, resolved = hooks_today(pack, st)
    if tonight:
        keys.append(W_HOOK * 65536 + tonight)
    if resolved:
        keys.append(W_RESOLVED * 65536 + resolved)
    return keys


# ---- the page's view -------------------------------------------------------------------
def view(eng, local, pack, st, log, you, minute, visit=True):
    """The engagement part of /api/state for crew `you`. With visit=True this counts as
    `you` looking: the NEW list is returned and then forgotten (LED goes dark)."""
    from lv import ops as O
    d = st.day
    keys = waiting(eng, local, pack, st, log, you, minute)
    new = local.visit(you, keys) if visit else [k for k in keys if k not in local.seen[you]]
    drops = []
    for x in range(1, d + 1):
        tier, item = eng.drop(you, x)
        drops.append([x, tier, item, local.is_open(you, x)])
    jobs = []
    for x in range(1, d + 1):
        j = eng.job(you, x)
        if j is None:
            continue
        done = x < d or (minute is not None and minute >= j[1])
        jobs.append([x, j[0], j[1], j[2] if done else -1])
    act = active_days(log, you, pack.season)
    cur, best, covered = streak(act, d)
    inbox, outbox, asks, sent = gifts(log, you, d, eng.t.ask_days)
    votes = rescues = given = 0
    for r in log.recs.values():
        if R.ship(r) != you:
            continue
        k = R.kind(r)
        if k == R.VOTE and r[5] < len(pack.cards):
            if pack.cards[r[5]].type == O.RESCUE:
                rescues += 1
            else:
                votes += 1
        elif k == R.GIFT and r[7] != R.GIFT_ASK:
            given += 1
    tonight, resolved = hooks_today(pack, st)
    return {
        "new": new,
        "drops": drops,
        "jobs": jobs,
        "minute": minute,
        "streak": {"cur": cur, "best": best, "covered": covered, "today": act[d] == 1,
                   "days": [x for x in range(1, d + 1) if act[x]]},
        "gifts": {"in": [list(g) for g in inbox[-12:]], "out": [list(g) for g in outbox[-12:]],
                  "asks": [list(g) for g in asks], "gave": sent[0], "asked": sent[1]},
        "stats": {"votes": votes, "rescues": rescues, "gifts": given},
        "hook": [tonight, resolved],
    }
