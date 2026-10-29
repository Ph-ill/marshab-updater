# The board's web server on the hotspot: the captive portal (DNS answers every name with
# the board, unknown pages redirect to it), the phone page streamed from flash, and the
# bench's status pages. The game's JSON API lives in lvphone.py and is loaded on the
# first phone request, so a board nobody has joined yet doesn't pay for it.
#
#   GET  /, /index.html       www/app.html.gz (Content-Encoding: gzip), streamed 512 B at a time
#   GET  /text.json, /engage.json   www/<name>.gz, streamed
#   GET  /status              one STAT line (text)          GET /api/sync   status JSON
#   GET  /api/gift?to=N       bench gift from this ship's crew member (POST /api/gift is the game's)
#   /api/...                  lvphone.Phone (the contract sim/mockserver.py serves)
#   GET  /ws                  404: the page falls back to polling /api/v every 15 s
#   anything else             302 to http://<board>/ (phones' captive-portal probes)
#
# One request per connection (HTTP/1.0, Connection: close). Slow or silent phones time out
# (READ_MS) and at most MAX_CONN requests are served at once; the rest get a quick 503, so
# a phone left idle never holds the board up.
import gc

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

try:
    sleep_ms = asyncio.sleep_ms
except AttributeError:     # CPython (the tests)
    def sleep_ms(ms):
        return asyncio.sleep(ms / 1000)

MAX_CONN = 4
READ_MS = 5000
MAX_BODY = 512
CHUNK = 512
probe = None        # tests: called at the server's busiest points (tests/mp_sync_heap.py)
KEEP = ("content-length", "user-agent", "x-crew-token", "x-phone-time", "x-phone-tz")
STATUS = {200: "OK", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
          404: "Not Found", 409: "Conflict", 413: "Too Large", 429: "Too Many Requests",
          500: "Error", 503: "Busy"}
STATIC = {"/": ("www/app.html.gz", "text/html; charset=utf-8"),
          "/index.html": ("www/app.html.gz", "text/html; charset=utf-8"),
          "/text.json": ("www/text.json.gz", "application/json"),
          "/engage.json": ("www/engage.json.gz", "application/json")}


class Req:
    __slots__ = ("method", "path", "q", "hdr", "body", "peer")

    def header(self, k):
        return self.hdr.get(k)

    def phone(self):
        # What stays put for a day on the hotspot: the phone's address plus its browser.
        return "%s|%s" % (self.peer, self.hdr.get("user-agent", ""))


def parse_query(s):
    q = {}
    for kv in s.split("&"):
        if kv:
            k, _, v = kv.partition("=")
            q[k] = v
    return q


def peer_of(writer):
    try:
        a = writer.get_extra_info("peername")
    except Exception:
        return "?"
    if isinstance(a, tuple):
        return str(a[0])
    if isinstance(a, (bytes, bytearray)) and len(a) >= 8:   # unix port: a raw sockaddr
        return "%d.%d.%d.%d" % (a[4], a[5], a[6], a[7])
    return str(a)


async def read_req(reader):
    line = await reader.readline()
    parts = str(line, "utf-8").split(" ")
    if len(parts) < 2:
        return None
    r = Req()
    r.method = parts[0]
    path, _, query = parts[1].partition("?")
    r.path = path
    r.q = parse_query(query)
    r.hdr = {}
    for _ in range(40):
        h = await reader.readline()
        if not h or h in (b"\r\n", b"\n"):
            break
        i = h.find(b":")
        if i > 0:
            k = str(h[:i].strip().lower(), "utf-8")
            if k in KEEP:
                r.hdr[k] = str(h[i + 1:].strip(), "utf-8")
    r.body = b""
    n = int(r.hdr.get("content-length", "0") or 0)
    if n > MAX_BODY:
        raise ValueError("body too large")
    if n:
        r.body = await reader.readexactly(n)
    return r


def head(code, ctype, length=None, gz=False, extra=""):
    return bytes("HTTP/1.0 %d %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\n%s%s%sConnection: close\r\n\r\n" % (
        code, STATUS.get(code, "OK"), ctype, "Content-Encoding: gzip\r\n" if gz else "",
        "" if length is None else "Content-Length: %d\r\n" % length, extra), "utf-8")


async def send(writer, code, body=b"", ctype="application/json", extra=""):
    if isinstance(body, str):
        body = bytes(body, "utf-8")
    writer.write(head(code, ctype, len(body), extra=extra))
    if body:
        writer.write(body)
    if probe:
        probe()
    await writer.drain()


async def send_json(writer, code, obj):
    import json
    await send(writer, code, json.dumps(obj))


