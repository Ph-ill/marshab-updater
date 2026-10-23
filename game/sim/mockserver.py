#!/usr/bin/env python3
"""Mock Pico for the phone UI. Serves the real gzipped page and an API backed by the
real engine and the simulated season, so the prototype shows engine-made story.

  python3 web/build.py && python3 sim/mockserver.py [--port 8042] [--day 23] [codes=1234,,5555,...]

Open http://localhost:8042/ (add ?day=8 to look at another flight day; mock only).

What it models: this ship is the player's own Pico. It knows only what has reached
it by gossip (sim/season.py's "gossip" delivery), so late records replay days and the
page can mark "log updated". Your own taps become real signed records that take
effect tomorrow. The simulated player for your seat is silenced from today on.
Nothing is stored on the phone: the session token lives in page memory.

Engagement (lv/engage.py): every request may carry the phone's clock (X-Phone-Time,
X-Phone-TZ), which the mock learns like a ship would; add &now=HH:MM to pretend it's
another time of day. Drops opened and "seen at last visit" are kept per crew in memory.

Crew codes work as on the board (lv/codes.py): set up front (here every code is 1234
unless codes= lists them; an empty entry means "not set up"), five wrong tries lock that
name for five minutes, and a phone that signed in is remembered, by IP and User-Agent,
for the rest of the flight day it signed in on (the ?day=N it used).
"""
import base64
import gzip
import hashlib
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from lv import ops as O                       # noqa: E402
from lv import record as R                    # noqa: E402
from lv import codes as K                     # noqa: E402
from lv import engage as EN                   # noqa: E402
from lv.clock import Clock                    # noqa: E402
from lv.engine import Engine                  # noqa: E402
from lv.pack import load as load_pack         # noqa: E402
from lv.state import State, N                 # noqa: E402
from sim.season import (FLEET_KEY, Ship, deliver, reference_season)  # noqa: E402

BUILD = os.path.join(ROOT, "build")


def visible(out):
    """The entries the page shows (routine chores are folded into one line)."""
    keep = bytearray()
    for i in range(0, len(out), 8):
        e = out[i:i + 8]
        if not (e[1] == O.O_ACT and e[6] == 1 and e[4] != 0):
            keep += e
    return bytes(keep)


class ViewShip(Ship):
    """A Ship that keeps every day's story and notes days rewritten by a replay."""

    def __init__(self, idx, pack):
        super().__init__(idx, pack)
        self.days = {}
        self.updated = {}
        self.now = 0

    def tick_to(self, day):
        while self.st.day < day:
            Engine(self.p, self.st, self.log).tick()
            d = self.st.day
            new = bytes(self.st.out)
            old = self.days.get(d)
            # Flag a day only if a later visit would read something different:
            # rewritten after that day ended, and a line the page shows changed.
            if old is not None and self.now > d and visible(old) != visible(new):
                self.updated[d] = self.now
            self.days[d] = new
            if d % self.SNAP_EVERY == 0:
                self.snaps[d] = self.st.dump()


