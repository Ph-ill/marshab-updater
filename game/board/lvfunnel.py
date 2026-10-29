# The home-screen funnel, the ship's side (web/funnel.js is the page's; docs/OTA.md, "The
# home-screen funnel"). The page asks GET /api/hello?ctx=<where it runs>[&m=icon] before the game
# loads, and the ship answers what it has seen THIS phone do:
#   {"installed": 0|1, "tab": 0|1, "sheet": 0|1, "key": "ip"|"mac"}
# installed: the phone opened the game from its home-screen icon (iOS: running standalone;
#            Android: the address carries the icon's ?src=icon marker). Only that marks it.
# tab:       the phone opened the page in a browser tab.
# sheet:     the phone showed the page in a captive-portal pop-up (iOS sheet, Android
#            sign-in window), which only sends the player to the real browser.
# main.py imports this per request and drops it after (as lvota), so it holds no RAM
# between requests; nothing here is frozen (it ships over the air as lvfunnel.mpy).
#
# Which phone: by client address for now. The hotspot leases an address for 24 hours, so a
# record keyed by address is trusted for less than that (FRESH): after it, another phone
# may hold the address. MAC mode is the hook below: firmware that can list its DHCP leases
# (ap.status("leases") -> [(mac, ip), ...], not stock MicroPython 1.29 on the Pico W) keys
# phones by MAC instead, and those records don't go stale. iOS and Android give each Wi-Fi
# network their own private MAC, which stays put for that network, so MAC mode still
# tells phones apart on one ship.
#
# The store: /data/funnel.bin, N records of REC bytes:
#   key[6]   b"ip" + the IPv4 address, or the MAC
#   flags    INSTALLED 1, TAB 2, SHEET 4, MAC 8
#   stamp    when the ship last heard from the phone: epoch hours // 4, mod 256 (0..255)
# 32 phones in 256 bytes, written whole (funnel.bin.new, then a rename) and only when a
# record changes. A full store gives the stalest record that isn't installed to a new phone.
# "Reset this ship" (lvcode.py RESET) deletes it.
N = 32
REC = 8
INSTALLED = 1
TAB = 2
SHEET = 4
MAC = 8
FRESH = 5                       # stamps: under 24 h (4 h units), the DHCP lease
UNIT_MS = 14400000              # 4 h
FILE = "funnel.bin"
CTX = {"standalone": INSTALLED, "ios": TAB, "iosx": TAB, "and": TAB, "sam": TAB,
       "sheet": SHEET, "awv": SHEET}


def mac_of(ap, peer):
    # MAC mode: the phone's MAC from the hotspot's lease table, or None (stock firmware
    # raises for "leases"; keep keying by address then).
    if ap is None:
        return None
    try:
        for m, a in ap.status("leases"):
            if a == peer and len(m) == 6:
                return bytes(m)
    except Exception:
        pass
    return None


def ip_key(peer):
    try:
        p = [int(x) for x in peer.split(".")]
        if len(p) == 4:
            return b"ip" + bytes(p)
    except (ValueError, OverflowError):
        pass
    return b"ip\0\0\0\0"


class Funnel:
    def __init__(self, path, now=None, ap=None):
        # now: the stamp for this moment (stamp()), or None when the ship has no clock yet.
        self.path = path
        self.now = now
        self.ap = ap
        self.t = bytearray(N * REC)
        self.dirty = False
        try:
            with open(path, "rb") as f:
                f.readinto(self.t)
        except OSError:
            pass

    def key(self, peer):
        m = mac_of(self.ap, peer)
        return (m, MAC) if m else (ip_key(peer), 0)

    def find(self, k):
        t = self.t
        for o in range(0, N * REC, REC):
            if t[o + 6] and t[o:o + 6] == k:
                return o
        return -1

    def age(self, o):
        return 0 if self.now is None else (self.now - self.t[o + 7]) & 255

    def fresh(self, o):
        return self.t[o + 6] & MAC or self.age(o) <= FRESH

    def get(self, peer):
        o = self.find(self.key(peer)[0])
        return self.t[o + 6] if o >= 0 and self.fresh(o) else 0

    def mark(self, peer, flags):
        k, km = self.key(peer)
        t = self.t
        o = self.find(k)
        if o >= 0 and not self.fresh(o):
            t[o + 6] = 0                 # a lease ago: maybe someone else's phone now
            o = -1
        if o < 0:
            best = -1
            for i in range(0, N * REC, REC):
                if not t[i + 6]:
                    o = i
                    break
                sc = self.age(i) + (0 if t[i + 6] & INSTALLED else 512)
                if sc > best:
                    best, o = sc, i
            for i in range(6):
                t[o + i] = k[i]
            t[o + 6] = 0
        f = t[o + 6] | flags | km
        s = t[o + 7] if self.now is None else self.now
        if f != t[o + 6] or s != t[o + 7]:
            t[o + 6] = f
            t[o + 7] = s
            self.dirty = True
        return f

    def save(self):
        if not self.dirty:
            return
        import os
        with open(self.path + ".new", "wb") as f:
            f.write(self.t)
        try:
            os.remove(self.path)
        except OSError:
            pass
        os.rename(self.path + ".new", self.path)
        self.dirty = False

    def hello(self, q, peer):
        ctx = q.get("ctx", "")
        f = INSTALLED if q.get("m") == "icon" and ctx in CTX else CTX.get(ctx, 0)
        r = self.mark(peer, f) if f else self.get(peer)
        return {"installed": r & INSTALLED, "tab": r & TAB and 1, "sheet": r & SHEET and 1,
                "key": "mac" if self.key(peer)[1] else "ip"}


def stamp(epoch_ms):
    return None if epoch_ms is None else (epoch_ms // UNIT_MS) & 255


def api(web, req):
    # GET /api/hello for main.py. The page sends its clock (X-Phone-Time) with this, so the
    # ship has the time from the first request (lvweb learns it for every request too).
    sh = web.ship
    if sh.clock.learn_headers(req.header):
        sh.day_check()
    fn = Funnel(sh.data + "/" + FILE, stamp(sh.clock.epoch_ms()), getattr(web, "ap", None))
    r = fn.hello(req.q, req.peer)
    try:
        fn.save()
    except OSError:
        pass                     # a full or read-only /data: answer anyway
    return r
