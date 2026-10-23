# The phone game's JSON API on the board: the same contract sim/mockserver.py serves on a
# PC (web/app.html and web/engage.js call it), backed by this ship's real log and story.
# lvweb.Server loads this on the first /api/ request and calls Phone.api(req).
#
#   GET  /api/crew    {set: [8 bools], day[, start][, launch, until before launch]}
#   GET  /api/me      a phone that signed in here today: {token, crew, first:false}, else 401
#   GET  /api/v       {v}: bumps when anything a phone sees may have changed
#   GET  /api/state   (X-Crew-Token) the whole screen: story, open cards, crew, engagement
#   POST /api/login   {crew, pin} -> {token, crew, first} | 403 {err, left} | 429 {err, wait} | 409
#   POST /api/logout
#   POST /api/open    {day} -> {ok, day, tier, item}       (daily drop)
#   POST /api/gift    {item, to, mode} -> {ok, v} | 409 {err}
#   POST /api/act     {act, param, tgt}   POST /api/vote {card, opt}   POST /api/answer {card, opt}
#
# The board has one flight day (ship.day: from the launch date and the phones' clocks,
# board/lvcal.py, or ship.json "day" on the bench); the page's ?day= is ignored. Before
# launch only /api/crew (with the countdown: {day: 0, launch, until, start}) and /api/v
# answer; the rest is 409. Taps are signed records for today authored by whoever signed
# in (lvship.Ship.tap), so they sync to the other ships like any record.
# Crew codes come from data/crew.json (the updater writes it); without it nobody can sign in.
# What phones opened and saw is kept in /data/local.bin.
from lv import ops as O
from lv import record as R
from lv import codes as K
from lv import engage as EN
from lv.engine import Engine
from lv.state import N
from lv.clock import ticks_ms

MAX_TOKENS = 16
probe = None        # tests: called where /api/state holds the most (tests/mp_sync_heap.py)


