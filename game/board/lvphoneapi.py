# Phone request dispatch/crew authentication, loaded for each non-state request.
from lv import ops as O
from lv import record as R
from lv import codes as K
from lv import engage as EN
from lv.state import N
from lv.clock import ticks_ms
from lvphone import _int

# ---- the API
def api(self, req):
    """-> (status, JSON-able) or (0, coroutine function writing the response)."""
    p = req.path
    sh = self.ship
    d = max(1, sh.day)
    auth = p in ("/api/login", "/api/me", "/api/logout")
    if not auth:
        if sh.st is None or sh.days is None:
            return 503, {"err": "The story is switched off on this ship (story: false)."}
        # The Ship light switch works during the countdown too (review 3 m1): POST /api/led
        # goes on to the sign-in check below like any other call.
        if sh.day < 1 and sh.cal is not None and p not in ("/api/crew", "/api/v") \
                and not (p == "/api/led" and req.method == "POST"):
            j = {"err": "The voyage hasn't launched yet.", "until": sh.cal.until()}
            you = self.who(req) if p == "/api/state" else None
            if you is not None:
                # A crew member signed in during the countdown (0.3.0 review 2 M1): what the
                # page's top bar and Settings need, nothing of the story. The page shows the
                # countdown and the gear; Ship software, the Ship light, codes and Reset work.
                j["launch"], j["start"] = sh.cal.date, sh.cal.start
                j["pre"] = {"you": you, "here": sh.me, "v": sh.v, "season": sh.pack.season,
                            "led": sh.led.enabled, "bat": sh.bat[:3] if sh.bat else None}
            return 409, j
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
            # No recall before launch (0.3.0 review 2 m2): a sign-in then isn't remembered
            # (see /api/login), and one remembered on an earlier flight day can't come back
            # through a countdown that a wrong first clock started. Recall is by IP and
            # browser, which a later device on the same DHCP lease can share.
            c = self.book.recall(req.phone(), d) if sh.day >= 1 else None
            if c is None:
                return 401, {"err": "signed out"}
            return 200, {"token": self.token(c), "crew": c, "first": False}
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
            if sh.day >= 1:
                # Before launch (0.3.0 review 2 m2) a sign-in is for Settings only: it isn't
                # remembered for /api/me (that would last the whole countdown and FD 01, on a
                # key another device can share), and it doesn't use up the first-time
                # briefing, which the page shows once the voyage starts.
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
    if p == "/api/led":
        import lvledcfg
        on = lvledcfg.toggle(self, bool(b.get("on")))
        return 200, {"ok": True, "led": on, "v": sh.v}
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

