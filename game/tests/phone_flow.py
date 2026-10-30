# What the phone page (web/app.html, web/engage.js) does against a ship, as requests:
# shared by tests/phone_check.py (fake sockets), tests/mp_sync_heap.py --phone (real
# sockets, heap) and tests/phone_e2e.py. Runs under CPython and MicroPython.
#
#   await session(req, ua, crew, pin, fail)   one phone's whole visit; fail(msg) collects errors
# `req(method, path, body_bytes_or_None, headers_dict) -> (status, headers, body)` is the
# transport (tcp() or fake() below).
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

PHONE_TIME = "1792843200000"


def parse(raw):
    i = raw.find(b"\r\n\r\n")
    head, body = raw[:i], raw[i + 4:]
    lines = str(head, "utf-8").split("\r\n")
    status = int(lines[0].split(" ")[1])
    h = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        h[k.strip().lower()] = v.strip()
    return status, h, body


def request_bytes(method, path, body, headers):
    out = "%s %s HTTP/1.1\r\nHost: 192.168.4.1\r\n" % (method, path)
    for k in headers:
        out += "%s: %s\r\n" % (k, headers[k])
    if body is not None:
        out += "Content-Type: application/json\r\nContent-Length: %d\r\n" % len(body)
    return bytes(out + "\r\n", "utf-8") + (body or b"")


def tcp(port, host="127.0.0.1"):
    async def req(method, path, body=None, headers=None):
        r, w = await asyncio.open_connection(host, port)
        try:
            w.write(request_bytes(method, path, body, headers or {}))
            await w.drain()
            raw, total = b"", None
            while True:
                b = await r.read(1024)
                if not b:
                    break
                raw += b
                if total is None and b"\r\n\r\n" in raw:
                    _, h, _ = parse(raw)
                    if "content-length" in h:
                        total = raw.find(b"\r\n\r\n") + 4 + int(h["content-length"])
                # A refused connection may reset after its complete 503 reply
                # because the server did not read the request. Do not wait for
                # EOF once HTTP framing proves the answer is complete.
                if total is not None and len(raw) >= total:
                    break
            if total is not None and len(raw) != total:
                raise EOFError("incomplete HTTP response: %d of %d bytes" % (len(raw), total))
            return parse(raw)
        finally:
            w.close()
            try:
                await w.wait_closed()
            except Exception:
                pass
    return req


class FakeReader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    async def readline(self):
        j = self.d.find(b"\n", self.i)
        j = len(self.d) if j < 0 else j + 1
        b = self.d[self.i:j]
        self.i = j
        return b

    async def readexactly(self, n):
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    async def read(self, n=-1):
        return await self.readexactly(len(self.d) - self.i if n < 0 else n)


class StuckReader:
    """A phone that connected and says nothing."""
    async def readline(self):
        await asyncio.sleep(3600)


class FakeWriter:
    def __init__(self, peer="10.0.0.2"):
        self.out = bytearray()
        self.peer = peer
        self.closed = False
        self.drains = 0

    def write(self, b):
        self.out += bytes(b)

    async def drain(self):
        self.drains += 1
        await asyncio.sleep(0)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def get_extra_info(self, k):
        return (self.peer, 51000) if k == "peername" else None


def fake(server, peer="10.0.0.2"):
    async def req(method, path, body=None, headers=None):
        w = FakeWriter(peer)
        await server.handle(FakeReader(request_bytes(method, path, body, headers or {})), w)
        if not w.closed:
            raise AssertionError("connection left open: " + path)
        return parse(bytes(w.out))
    return req


def js(b):
    return json.loads(str(b, "utf-8")) if b else {}


