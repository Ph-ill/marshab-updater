# Ship-to-ship sync over Bluetooth LE (MicroPython `bluetooth`, Pico W / Pico 2 W).
#
# The transport for lv/sync.py. The simulator and the unit tests use sync.LoopLink (and
# sim/season.py's delivery model) instead; tests/fakeble/bluetooth.py stands in for the
# radio so this file's own code runs under unix MicroPython and CPython.
#
# How a ship behaves:
#  * Advertises all the time (connectable, every ADV_MS) with sync.Node.advert(): ship,
#    flight day, fleet id, record count and log digest. A new advert goes out only when
#    one of those changes.
#  * Scans in short passive bursts: SCAN_MS every SCAN_EVERY_MS, listening WINDOW_US out
#    of every INTERVAL_US inside a burst (defaults: 3 s at 10 % every 12 s, about 2.5 % of
#    the radio). The CYW43439 shares one antenna between Wi-Fi and BLE, so the hotspot
#    keeps the air almost all the time (see bench/coex-test for the soak numbers).
#  * Hears a ship of the same fleet and protocol with a different digest: the lower ship
#    number connects; the higher one waits GRACE_MS first, in case the lower one can't.
#    One link at a time, no scanning during it. The central exchanges the MTU, enables
#    notifications and runs a sync.Session; the peripheral answers on the same
#    characteristic (writes in, notifications out). Both register the same single
#    service, so the value handle is the same on both and nothing is discovered.
#  * A failed or half-finished sync backs off for that peer (BACKOFF_MS doubling up to
#    BACKOFF_MAX_MS); a good one rests it for COOLDOWN_MS. Ships that are off, out of
#    range, on another protocol or another fleet are simply never connected to; nothing
#    waits for them, and their records arrive later through whoever met them.
#  * Never touches the LED, never allocates much in the IRQ: the handler only copies
#    bytes into small queues that poll() works through from the main loop.
from lv import sync as S

try:
    from micropython import const
except ImportError:  # CPython (tests)
    def const(x):
        return x

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_MTU_EXCHANGED = const(21)

SVC = "6c760001-5e1a-4b8e-9f3a-2d1c0b5a7e01"
CHR = "6c760002-5e1a-4b8e-9f3a-2d1c0b5a7e01"

DEFAULTS = {
    "adv_ms": 1000,
    "scan_ms": 3000,
    "scan_every_ms": 12000,
    "interval_us": 300000,
    "window_us": 30000,
    "connect_ms": 3000,
    "mtu": 128,
    "cooldown_ms": 15000,
    "backoff_ms": 20000,
    "backoff_max_ms": 600000,
    "grace_ms": 45000,
    "peer_ttl_ms": 600000,
    "linger_ms": 300,
}

IDLE, CONNECTING, SETUP, SYNC, CLOSING = "idle", "connecting", "setup", "sync", "closing"


class Peer:
    def __init__(self, ship):
        self.ship = ship
        self.addr = None          # (addr type, address bytes)
        self.seen = 0             # uptime ms last heard
        self.info = None          # parsed advert
        self.fails = 0
        self.next_try = 0
        self.diff_since = None    # first heard with a different log
        self.ok = 0
        self.why = ""


