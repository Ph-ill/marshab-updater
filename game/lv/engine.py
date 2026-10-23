# The daily tick. The story on day d is a pure function of (pack, state after d-1,
# the log records that take effect on day d, and the votes/answers in effect by d).
# Nothing waits on a player: every vote has a default, every astronaut acts alone.
from lv import ops as O
from lv import record as R
from lv.prng import Rng, day_seed
from lv.state import N

NONE = O.NONE

# Daily instruction menu (payload of an ACTION record)
A_GIFT, A_ADVICE, A_TASK, A_REST = 0, 1, 2, 3

FOOD, FUEL, SPARES = 0, 1, 2

# Which condition ops take roles in a (and b)
_ROLE_A = (O.C_TRAIT_GE, O.C_TRAIT_LE, O.C_BOND_GE, O.C_BOND_LE, O.C_SAME, O.C_APART,
           O.C_COND, O.C_IDLE_GE, O.C_MORALE_LE, O.C_MORALE_GE, O.C_KIT_ELSE,
           O.C_BESTBOND, O.C_IS, O.C_HOME, O.C_AWAY, O.C_CREW)
_ROLE_B = (O.C_BOND_GE, O.C_BOND_LE, O.C_SAME, O.C_APART, O.C_BESTBOND)


def _s8(v):
    return v - 256 if v > 127 else v


