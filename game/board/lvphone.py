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
#   POST /api/led     {on} -> {ok, led, v}: the Ship light (LED notifier, lvled.py; lvledcfg.toggle), kept in ship.json
#   POST /api/open    {day} -> {ok, day, tier, item}       (daily drop)
#   POST /api/gift    {item, to, mode} -> {ok, v} | 409 {err}
#   POST /api/act     {act, param, tgt}   POST /api/vote {card, opt}   POST /api/answer {card, opt}
#
# The board has one flight day (ship.day: from the launch date and the phones' clocks,
# board/lvcal.py, or ship.json "day" on the bench); the page's ?day= is ignored. Before
# launch /api/crew (with the countdown: {day: 0, launch, until, start}), /api/v and
# sign-in/recovery/sign-out answer; story routes are 409. Authentication also works
# with the story switched off, so a crew token can correct a bad first phone clock
# and authorize normal OTA. Taps are signed records for today authored by whoever signed
# in (lvship.Ship.tap), so they sync to the other ships like any record.
# Crew codes come from data/crew.json (the updater writes it); without it nobody can sign in.
# What phones opened and saw is kept in /data/local.bin.
from lv import codes as K
from lv import engage as EN
from lv.state import N

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
        import lvphoneinit
        import lvship
        try:
            lvphoneinit.setup(self, ship, root, say)
        finally:
            lvship.drop("lvphoneinit")

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

    # Dispatch code isn't retained during an upload or a streamed response.
    def api(self, req):
        if req.path == "/api/state" and req.method == "GET":
            sh = self.ship
            if sh.st is None or sh.days is None:
                return 503, {"err": "The story is switched off on this ship (story: false)."}
            if sh.day < 1 and sh.cal is not None:
                return 409, {"err": "The voyage hasn't launched yet.", "until": sh.cal.until()}
            you = self.who(req)
            if you is None:
                return 401, {"err": "signed out"}
            sh._led("seen")
            return 0, self.state_writer(you, _int(req.q.get("last"), max(0, max(1, sh.day) - 3)), sh.clock.minute())
        import lvphoneapi
        import lvship
        try:
            return lvphoneapi.api(self, req)
        finally:
            lvship.drop("lvphoneapi")

    def gift(self, you, day, item, to, mode):
        import lvphoneapi
        import lvship
        try:
            return lvphoneapi.gift(self, you, day, item, to, mode)
        finally:
            lvship.drop("lvphoneapi")

    # ---- /api/state (loaded only while building/streaming the response)
    def state_body(self, you, last, minute):
        import lvstateapi
        import lvship
        try:
            return lvstateapi.state_body(self, you, last, minute)
        finally:
            lvship.drop("lvstateapi")

    def state_writer(self, you, last, minute):
        import lvstateapi
        import lvship
        try:
            return lvstateapi.state_writer(self, you, last, minute)
        finally:
            lvship.drop("lvstateapi")