class Game:
    def __init__(self, day):
        self.pack = load_pack(os.path.join(BUILD, "pack.bin"))
        self.text = json.load(open(os.path.join(BUILD, "text.json"), encoding="utf-8"))
        _, self.authored, _, _ = reference_season(self.pack, seed=1)
        self.day = day
        self.book = K.CodeBook(K.make_config(["1234"] * N, b"mock-fleet-salt!"))
        self.tokens = {}          # token -> crew
        self.mine = []            # (day, record) tapped on this mock
        self.seq = [1000] * N
        self.cache = {}
        self.lock = threading.RLock()   # gift() checks, then taps
        self.changed = threading.Condition()
        self.version = 0
        self.etable = EN.load_table(os.path.join(BUILD, "engage.bin"))
        self.eng = EN.Engage(self.etable, self.pack.voyage_key, self.pack.season)
        self.etext = json.load(open(os.path.join(BUILD, "engage.json"), encoding="utf-8"))
        self.local = EN.Local(self.pack.season)
        self.clock = Clock()

    # -- the world as one ship sees it ------------------------------------------------
    def ship_view(self, you, day):
        key = (you, day, len(self.mine))
        if key not in self.cache:
            recs = [(d, r) for d, r in self.authored if not (R.ship(r) == you and d >= day)]
            recs += [(d, r) for d, r in self.mine if R.ship(r) == you and d <= day]
            recs.sort(key=lambda x: x[0])
            ships = deliver(self.pack, recs, "gossip", upto=day, cls=ViewShip)
            self.cache[key] = ships[you]
        return self.cache[key]

    def state(self, you, day, last, minute=None):
        sh = self.ship_view(you, day)
        st, p = sh.st, self.pack
        eng = Engine(p, st, sh.log)
        opens = []
        for it in st.pend:
            ctype, idx, opened, close = it[0], it[1], it[2], it[3]
            A, B = it[4], it[5]
            if ctype == O.DILEMMA and A != you:
                continue
            card = p.cards[idx]
            kind = R.DILEMMA if ctype == O.DILEMMA else R.VOTE
            got = sh.log.answers(kind, idx, opened, close)
            tally = [0] * card.nopt
            mine = None
            for s, o in got:
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
        for r in sh.log.all_records():
            if R.kind(r) == R.ACTION and R.ship(r) == you and R.day(r) == day:
                act = [r[5], r[6], r[7]]
        story = b"".join(sh.days.get(d, b"") for d in range(1, day + 1))
        return {
            "day": day, "season": p.season, "you": you, "here": you, "last": last,
            "loc": list(st.loc), "cond": list(st.cond), "morale": list(st.morale),
            "traits": [[st.trait(c, a) for a in range(3)] for c in range(N)],
            "bonds": [st.bond(you, j) for j in range(N)],
            "best": [max((j for j in range(N) if j != c), key=lambda j: st.bond(c, j)) for c in range(N)],
            "res": list(st.res), "kit": list(st.medkit),
            "open": opens, "act": act, "ending": st.ending,
            "story": base64.b64encode(story).decode(),
            "updated": {str(d): a for d, a in sorted(sh.updated.items())},
            "eng": EN.view(self.eng, self.local, p, st, sh.log, you, minute),
        }

    def gift(self, you, day, item, to, mode):
        """The board's rules for a gift tap. Returns an error string or None."""
        sh = self.ship_view(you, day)
        flags = self.etable.gift_flags
        if not (0 <= to < N) or to == you or not (0 <= item < len(flags)) or mode not in (0, 1, 2):
            return "bad request"
        if sh.st.cond[to] == O.COND_HOME:
            return "They're home now."
        _, _, asks, (gave, asked) = EN.gifts(sh.log, you, day, self.etable.ask_days)
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
        self.tap(you, day, R.GIFT, item, to, mode)
        return None

    def tap(self, you, day, kind, a, b=0, c=0):
        with self.lock:
            self.seq[you] += 1
            rec = R.encode(FLEET_KEY, kind, you, 1, self.seq[you], day, a, b, c)
            self.mine.append((day, rec))
        self.bump()

    def token(self, crew):
        t = secrets.token_hex(8)
        self.tokens[t] = crew
        return t

    def bump(self):
        with self.changed:
            self.version += 1
            self.changed.notify_all()


G = None


def ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()