class BleSync:
    def __init__(self, node, ble=None, cfg=None, say=None):
        import bluetooth
        self.node = node
        c = dict(DEFAULTS)
        if cfg:
            c.update(cfg)
        self.cfg = c
        self.say = say                 # say(text): one-line log, or None
        self.ble = ble if ble is not None else bluetooth.BLE()
        self.ble.active(True)          # once; never toggled (coex: see bench/coex-test)
        for stop in (self.ble.gap_advertise, self.ble.gap_scan):
            try:
                stop(None)             # a soft reset leaves the stack running: quiet it first
            except OSError:
                pass
        try:
            self.ble.config(mtu=c["mtu"])
        except Exception:
            pass
        flags = bluetooth.FLAG_WRITE | bluetooth.FLAG_NOTIFY
        ((self.vh,),) = self.ble.gatts_register_services(
            ((bluetooth.UUID(SVC), ((bluetooth.UUID(CHR), flags),)),))
        # Writes accumulate (append mode), so a burst of writes is never lost to the
        # next one overwriting the value before poll() reads it.
        self.ble.gatts_set_buffer(self.vh, 512, True)
        self.ble.irq(self._irq)
        self.peers = {}
        self.scan_q = []
        self.rx = []
        self.ev = []
        self.state = IDLE
        self.conn = None
        self.central = False
        self.sess = None
        self.peer = None               # Peer we're syncing with (if known)
        self.t = 0                     # state entered at
        self.mtu = 23
        self.wbusy = False
        self.wsent = 0
        self.scanning = False
        self.next_scan = 0
        self.adv = None
        self.dropped = False
        self._now = 0
        self._swept = 0
        self.n = {"adv_heard": 0, "ours": 0, "other_fleet": 0, "other_proto": 0, "same_ship": 0,
                  "scans": 0, "out": 0, "in": 0, "ok": 0, "fail": 0, "refused": 0,
                  "sent": 0, "got": 0, "new": 0, "retries": 0, "dups": 0, "irq_drop": 0}
        self.last = ""

    # ---- IRQ: copy and queue, nothing else
    def _irq(self, ev, data):
        if ev == _IRQ_SCAN_RESULT:
            if len(self.scan_q) < 16:
                t, a, kind, rssi, adv = data
                self.scan_q.append((t, bytes(a), kind, rssi, bytes(adv)))
            else:
                self.n["irq_drop"] += 1
        elif ev == _IRQ_GATTS_WRITE:
            conn, h = data
            if conn == self.conn and h == self.vh:
                self.rx.append(bytes(self.ble.gatts_read(self.vh)))
        elif ev == _IRQ_GATTC_NOTIFY:
            conn, h, d = data
            if conn == self.conn and h == self.vh:
                self.rx.append(bytes(d))
        elif ev == _IRQ_GATTC_WRITE_DONE:
            self.wbusy = False
        elif ev == _IRQ_SCAN_DONE:
            self.scanning = False
        elif ev == _IRQ_CENTRAL_CONNECT or ev == _IRQ_PERIPHERAL_CONNECT:
            self.ev.append((ev, data[0], data[1], bytes(data[2])))
        elif ev == _IRQ_CENTRAL_DISCONNECT or ev == _IRQ_PERIPHERAL_DISCONNECT:
            self.ev.append((ev, data[0]))
        elif ev == _IRQ_MTU_EXCHANGED:
            self.ev.append((ev, data[0], data[1]))

    # ---- helpers
    def _log(self, text):
        self.last = text
        if self.say:
            self.say(text)

    def busy(self):
        # True while a link is up: the LED notifier waits (lv/led.py radio_busy).
        return self.state != IDLE

    def _advertise(self):
        a = self.node.advert(self.state != IDLE)
        if a != self.adv:
            try:
                self.ble.gap_advertise(self.cfg["adv_ms"] * 1000, adv_data=S.adv_data(a), connectable=True)
                self.adv = a
            except OSError:
                self.adv = None

    def _peer(self, ship):
        p = self.peers.get(ship)
        if p is None:
            p = self.peers[ship] = Peer(ship)
        return p

    def _go(self, state, now):
        self.state = state
        self.t = now

    # ---- main loop
    def poll(self, now):
        """Call every 20-100 ms from the main loop with the uptime in ms."""
        while self.ev:
            e = self.ev.pop(0)
            self._event(e, now)
        if self.state == IDLE:
            self._scan_results(now)
            if self.state == IDLE:
                self._advertise()
                if not self.scanning and now >= self.next_scan:
                    self._start_scan(now)
        elif self.state == CONNECTING:
            if now - self.t > self.cfg["connect_ms"] + 1000:
                try:
                    self.ble.gap_connect(None)          # cancel
                except OSError:
                    pass
                self._finish(now, "no answer")
        elif self.state == SETUP:
            # central: MTU exchanged (or given up on), then notifications on, then go.
            if self.sess is None and (self.mtu > 23 or now - self.t > 1000) and not self.wbusy:
                try:
                    self.ble.gattc_write(self.conn, self.vh + 1, b"\x01\x00", 1)
                    self.wbusy = True
                    self.wsent = now
                except OSError:
                    pass
                self.sess = S.Session(self.node, now, self.mtu - 3, True)
                self._go(SYNC, now)
        if self.state == SYNC or self.state == CLOSING:
            self._pump(now)
        self._forget(now)

    def _start_scan(self, now):
        try:
            self.ble.gap_scan(self.cfg["scan_ms"], self.cfg["interval_us"], self.cfg["window_us"], False)
            self.scanning = True
            self.n["scans"] += 1
        except OSError:
            pass
        # Spread the ships' bursts apart: a fixed per-ship offset plus a little drift.
        self.next_scan = now + self.cfg["scan_every_ms"] + (self.node.ship * 1373 + self.n["scans"] * 211) % 2000

    def _scan_results(self, now):
        q, self.scan_q = self.scan_q, []
        node = self.node
        for t, a, kind, rssi, adv in q:
            self.n["adv_heard"] += 1
            info = S.parse_advert(adv)
            if info is None:
                continue
            if info["fid"] != node.fid:
                self.n["other_fleet"] += 1
                continue
            if info["ship"] == node.ship:
                self.n["same_ship"] += 1       # two boards configured as the same ship
                continue
            self.n["ours"] += 1
            p = self._peer(info["ship"])
            p.addr = (t, a)
            p.seen = now
            p.info = info
            if info["proto"] != S.PROTO:
                self.n["other_proto"] += 1
                p.why = "protocol %d" % info["proto"]
                continue
            same = info["digest"] == node.digest()
            if same:
                p.diff_since = None
                continue
            if p.diff_since is None:
                p.diff_since = now
            if self.state != IDLE or info["busy"] or now < p.next_try or kind not in (0, 1):
                continue
            if node.ship < p.ship or now - p.diff_since > self.cfg["grace_ms"]:
                self._connect(p, now)

    def _connect(self, p, now):
        try:
            if self.scanning:
                self.ble.gap_scan(None)
                self.scanning = False
            self.ble.gap_connect(p.addr[0], p.addr[1], self.cfg["connect_ms"])
        except OSError as e:
            self._backoff(p, now, "connect %s" % e)
            return
        self.peer = p
        self.central = True
        self.n["out"] += 1
        self._go(CONNECTING, now)
        self._log("ble: connecting to ship %d" % (p.ship + 1))

    def _event(self, e, now):
        ev = e[0]
        if ev == _IRQ_PERIPHERAL_CONNECT:
            if self.state == CONNECTING:
                self.conn = e[1]
                self.mtu = 23
                try:
                    self.ble.gattc_exchange_mtu(self.conn)
                except OSError:
                    pass
                self._go(SETUP, now)
            else:
                self._drop(e[1])
        elif ev == _IRQ_CENTRAL_CONNECT:
            if self.state != IDLE:
                self.n["refused"] += 1
                self._drop(e[1])          # one link at a time; they'll back off and retry
                return
            if self.scanning:
                try:
                    self.ble.gap_scan(None)
                except OSError:
                    pass
                self.scanning = False
            self.conn = e[1]
            self.central = False
            self.peer = None
            self.mtu = 23
            self.n["in"] += 1
            self.sess = S.Session(self.node, now, self.mtu - 3, False)
            self._go(SYNC, now)
        elif ev == _IRQ_MTU_EXCHANGED:
            if e[1] == self.conn:
                self.mtu = e[2]
                if self.sess:
                    self.sess.size = self.mtu - 3
        elif ev == _IRQ_CENTRAL_DISCONNECT or ev == _IRQ_PERIPHERAL_DISCONNECT:
            if e[1] == self.conn or (self.state == CONNECTING and e[1] == 0xFFFF):
                self._finish(now, "link lost")

    def _drop(self, conn):
        try:
            self.ble.gap_disconnect(conn)
        except OSError:
            pass

    def _send(self, c):
        if self.central:
            if self.wbusy:
                return False
            try:
                self.ble.gattc_write(self.conn, self.vh, c, 1)   # with response: paced by the link
            except OSError:
                return False
            self.wbusy = True
            self.wsent = self._now
            return True
        try:
            self.ble.gatts_notify(self.conn, self.vh, c)
        except OSError:
            return False                   # out of buffers: the session keeps it queued
        return True

    def _pump(self, now):
        s = self.sess
        if self.wbusy and now - self.wsent > 1500:
            self.wbusy = False             # a write confirmation that never came
        rx, self.rx = self.rx, []
        for c in rx:
            s.feed(c, now)
        if s.peer is not None and self.peer is None:
            self.peer = self._peer(s.peer)
        self._now = now
        st = s.pump(self._send, now)
        if self.state == SYNC and st != S.RUN:
            self._go(CLOSING, now)
        if self.state == CLOSING and now - self.t > self.cfg["linger_ms"] and (not s.q or now - self.t > 2000):
            # The central hangs up once it's done (after a short linger so the last acks
            # get out); a peripheral only hangs up on a failed session.
            if (self.central or st == S.FAIL) and not self.dropped:
                self.dropped = True
                self._drop(self.conn)
            if now - self.t > 3000:
                self._finish(now, "close timeout")

    def _finish(self, now, why):
        s, p = self.sess, self.peer
        ok = s is not None and s.complete()
        if s is not None:
            n = self.n
            n["sent"] += s.sent
            n["got"] += s.recv
            n["new"] += s.added
            n["retries"] += s.retries
            n["dups"] += s.dups
            if s.why:
                why = s.why
        if ok:
            self.n["ok"] += 1
            if p:
                p.fails = 0
                p.ok += 1
                p.next_try = now + self.cfg["cooldown_ms"]
                p.why = ""
            self._log("ble: synced with ship %s: sent %d, got %d (%d new)" % (
                p.ship + 1 if p else "?", s.sent, s.recv, s.added))
        else:
            self.n["fail"] += 1
            if p:
                self._backoff(p, now, why)
            self._log("ble: sync with ship %s failed (%s)" % (p.ship + 1 if p else "?", why))
        if self.state != CONNECTING and self.conn is not None and why != "link lost":
            self._drop(self.conn)
        self.sess = None
        self.peer = None
        self.conn = None
        self.central = False
        self.wbusy = False
        self.rx = []
        self.dropped = False
        self.adv = None                    # re-advertise (a connection stops advertising)
        self._go(IDLE, now)

    def _backoff(self, p, now, why):
        p.fails += 1
        p.why = why
        d = self.cfg["backoff_ms"] << min(p.fails - 1, 5)
        # plus a per-ship stagger, so two ships that keep crossing don't stay in step
        p.next_try = now + min(d, self.cfg["backoff_max_ms"]) + (self.node.ship * 397) % 5000

    def _forget(self, now):
        if now - self._swept < 10000:
            return
        self._swept = now
        ttl = self.cfg["peer_ttl_ms"]
        for k in [k for k, p in self.peers.items() if now - p.seen > ttl]:
            del self.peers[k]

    def status(self, now):
        """Plain dict for the self-test and the status page."""
        ps = []
        for k in sorted(self.peers):
            p = self.peers[k]
            i = p.info or {}
            ps.append({"ship": k + 1, "ago_s": (now - p.seen) // 1000, "n": i.get("n"),
                       "same": i.get("digest") == self.node.digest(), "proto": i.get("proto"),
                       "ok": p.ok, "fails": p.fails, "why": p.why})
        return {"state": self.state, "scanning": self.scanning, "records": len(self.node.log),
                "digest": self.node.digest().hex(), "peers": ps, "n": self.n, "last": self.last}