async def send_file(writer, path, ctype, gz=True):
    """Stream a file from flash: one CHUNK buffer, never the whole file in RAM."""
    import os
    try:
        n = os.stat(path)[6]
        f = open(path, "rb")
    except OSError:
        return await send(writer, 404, '{"err":"missing %s: install the game files with the updater"}' % path)
    try:
        writer.write(head(200, ctype, n, gz))
        buf = bytearray(CHUNK)
        mv = memoryview(buf)
        while True:
            k = f.readinto(buf)
            if not k:
                break
            writer.write(mv[:k])
            if probe:
                probe()
            await writer.drain()
    finally:
        f.close()


class Server:
    def __init__(self, ship, root="", ip="192.168.4.1", say=print):
        self.ship = ship
        self.root = root
        self.ip = ip
        self.say = say
        self.phone = None       # lvphone.Phone, made on the first API request
        ship.web = self         # the LED notifier waits while a request is in progress
        self.busy = 0
        self.served = 0
        self.refused = 0

    def get_phone(self):
        if self.phone is None:
            import lvphone
            self.phone = lvphone.Phone(self.ship, self.root, self.say)
        return self.phone

    async def handle(self, reader, writer):
        self.ship.http_hits += 1
        if self.busy >= MAX_CONN:
            self.refused += 1
            try:
                await send(writer, 503, '{"err":"busy, try again"}', extra="Retry-After: 1\r\n")
            except Exception:
                pass
            return await self._close(writer)
        self.busy += 1
        try:
            try:
                req = await asyncio.wait_for_ms(read_req(reader), READ_MS) if hasattr(asyncio, "wait_for_ms") \
                    else await asyncio.wait_for(read_req(reader), READ_MS / 1000)
            except ValueError:
                await send(writer, 413, '{"err":"too large"}')
                req = None
            if req is not None:
                req.peer = peer_of(writer)
                await self.route(req, writer)
                self.served += 1
        except Exception as e:      # one bad request (or a phone walking away) never stops the server
            self.say("http: %r" % (e,))
        finally:
            self.busy -= 1
            await self._close(writer)
            gc.collect()

    async def _close(self, writer):
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    async def route(self, req, w):
        p = req.path
        sh = self.ship
        if sh.clock.learn_headers(req.header):  # any phone request carries its clock
            sh.day_check()                       # with a launch date: today's flight day
        if req.method == "GET":
            s = STATIC.get(p)
            if s:
                return await send_file(w, self.root + s[0], s[1])
            if p == "/status":
                return await send(w, 200, sh.stat_line() + "\n", "text/plain")
            if p == "/api/sync":
                return await send_json(w, 200, sh.status())
            if p == "/api/gift" and "to" in req.q:      # bench: a gift from this ship's seat
                try:
                    r = sh.gift(int(req.q["to"]))
                    return await send_json(w, 200, {"gift": r.hex()})
                except ValueError as e:
                    return await send_json(w, 400, {"error": str(e)})
            if p == "/ws":
                return await send(w, 404, '{"err":"no websocket here, poll /api/v"}')
        if p.startswith("/api/"):
            code, obj = self.get_phone().api(req)
            if code == 0:          # the phone module streams this one itself
                return await obj(w)
            return await send_json(w, code, obj)
        # Captive-portal probes (iOS, Android, Windows) and stray links: to the game page.
        return await send(w, 302, "", "text/plain", "Location: http://%s/\r\n" % self.ip)

    async def tick(self):
        # Housekeeping for the phone side (saves what phones opened, at most once a minute).
        while True:
            await sleep_ms(60000)
            if self.phone is not None:
                self.phone.save()


# ---- DNS: every name is this board (the captive portal) ---------------------------------
def dns_answer(q, ip):
    """Answer a DNS query packet: A queries get `ip`, anything else (AAAA, HTTPS...) gets
    an empty answer. Returns bytes, or None for packets that aren't a plain query."""
    if len(q) < 17 or q[2] & 0x80 or q[4:6] != b"\x00\x01":
        return None
    i = 12
    while i < len(q) and q[i]:
        if q[i] & 0xC0:
            return None
        i += q[i] + 1
    i += 1
    if i + 4 > len(q):
        return None
    qtype = q[i] << 8 | q[i + 1]
    end = i + 4
    a = qtype == 1
    hdr = q[:2] + b"\x81\x80\x00\x01\x00" + (b"\x01" if a else b"\x00") + b"\x00\x00\x00\x00"
    body = hdr + q[12:end]
    if a:
        body += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + bytes(int(x) for x in ip.split("."))
    return body


async def dns(ip, port=53, say=print, stop=None):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    s.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
    s.setblocking(False)
    say("dns: every name -> %s" % ip)
    n = 0
    try:
        while stop is None or not stop():
            try:
                q, addr = s.recvfrom(512)
            except OSError:
                await sleep_ms(40)
                continue
            r = dns_answer(q, ip)
            if r:
                try:
                    s.sendto(r, addr)
                    n += 1
                except OSError:
                    pass
    finally:
        s.close()
    return n