def ws_frame(text):
    b = text.encode()
    n = len(b)
    head = bytes([0x81, n]) if n < 126 else bytes([0x81, 126]) + struct.pack(">H", n)
    return head + b


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json", gz=False, extra=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def who(self):
        return G.tokens.get(self.headers.get("X-Crew-Token", ""))

    def phone(self):
        return "%s|%s" % (self.client_address[0], self.headers.get("User-Agent", ""))

    def minute(self, q):
        # The local minute of the day: ?now=HH:MM (mock only), else the learned clock.
        G.clock.learn_headers(lambda k: self.headers.get(k))
        v = q.get("now", [None])[0]
        if v:
            try:
                h, m = v.split(":")
                return (int(h) * 60 + int(m)) % 1440
            except ValueError:
                pass
        return G.clock.minute()

    def day(self, q):
        try:
            return max(1, min(G.pack.season, int(q.get("day", [G.day])[0])))
        except ValueError:
            return G.day

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self.send(200, open(os.path.join(BUILD, "app.html.gz"), "rb").read(),
                             "text/html; charset=utf-8", gz=True)
        if u.path == "/text.json":
            return self.send(200, gzip.compress(json.dumps(G.text, ensure_ascii=False).encode()),
                             gz=True)
        if u.path == "/engage.json":
            return self.send(200, gzip.compress(json.dumps(G.etext, ensure_ascii=False).encode()),
                             gz=True)
        if u.path == "/api/crew":
            return self.send(200, {"set": [G.book.is_set(c) for c in range(N)], "day": self.day(q)})
        if u.path == "/api/me":     # remembered phone: sign straight back in
            with G.lock:
                c = G.book.recall(self.phone(), self.day(q))
                if c is None:
                    return self.send(401, {"err": "signed out"})
                return self.send(200, {"token": G.token(c), "crew": c, "first": False})
        if u.path == "/api/v":
            return self.send(200, {"v": G.version})
        if u.path == "/api/state":
            you = self.who()
            if you is None:
                return self.send(401, {"err": "signed out"})
            d = self.day(q)
            last = int(q.get("last", [max(0, d - 3)])[0])
            minute = self.minute(q)
            with G.lock:
                body = G.state(you, d, last, minute)
            body["v"] = G.version
            return self.send(200, body)
        if u.path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            return self.websocket()
        # Captive portal probes (iOS, Android, Windows): send them to the page.
        return self.send(302, b"", "text/plain", extra=[("Location", "/")])

    def websocket(self):
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept(self.headers["Sec-WebSocket-Key"]))
        self.end_headers()
        self.close_connection = True
        try:
            seen = -1
            while True:
                with G.changed:
                    if seen == G.version:
                        G.changed.wait(25)
                    v = G.version
                self.wfile.write(ws_frame(json.dumps({"v": v})))
                self.wfile.flush()
                seen = v
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        b = self.body()
        if u.path == "/api/login":
            try:
                c, pin = int(b.get("crew")), str(b.get("pin", ""))
            except (TypeError, ValueError):
                return self.send(400, {"err": "bad request"})
            with G.lock:
                st, v = G.book.check(c, pin, int(time.monotonic() * 1000))
                if st == K.OK:
                    first = not G.book.seen[c]
                    G.book.seen[c] = True
                    G.book.remember(self.phone(), c, self.day(q))
                    return self.send(200, {"token": G.token(c), "crew": c, "first": first})
            if st == K.WRONG:
                return self.send(403, {"err": "That code doesn't match.", "left": v})
            if st == K.LOCKED:
                return self.send(429, {"err": "Too many tries.", "wait": v})
            if st == K.NO_CODE:
                return self.send(409, {"err": "No code set up for this name yet."})
            return self.send(400, {"err": "bad request"})
        if u.path == "/api/logout":
            with G.lock:
                G.book.forget(self.phone())
                G.tokens.pop(self.headers.get("X-Crew-Token", ""), None)
            return self.send(200, {"ok": True})
        you = self.who()
        if you is None:
            return self.send(401, {"err": "signed out"})
        d = self.day(q)
        self.minute(q)
        try:
            if u.path == "/api/open":
                x = int(b.get("day", d))
                if not 1 <= x <= d:
                    return self.send(400, {"err": "bad request"})
                with G.lock:
                    G.local.open(you, x)
                tier, item = G.eng.drop(you, x)
                return self.send(200, {"ok": True, "day": x, "tier": tier, "item": item})
            if u.path == "/api/gift":
                with G.lock:
                    err = G.gift(you, d, int(b["item"]), int(b["to"]), int(b.get("mode", 0)))
                if err:
                    return self.send(409 if err != "bad request" else 400, {"err": err})
                return self.send(200, {"ok": True, "v": G.version})
            if u.path == "/api/act":
                G.tap(you, d, R.ACTION, int(b["act"]), int(b.get("param", 0)), int(b.get("tgt", 0)))
            elif u.path == "/api/vote":
                G.tap(you, d, R.VOTE, int(b["card"]), int(b["opt"]))
            elif u.path == "/api/answer":
                G.tap(you, d, R.DILEMMA, int(b["card"]), int(b["opt"]))
            else:
                return self.send(404, {"err": "no such thing"})
        except (KeyError, TypeError, ValueError):
            return self.send(400, {"err": "bad request"})
        return self.send(200, {"ok": True, "v": G.version})


def main(argv):
    global G
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8042
    day = int(argv[argv.index("--day") + 1]) if "--day" in argv else 23
    G = Game(day)
    for a in argv:   # codes=1234,,5555,... sets the crew codes; an empty one is "not set up"
        if a.startswith("codes="):
            got = [k or None for k in a[6:].split(",")]
            G.book = K.CodeBook(K.make_config((got + [None] * N)[:N], b"mock-fleet-salt!"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    print("mock Pico on http://localhost:%d/  (flight day %d)" % (port, day), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