def _int(v, d=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        if d is None:
            raise ValueError("bad request")
        return d


class Phone:
    def __init__(self, ship, root="", say=print):
        self.ship = ship
        self.root = root
        self.say = say
        self.data = ship.data
        self.book = K.load((self.data or "data") + "/crew.json")
        self.tokens = []          # [token, crew], oldest first
        self.etable = EN.load_table(root + "engage.bin")
        self.eng = EN.Engage(self.etable, ship.pack.voyage_key, ship.pack.season)
        self.local = None
        try:
            with open(self.data + "/local.bin", "rb") as f:
                self.local = EN.Local.load(f.read())
            if self.local.season != ship.pack.season:
                self.local = None
        except Exception:
            pass
        if self.local is None:
            self.local = EN.Local(ship.pack.season)
        say("phone: codes set for %d of %d, %d phones max" % (
            sum(1 for c in range(N) if self.book.is_set(c)), N, MAX_TOKENS))

    def save(self):
        if self.local.dirty and self.data:
            try:
                with open(self.data + "/local.bin", "wb") as f:
                    f.write(self.local.dump())
                self.local.dirty = False
            except OSError as e:
                self.say("phone: save failed %s" % e)

    # ---- sessions
    def token(self, crew):
        import os
        from binascii import hexlify
        t = str(hexlify(os.urandom(8)), "ascii")
        self.tokens.append([t, crew])
        if len(self.tokens) > MAX_TOKENS:
            self.tokens.pop(0)
        return t

    def who(self, req):
        t = req.header("x-crew-token")
        if t:
            for k, c in self.tokens:
                if k == t:
                    return c
        return None

    def drop_token(self, t):
        self.tokens = [x for x in self.tokens if x[0] != t]

    # ---- the API
    def api(self, req):
        """-> (status, JSON-able) or (0, coroutine function writing the response)."""
        p = req.path
        sh = self.ship
        d = max(1, sh.day)
        if sh.st is None or sh.days is None:
            return 503, {"err": "The story is switched off on this ship (story: false)."}
        if sh.day < 1 and sh.cal is not None and p not in ("/api/crew", "/api/v"):
            return 409, {"err": "The voyage hasn't launched yet.", "until": sh.cal.until()}
        if req.method == "GET":
            if p == "/api/crew":
                j = {"set": [self.book.is_set(c) for c in range(N)], "day": d}
                cal = sh.cal
                if cal is not None:
                    j["start"] = cal.start
                    if sh.day < 1:     # before launch: the page shows a countdown
                        j["day"] = 0
                        j["launch"] = cal.date
                        j["until"] = cal.until()
                return 200, j
            if p == "/api/v":
                return 200, {"v": sh.v}
            if p == "/api/me":
                c = self.book.recall(req.phone(), d)
                if c is None:
                    return 401, {"err": "signed out"}
                return 200, {"token": self.token(c), "crew": c, "first": False}
            if p == "/api/state":
                you = self.who(req)
                if you is None:
                    return 401, {"err": "signed out"}
                return 0, self.state_writer(you, _int(req.q.get("last"), max(0, d - 3)), sh.clock.minute())
            return 404, {"err": "no such thing"}
        if req.method != "POST":
            return 404, {"err": "no such thing"}
        try:
            import json
            b = json.loads(req.body or b"{}")
            if not isinstance(b, dict):
                raise ValueError
        except ValueError:
            b = {}
        if p == "/api/login":
            try:
                c = int(b.get("crew"))
                pin = str(b.get("pin", ""))
            except (TypeError, ValueError):
                return 400, {"err": "bad request"}
            st, v = self.book.check(c, pin, ticks_ms())
            if st == K.OK:
                first = not self.book.seen[c]
                self.book.seen[c] = True
                self.book.remember(req.phone(), c, d)
                return 200, {"token": self.token(c), "crew": c, "first": first}
            if st == K.WRONG:
                return 403, {"err": "That code doesn't match.", "left": v}
            if st == K.LOCKED:
                return 429, {"err": "Too many tries.", "wait": v}
            if st == K.NO_CODE:
                return 409, {"err": "No code set up for this name yet."}
            return 400, {"err": "bad request"}
        if p == "/api/logout":
            self.book.forget(req.phone())
            self.drop_token(req.header("x-crew-token") or "")
            return 200, {"ok": True}
        you = self.who(req)
        if you is None:
            return 401, {"err": "signed out"}
        try:
            if p == "/api/open":
                x = _int(b.get("day", d))
                if not 1 <= x <= d:
                    return 400, {"err": "bad request"}
                self.local.open(you, x)
                tier, item = self.eng.drop(you, x)
                return 200, {"ok": True, "day": x, "tier": tier, "item": item}
            if p == "/api/gift":
                err = self.gift(you, d, _int(b.get("item")), _int(b.get("to")), _int(b.get("mode", 0)))
                if err:
                    return (409 if err != "bad request" else 400), {"err": err}
                return 200, {"ok": True, "v": sh.v}
            if p == "/api/act":
                sh.tap(you, R.ACTION, _int(b.get("act")), _int(b.get("param", 0)), _int(b.get("tgt", 0)))
            elif p == "/api/vote":
                sh.tap(you, R.VOTE, _int(b.get("card")), _int(b.get("opt")))
            elif p == "/api/answer":
                sh.tap(you, R.DILEMMA, _int(b.get("card")), _int(b.get("opt")))
            else:
                return 404, {"err": "no such thing"}
        except ValueError:
            return 400, {"err": "bad request"}
        return 200, {"ok": True, "v": sh.v}

    def gift(self, you, day, item, to, mode):
        """The gift rules (as sim/mockserver.py). Returns an error string or None."""
        sh = self.ship
        flags = self.etable.gift_flags
        if not (0 <= to < N) or to == you or not (0 <= item < len(flags)) or mode not in (0, 1, 2):
            return "bad request"
        if sh.st.cond[to] == O.COND_HOME:
            return "They're home now."
        _, _, asks, sent = EN.gifts(sh.log, you, day, self.etable.ask_days)
        gave, asked = sent
        if mode == R.GIFT_GIVE:
            if not flags[item] & 1:
                return "bad request"
            if gave:
                return "One gift a day. Tomorrow's cargo run has room."
        elif mode == R.GIFT_ASK:
            if not flags[item] & 2:
                return "bad request"
            if asked:
                return "One ask a day."
        elif not any(a[1] == to and a[2] == item for a in asks):
            return "Nothing to answer."
        sh.tap(you, R.GIFT, item, to, mode)
        return None

    # ---- /api/state
    def state_body(self, you, last, minute):
        """Everything in /api/state except "story" (streamed separately)."""
        sh = self.ship
        st, p, log = sh.st, sh.pack, sh.log
        d = st.day
        eng = Engine(p, st, log)
        opens = []
        for it in st.pend:
            ctype, idx, opened, close = it[0], it[1], it[2], it[3]
            A, B = it[4], it[5]
            if ctype == O.DILEMMA and A != you:
                continue
            card = p.cards[idx]
            kind = R.DILEMMA if ctype == O.DILEMMA else R.VOTE
            tally = [0] * card.nopt
            mine = None
            for s, o in log.answers(kind, idx, opened, close):
                if o < card.nopt:
                    tally[o] += 1
                if s == you:
                    mine = o
            if ctype == O.DECISION:
                lean = card.lpos if eng.fleet_lean(card.laxis) >= 0 else card.lneg
            elif ctype == O.DILEMMA:
                lean = card.lpos if st.trait(A, card.laxis) >= 0 else card.lneg
            else:
                lean = card.lpos
            opens.append({"type": ctype, "card": idx, "a": A, "b": B, "opened": opened,
                          "close": close, "tally": tally, "mine": mine, "lean": lean})
        act = None
        for r in log.values():
            if R.kind(r) == R.ACTION and R.ship(r) == you and R.day(r) == d:
                act = [r[5], r[6], r[7]]
        best = []
        for c in range(N):
            bj, bb = -1, None
            for j in range(N):
                if j != c and (bb is None or st.bond(c, j) > bb):
                    bj, bb = j, st.bond(c, j)
            best.append(bj)
        upd = {}
        for k in sh.days.updated:
            upd[str(k)] = sh.days.updated[k]
        return {
            "day": d, "season": p.season, "you": you, "here": sh.me, "last": last,
            "loc": list(st.loc), "cond": list(st.cond), "morale": list(st.morale),
            "traits": [[st.trait(c, a) for a in range(3)] for c in range(N)],
            "bonds": [st.bond(you, j) for j in range(N)],
            "best": best, "bestb": [st.bond(c, best[c]) for c in range(N)],
            "res": list(st.res), "kit": list(st.medkit),
            "open": opens, "act": act, "ending": st.ending,
            "updated": upd,
            "eng": EN.view(self.eng, self.local, p, st, log, you, minute),
            "v": sh.v, "start": sh.cal.start if sh.cal is not None else None,
        }


    def state_writer(self, you, last, minute):
        import json
        from binascii import b2a_base64
        sh = self.ship
        body = self.state_body(you, last, minute)
        rest = json.dumps(body)
        if probe:
            probe()
        body = None
        d = sh.st.day
        days = sh.days
        refs = [days.ref(x) for x in range(1, d + 1)]    # this version, even if a replay lands
        n = 0
        for x in range(1, d + 1):
            n += days.length(x)
        pre = b'{"story":"'
        tail = bytes('",' + rest[1:], "utf-8")
        rest = None
        b64 = (n + 2) // 3 * 4

        async def write(w):
            import lvweb
            w.write(lvweb.head(200, "application/json", len(pre) + b64 + len(tail)))
            w.write(pre)
            carry = b""
            days.readers += 1
            try:
                for i in range(len(refs)):
                    carry += days.load(refs[i])
                    k = len(carry) // 3 * 3
                    if k >= 384 or (i == len(refs) - 1 and k):
                        w.write(b2a_base64(carry[:k])[:-1])
                        carry = carry[k:]
                        await w.drain()
            finally:
                days.readers -= 1
            if carry:
                w.write(b2a_base64(carry)[:-1])
            w.write(tail)
            if probe:
                probe()
            await w.drain()
        return write