async def session(req, ua, crew, pin, fail, assets=None, wrong="0000", log=None):
    """One phone's visit, in the order the page makes its requests. Returns what it saw."""
    say = log or (lambda s: None)
    H = {"User-Agent": ua, "X-Phone-Time": PHONE_TIME, "X-Phone-TZ": "-300"}
    seen = {}

    def check(ok, msg):
        if not ok:
            fail(msg)
        return ok

    async def call(method, path, obj=None, tok=None):
        h = dict(H)
        if tok:
            h["X-Crew-Token"] = tok
        s, hd, b = await req(method, path, None if obj is None else bytes(json.dumps(obj), "utf-8"), h)
        return s, hd, b

    # The captive sheet probes, then loads the page and its two data files.
    s, hd, _ = await call("GET", "/hotspot-detect.html")
    check(s == 302 and hd.get("location", "").startswith("http://"), "probe: want 302 to the board, got %d" % s)
    # Then the home-screen manifest and icon (Chrome reads the manifest on load; iOS reads
    # the touch icon when you add the game to your home screen).
    for path, name, ct in (("/", "app.html.gz", "text/html"), ("/text.json", "text.json.gz", "application/json"),
                           ("/engage.json", "engage.json.gz", "application/json"),
                           ("/app.webmanifest", "app.webmanifest.gz", "application/manifest+json"),
                           ("/icon.png", "icon.png.gz", "image/png"), ("/apple-touch-icon.png", "icon.png.gz", "image/png")):
        s, hd, b = await call("GET", path)
        check(s == 200 and hd.get("content-encoding") == "gzip", "%s: status %d / encoding %s" % (path, s, hd.get("content-encoding")))
        check(hd.get("content-type", "").startswith(ct), "%s: content type %s, want %s" % (path, hd.get("content-type"), ct))
        check(int(hd.get("content-length", -1)) == len(b), "%s: length header %s, body %d" % (path, hd.get("content-length"), len(b)))
        if assets is not None:
            check(b == assets[name], "%s: not the bytes of %s" % (path, name))
        seen[path] = len(b)
    s, _, b = await call("GET", "/api/crew?day=99")
    crew_set = js(b).get("set")
    check(s == 200 and crew_set and crew_set[crew], "crew: %d %s" % (s, crew_set))
    s, _, b = await call("GET", "/api/me")
    check(s == 401, "me before sign-in: %d" % s)
    s, _, b = await call("POST", "/api/login", {"crew": crew, "pin": wrong})
    check(s == 403 and js(b).get("left") == 4, "wrong code: %d %s" % (s, b))
    s, _, b = await call("POST", "/api/login", {"crew": crew, "pin": pin})
    j = js(b)
    check(s == 200 and j.get("crew") == crew and j.get("token"), "login: %d %s" % (s, b))
    seen["first"] = j.get("first")
    tok = j.get("token")
    s, _, b = await call("GET", "/api/me")
    j = js(b)
    check(s == 200 and j.get("crew") == crew and j.get("first") is False, "me (remembered): %d %s" % (s, b))
    tok = j.get("token") or tok
    s, hd, b = await call("GET", "/ws")
    check(s == 404, "ws: want 404 (poll instead), got %d" % s)
    s, hd, b = await call("GET", "/api/state", tok=tok)
    check(s == 200 and int(hd.get("content-length", -1)) == len(b), "state: %d, length %s vs %d" % (s, hd.get("content-length"), len(b)))
    S = js(b)
    seen["state"] = S
    seen["state_bytes"] = len(b)
    check(S.get("you") == crew, "state: you %s" % S.get("you"))
    v0 = S.get("v")
    # Vote on the first open vote, answer a dilemma if this crew member has one.
    for o in S.get("open", []):
        if o["type"] in (3, 5) and "vote" not in seen:
            opt = 1 if len(o["tally"]) > 1 and o.get("mine") != 1 else 0
            s, _, b = await call("POST", "/api/vote", {"card": o["card"], "opt": opt}, tok)
            check(s == 200 and js(b).get("ok"), "vote: %d %s" % (s, b))
            seen["vote"] = (o["card"], opt)
        if o["type"] == 4 and "answer" not in seen:
            s, _, b = await call("POST", "/api/answer", {"card": o["card"], "opt": 0}, tok)
            check(s == 200, "answer: %d %s" % (s, b))
            seen["answer"] = (o["card"], 0)
    s, _, b = await call("POST", "/api/act", {"act": 1, "param": 0, "tgt": 0}, tok)
    check(s == 200, "act: %d %s" % (s, b))
    s, _, b = await call("POST", "/api/open", {"day": S.get("day")}, tok)
    j = js(b)
    check(s == 200 and j.get("day") == S.get("day") and "tier" in j and "item" in j, "open: %d %s" % (s, b))
    # Gifts: one a day. Try items until one is giftable, then the second must be refused.
    to = 0 if crew != 0 else 1
    while to < 8 and (to == crew or S["cond"][to] == 2):
        to += 1
    gave = None
    for item in range(16):
        s, _, b = await call("POST", "/api/gift", {"item": item, "to": to, "mode": 0}, tok)
        if s == 200 or s == 409:
            gave = (item, s, js(b))
            break
    check(gave is not None, "gift: no item accepted")
    if gave:
        s, _, b = await call("POST", "/api/gift", {"item": gave[0], "to": to, "mode": 0}, tok)
        check(s == 409 and "One gift a day" in js(b).get("err", ""), "second gift: %d %s" % (s, b))
        seen["gift"] = gave
    s, _, b = await call("POST", "/api/vote", {"card": "x"}, tok)
    check(s == 400, "bad vote: %d" % s)
    s, _, b = await call("GET", "/api/v")
    v1 = js(b).get("v")
    check(s == 200 and v1 is not None and v1 > v0, "v did not move: %s -> %s" % (v0, v1))
    s, _, b = await call("GET", "/api/state?last=5", tok=tok)
    S2 = js(b)
    seen["state2"] = S2
    check(s == 200 and S2.get("last") == 5, "state again: %d last %s" % (s, S2.get("last")))
    check(S2.get("act") == [1, 0, 0], "act not in state: %s" % S2.get("act"))
    if "vote" in seen:
        o = [x for x in S2["open"] if x["card"] == seen["vote"][0]]
        check(o and o[0]["mine"] == seen["vote"][1], "vote not in state: %s" % o)
    check(S2["eng"]["drops"][S2["day"] - 1][3] in (1, True), "drop not opened: %s" % S2["eng"]["drops"][-1:])
    s, _, b = await call("POST", "/api/logout", {}, tok)
    check(s == 200, "logout: %d" % s)
    s, _, b = await call("GET", "/api/state", tok=tok)
    check(s == 401, "state after logout: %d" % s)
    s, _, b = await call("GET", "/api/me")
    check(s == 401, "me after logout: %d" % s)
    say("phone %s: crew %d, state %d B, v %s -> %s" % (ua[-6:], crew, seen["state_bytes"], v0, v1))
    return seen