class Engine:
    def __init__(self, pack, state, log):
        self.p = pack
        self.s = state
        self.log = log
        self.rng = None

    # ---- conditions -------------------------------------------------------
    def _cond(self, op, a, b, c, roles):
        s = self.s
        if op == O.C_FLAG:
            return s.flag(a)
        if op == O.C_NOFLAG:
            return not s.flag(a)
        if op == O.C_VAR_GE:
            return s.vars[a] >= c
        if op == O.C_VAR_LE:
            return s.vars[a] <= c
        if op == O.C_SINCE_GE:
            return s.vars[a] > 0 and s.day - s.vars[a] >= b
        if op == O.C_RES_GE:
            return s.res[a] >= c
        if op == O.C_RES_LE:
            return s.res[a] <= c
        if op == O.C_FIRED:
            return s.fired[a] > 0
        if op == O.C_NOTFIRED:
            return s.fired[a] == 0
        if op == O.C_DAY_GE:
            return s.day >= b
        ra = roles[a] if op in _ROLE_A else NONE
        rb = roles[b] if op in _ROLE_B else NONE
        if ra == NONE or (op in _ROLE_B and rb == NONE):
            return True  # not bound yet: checked again once it is
        if op == O.C_TRAIT_GE:
            return s.trait(ra, b) >= c
        if op == O.C_TRAIT_LE:
            return s.trait(ra, b) <= c
        if op == O.C_BOND_GE:
            return s.bond(ra, rb) >= c
        if op == O.C_BOND_LE:
            return s.bond(ra, rb) <= c
        if op == O.C_SAME:
            return s.loc[ra] == s.loc[rb]
        if op == O.C_APART:
            return s.loc[ra] != s.loc[rb]
        if op == O.C_COND:
            return s.cond[ra] == b
        if op == O.C_IDLE_GE:
            return s.day - s.last_seen[ra] >= b
        if op == O.C_MORALE_LE:
            return s.morale[ra] <= c
        if op == O.C_MORALE_GE:
            return s.morale[ra] >= c
        if op == O.C_KIT_ELSE:
            return self._kit_ship(s.loc[ra]) != NONE
        if op == O.C_BESTBOND:
            return self._best_bond(rb) == ra
        if op == O.C_IS:
            return s.vars[b] == ra + 1
        if op == O.C_HOME:
            return s.loc[ra] == ra
        if op == O.C_AWAY:
            return s.loc[ra] != ra
        if op == O.C_CREW:
            return (b >> ra) & 1 == 1
        return False

    def _check(self, off, roles):
        ops = self.p.data
        end = off + 1 + 4 * ops[off]
        for i in range(off + 1, end, 4):
            if not self._cond(ops[i], ops[i + 1], ops[i + 2], _s8(ops[i + 3]), roles):
                return False
        return True

    def _best_bond(self, x):
        s = self.s
        best, bv = NONE, -1000
        for j in range(N):
            if j != x and s.cond[j] != O.COND_HOME:
                v = s.bond(x, j)
                if v > bv:
                    best, bv = j, v
        return best

    def _kit_ship(self, not_ship):
        s = self.s
        best, bv = NONE, 0
        for j in range(N):
            if j != not_ship and s.medkit[j] > bv:
                best, bv = j, s.medkit[j]
        return best

    # ---- role binding ----------------------------------------------------
    def bind(self, card, preset=None):
        roles = bytearray([NONE] * 4)
        k = 0
        if preset:
            while k < card.nroles and k < len(preset) and preset[k] != NONE:
                roles[k] = preset[k]
                k += 1
        start = self.rng.below(N)
        if self._bind(card, roles, k, start):
            return roles
        return None

    def _bind(self, card, roles, k, start):
        if k >= card.nroles:
            return self._check(card.conds, roles)
        s = self.s
        for i in range(N):
            c = (start + i) % N
            if s.cond[c] == O.COND_HOME:
                continue
            taken = False
            for j in range(k):
                if roles[j] == c:
                    taken = True
            if taken:
                continue
            if k == 0 and card.type == O.DILEMMA and not self._can_offer(card, c):
                continue
            roles[k] = c
            if self._check(card.conds, roles) and self._bind(card, roles, k + 1, start):
                return True
        roles[k] = NONE
        return False

    def _can_offer(self, card, c):
        # At most 2 private dilemmas per player per season, each card once per player,
        # and never two open at once for the same player.
        s = self.s
        if s.dil_given[c] >= 2 or (s.dil_seen[card.idx] >> c) & 1:
            return False
        for it in s.pend:
            if it[0] == O.DILEMMA and it[4] == c:
                return False
        return True

    def eligible(self, card):
        s = self.s
        d = s.day
        if d < card.dmin or d > card.dmax:
            return None
        last = s.fired[card.idx]
        if last and (card.flags & O.F_ONCE):
            return None
        if last and card.cooldown and d - last < card.cooldown:
            return None
        if last == d:
            return None
        return self.bind(card)

    # ---- effects ------------------------------------------------------------
    def apply(self, off, roles):
        s = self.s
        ops = self.p.data
        for i in range(off + 1, off + 1 + 4 * ops[off], 4):
            op, a, b, c = ops[i], ops[i + 1], ops[i + 2], _s8(ops[i + 3])
            if op == O.E_SET:
                s.set_flag(a, 1)
            elif op == O.E_CLR:
                s.set_flag(a, 0)
            elif op == O.E_VADD:
                v = s.vars[a] + c
                s.vars[a] = 255 if v > 255 else 0 if v < 0 else v
            elif op == O.E_MARK:
                s.vars[a] = s.day
            elif op == O.E_WHO:
                s.vars[a] = roles[b] + 1
            elif op == O.E_RADD:
                s.add_res(a, c)
            elif op == O.E_TRAIT:
                s.add_trait(roles[a], b, c)
            elif op == O.E_BOND:
                s.add_bond(roles[a], roles[b], c)
            elif op == O.E_MORALE:
                s.add_morale(roles[a], c)
            elif op == O.E_COND:
                s.cond[roles[a]] = b
            elif op == O.E_MOVE:
                self._move(roles[a], s.loc[roles[b]])
            elif op == O.E_GOHOME:
                self._move(roles[a], roles[a])
            elif op == O.E_KIT:
                k = self._kit_ship(s.loc[roles[a]])
                if k != NONE:
                    s.medkit[k] -= 1
                    s.cond[roles[a]] = O.COND_OK
            elif op == O.E_KITFROM:
                src = s.loc[roles[a]]
                if s.medkit[src] == 0:
                    src = self._kit_ship(NONE)
                if src != NONE:
                    s.medkit[src] -= 1
                    s.cond[roles[b]] = O.COND_OK
            elif op == O.E_OPEN:
                self.open(self.p.cards[a], roles)

    def _move(self, c, ship):
        s = self.s
        if s.loc[c] != ship:
            s.emit(O.O_MOVE, NONE, c, s.loc[c], ship)
            s.loc[c] = ship

    # ---- open items: decisions, dilemmas, rescues -------------------------------
    def open(self, card, preset=None):
        s = self.s
        roles = self.bind(card, preset) if card.nroles else bytearray([NONE] * 4)
        if roles is None:
            return False
        s.fired[card.idx] = s.day
        s.pend.append(bytes((card.type, card.idx, s.day, s.day + card.duration,
                             roles[0], roles[1], roles[2], roles[3])))
        if card.type == O.DILEMMA:
            s.dil_given[roles[0]] += 1
            s.dil_seen[card.idx] |= 1 << roles[0]
            s.emit(O.O_DIL_OPEN, card.idx, roles[0])
        elif card.type == O.RESCUE:
            s.emit(O.O_RES_OPEN, card.idx, roles[0], roles[1])
        else:
            s.emit(O.O_DEC_OPEN, card.idx, roles[0], roles[1])
        self.apply(card.effects, roles)
        return True

    def fleet_lean(self, axis):
        s = self.s
        t = 0
        for c in range(N):
            if s.cond[c] != O.COND_HOME:
                t += s.trait(c, axis)
        return t

    def _close(self, item):
        s = self.s
        ctype, idx, opened, close = item[0], item[1], item[2], item[3]
        roles = bytearray(item[4:8])
        card = self.p.cards[idx]
        nopt = card.nopt
        if ctype == O.DILEMMA:
            owner = roles[0]
            opt, by = NONE, 1
            for ship, o in self.log.answers(R.DILEMMA, idx, opened, close):
                if ship == owner and o < nopt:
                    opt, by = o, 0
            if opt == NONE:
                opt = card.lpos if s.trait(owner, card.laxis) >= 0 else card.lneg
            self.apply(self.p.opt(card, opt), roles)
            s.emit(O.O_DIL_CLOSE, idx, owner, opt, by)
            return
        ballots = self.log.answers(R.VOTE, idx, opened, close)
        tally = [0] * nopt
        n = 0
        for ship, o in ballots:
            if o < nopt:
                tally[o] += 1
                n += 1
        if ctype == O.RESCUE:
            # One tap from anyone is enough; with mixed taps the most common wins.
            if n:
                opt = 0
                for i in range(nopt):
                    if tally[i] > tally[opt]:
                        opt = i
                defaulted = 0
            else:
                opt, defaulted = card.lpos, 1
            self.apply(self.p.opt(card, opt), roles)
            s.emit(O.O_RES_CLOSE, idx, opt, n, defaulted)
            return
        lean = card.lpos if self.fleet_lean(card.laxis) >= 0 else card.lneg
        if n == 0:
            opt, defaulted = lean, 1
        else:
            top = max(tally)
            tied = [i for i in range(nopt) if tally[i] == top]
            if len(tied) == 1:
                opt, defaulted = tied[0], 0
            else:
                opt, defaulted = (lean if lean in tied else tied[0]), 2  # 2 = tie broken by lean
        self.apply(self.p.opt(card, opt), roles)
        s.emit(O.O_DEC_CLOSE, idx, opt, n, defaulted)

    # ---- daily instructions -------------------------------------------------------
    def _instruction(self, c, rec):
        s = self.s
        act, param, tgt = rec[5], rec[6], rec[7]
        if act == A_GIFT and tgt < N and tgt != c and s.cond[tgt] != O.COND_HOME:
            s.add_bond(c, tgt, 6)
            s.add_morale(tgt, 4)
        elif act == A_ADVICE and param < 3:
            s.add_trait(c, param, 6 if tgt else -6)
        elif act == A_TASK and param < 3:
            s.add_res(param, 2)
            s.add_morale(c, -1)
        elif act == A_REST:
            s.add_morale(c, 8)
        else:
            return False
        s.emit(O.O_ACT, NONE, c, act, tgt, 0, param)
        return True

    def _auto_action(self, c):
        # An astronaut whose owner gave no instruction acts on their own traits.
        s, rng = self.s, self.rng
        brave, curious, warm = s.trait(c, 0), s.trait(c, 1), s.trait(c, 2)
        act, param, tgt = A_TASK, FOOD, NONE
        if s.morale[c] < 35:
            act = A_REST
        elif warm >= 15 and rng.chance(60):
            low, lv = NONE, 1000
            for j in range(N):
                if j != c and s.loc[j] == s.loc[c] and s.cond[j] != O.COND_HOME and s.bond(c, j) < lv:
                    low, lv = j, s.bond(c, j)
            if low != NONE:
                act, tgt = A_GIFT, low
        elif curious >= 15 and rng.chance(50):
            param = SPARES
        elif brave >= 15 and rng.chance(50):
            param = FUEL
        elif rng.chance(50):
            act = A_REST
        if act == A_GIFT:
            s.add_bond(c, tgt, 6)
            s.add_morale(tgt, 4)
        elif act == A_REST:
            s.add_morale(c, 4)
        else:
            s.add_res(param, 1)
        s.emit(O.O_ACT, NONE, c, act, tgt, 1, param)

    # ---- wandering (simulated, never tied to real proximity) -------------------------
    def _wander(self):
        s, rng = self.s, self.rng
        for c in range(N):
            if s.cond[c] != O.COND_OK:
                continue
            if s.loc[c] != c and rng.chance(12):
                self._move(c, c)
                continue
            cur = s.trait(c, 1)
            if not rng.chance(6 + (cur // 5 if cur > 0 else 0)):
                continue
            w = []
            for j in range(N):
                if j == c or s.cond[j] == O.COND_HOME or s.loc[j] == s.loc[c]:
                    w.append(0)
                else:
                    v = s.bond(c, j) + 60
                    w.append(v if v > 1 else 1)
            j = rng.weighted(w)
            if j >= 0:
                self._move(c, s.loc[j])

    # ---- picking events ---------------------------------------------------------
    def _fire(self, card, roles):
        s = self.s
        s.fired[card.idx] = s.day
        opt = NONE
        if card.nopt:
            a = roles[0] if roles[0] != NONE else 0
            opt = card.lpos if s.trait(a, card.laxis) >= 0 else card.lneg
        # Emit first so anything the card opens reads after it in the log.
        s.emit(O.O_EVENT, card.idx, roles[0], roles[1], opt)
        self.apply(card.effects, roles)
        if opt != NONE:
            self.apply(self.p.opt(card, opt), roles)

    def _pick(self, cards, pct):
        if not cards or not self.rng.chance(pct):
            return None, None
        bound = []
        w = []
        for c in cards:
            r = self.eligible(c)
            bound.append(r)
            w.append(c.weight if r is not None else 0)
        i = self.rng.weighted(w)
        if i < 0:
            return None, None
        return cards[i], bound[i]

    def _open_types(self, t):
        n = 0
        for it in self.s.pend:
            if it[0] == t:
                n += 1
        return n

    # ---- the tick -----------------------------------------------------------------
    def tick(self):
        s, p = self.s, self.p
        if s.day:
            s.close_day()
        s.out = bytearray()
        s.day += 1
        d = s.day
        self.rng = Rng(day_seed(p.voyage_key, d))
        instr = [None] * N
        for rec in self.log.effective(d):
            k, ship = R.kind(rec), R.ship(rec)
            if ship >= N:
                continue
            if R.day(rec) > s.last_seen[ship]:
                s.last_seen[ship] = R.day(rec)
            if k == R.ACTION:
                instr[ship] = rec  # key order: a later authored day overrides
            elif k == R.NOTE and rec[6] < N and rec[6] != ship and rec[5] < 3:
                s.add_bond(ship, rec[6], 3)
                s.emit(O.O_NOTE, NONE, ship, rec[5], rec[6])
        # Close whatever is due today, in the order it was opened.
        keep = []
        due = []
        for it in s.pend:
            (due if it[3] <= d else keep).append(it)
        s.pend = keep
        for it in due:
            self._close(it)
        # Every astronaut still aboard does one thing.
        for c in range(N):
            if s.cond[c] == O.COND_HOME:
                continue
            if s.cond[c] == O.COND_INJURED:
                if self.rng.chance(8):
                    s.cond[c] = O.COND_OK  # slow natural recovery, so nothing is stuck forever
                continue
            if instr[c] is None or not self._instruction(c, instr[c]):
                self._auto_action(c)
        self._wander()
        # Consumption
        before = s.res[FOOD]
        s.add_res(FOOD, -3)
        if d % 2 == 0:
            s.add_res(FUEL, -1)
        if before > 20 >= s.res[FOOD]:
            s.emit(O.O_SHORT, NONE, FOOD)
        # Callbacks first, then the day's dice.
        for c in p.cards:
            if (c.flags & O.F_DUE) and (c.type == O.EVENT or c.type == O.BEAT):
                r = self.eligible(c)
                if r is not None:
                    self._fire(c, r)
        events = [c for c in p.cards if c.type == O.EVENT and not (c.flags & O.F_DUE)]
        c, r = self._pick(events, 55)
        if c is not None:
            self._fire(c, r)
        if not self._open_types(O.DECISION):
            c, r = self._pick(p.of_type(O.DECISION), 50)
            if c is not None:
                self.open(c, r)
        dils = []
        for c in p.of_type(O.DILEMMA):
            dils.append(c)
        c, r = self._pick(dils, 35)
        if c is not None:
            self.open(c, r)
        beats = [c for c in p.cards if c.type == O.BEAT and not (c.flags & O.F_DUE)]
        for _ in range(2):
            c, r = self._pick(beats, 60)
            if c is not None:
                self._fire(c, r)
        if d == p.season:
            self._ending()
        return d

    def _ending(self):
        s = self.s
        for c in self.p.of_type(O.ENDING):
            if self._check(c.conds, bytearray([NONE] * 4)):
                s.ending = c.idx
                s.fired[c.idx] = s.day
                s.emit(O.O_END, c.idx)
                return
