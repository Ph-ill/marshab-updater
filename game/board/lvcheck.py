# Trial HTTP self-checks, loaded only while checking a new installation.
import lvship

class Sink:
    # serves()'s stand-in for a phone's connection, both ends: reads out the raw request
    # it was given (as a socket's stream would), keeps the answer's status line, drops the rest.
    def __init__(self, req):
        self.b = req
        self.st = None

    async def readline(self):
        i = self.b.find(b"\n") + 1 or len(self.b)
        r, self.b = self.b[:i], self.b[i:]
        return r

    async def readexactly(self, n):
        r, self.b = self.b[:n], self.b[n:]
        return r

    def write(self, d):
        if self.st is None:
            self.st = bytes(d[:12])

    async def drain(self):
        await lvship.sleep_ms(0)    # the page streams in CHUNKs: let the phones in between

    def get_extra_info(self, k):
        return ("127.0.0.1", 0)

    def close(self):
        pass

    async def wait_closed(self):
        pass


# serves()'s requests and the status each must get: the page, the crew list and the update
# status (2xx), and an update write with no sign-in (lvotap's 401: put, not apply or cancel,
# so a sign-in check gone wrong still can't act on anything). The put carries a whole piece
# (lvota.CHUNK, 1024 B: lvweb.MAX_BODY must take it) and is the last probe, PUT: it is sent
# even when a phone has had a 2xx already, so the upload's route, its body limit and lvotap
# itself are shown to work before a trial is kept (0.3.0 fix review FR1 m1).
PROBES = (("GET", "/", b"2"), ("GET", "/api/crew", b"2"), ("GET", "/api/ota", b"2"),
          ("POST", "/api/ota/put", b"401"))
PUT = PROBES[3:]


def essid_ok(ap, want):
    """Is the hotspot up under this ship's own name? Up (active) is required. The name read
    back (ap.config("essid"), str or bytes) must match when the firmware gives one; when it
    gives nothing, or can't read it back at all, active is taken as enough (a readback that
    doesn't work on this firmware must not fail every update's check)."""
    if not ap.active():
        return False
    try:
        e = ap.config("essid")
    except Exception:
        return True
    if isinstance(e, (bytes, bytearray)):
        e = str(e, "utf-8")
    return not e or str(e) == want


async def serves(web, probes=PROBES):
    """Does this set serve a phone? The hotspot is up as this ship's own SSID, the web
    server's accept loop is still running, and PROBES, as raw bytes through Server.handle
    (lvweb's request parser, the busy count, route, head), each get their status with no
    error said on the way. The counts a phone's visit moves (the 2xx count, served, the
    ship's hits) lose exactly what these requests added, so a phone's own request in the
    meantime still counts (the page streams, and lets other requests in as it goes). (A
    real socket round trip would be stronger; lwIP loopback on the Pico W is unconfirmed,
    so the listening socket is shown by its accept task instead.)"""
    sh = web.ship
    ap = getattr(web, "ap", None)
    if ap is not None:
        try:
            c = sh.cfg
            if not essid_ok(ap, "%s%d" % (c["ssid_prefix"], c["ship_id"])):
                print("ota: self-check: the hotspot isn't up")
                return False
        except Exception as e:
            print("ota: self-check hotspot %r" % (e,))
            return False
    t = getattr(getattr(web, "srv", None), "task", None)
    if t is not None and t.done():
        print("ota: self-check: the web server stopped")
        return False
    hits = oks = done = 0
    say = getattr(web, "say", print)
    err = []

    def heard(m):
        err.append(m)
        say(m)
    try:
        web.say = heard                 # Server.handle says what a request raised
        for m, p, want in probes:
            n = 1024 if m == "POST" else 0
            w = Sink(("%s %s HTTP/1.0\r\nHost: self\r\nContent-Length: %d\r\n\r\n" % (m, p, n)).encode()
                     + bytes(n))
            del err[:]
            n, d, h = web.ok2xx, web.served, sh.http_hits
            try:
                await web.handle(w, w)
            finally:
                # what this request added (at most 1 each: more is a phone's, and stays)
                oks += min(1, max(0, web.ok2xx - n))
                done += min(1, max(0, web.served - d))
                hits += min(1, max(0, sh.http_hits - h))
            st = w.st[9:9 + len(want)] if w.st else None
            if st != want or err:
                print("ota: %s %s answered %r" % (m, p, w.st))
                return False
        return True
    except Exception as e:
        print("ota: self-check %r" % (e,))
        return False
    finally:
        web.say = say
        web.ok2xx -= oks
        web.served -= done
        sh.http_hits -= hits


