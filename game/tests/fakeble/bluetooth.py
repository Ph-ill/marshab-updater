# A stand-in for MicroPython's `bluetooth` module, so lv/ble.py runs unchanged under the
# unix port (32- and 64-bit) and CPython. Put this directory first on sys.path.
#
# One World holds every fake radio and a virtual clock in ms. It models what lv/ble.py
# relies on: connectable adverts heard by duty-cycled passive scans, gap_connect with a
# timeout (and cancel), one GATT characteristic per device at the same handle, writes
# with response and an append-mode server buffer, notifications that need the CCCD
# written and can run out of buffers (OSError), MTU exchange, disconnects.
# It also breaks things on purpose: drop / duplicate / reorder data packets (per-mille
# rates), cut a link after N packets, take a device out of range or power it off, and
# make a device that advertises but never accepts a connection.
#
# IRQ data comes as memoryviews like the real stack's, so code that forgets to copy
# breaks here too.
FLAG_READ = 0x0002
FLAG_WRITE_NO_RESPONSE = 0x0004
FLAG_WRITE = 0x0008
FLAG_NOTIFY = 0x0010

_CC, _CD, _GW, _SR, _SD, _PC, _PD, _WD, _NT, _MTU = 1, 2, 3, 5, 6, 7, 8, 17, 18, 21
NOTIFY_SLOTS = 4


class UUID:
    def __init__(self, v):
        self.v = v

    def __eq__(self, o):
        return isinstance(o, UUID) and o.v == self.v


class World:
    def __init__(self, seed=1):
        self.now = 0
        self.devs = []
        self.q = []            # [due, n, fn, args]
        self.n = 0
        self.r = seed or 1
        self.drop = self.dup = self.reorder = 0     # per mille, data packets only
        self.cut_after = None  # packets on a link before the link drops (once per link)
        self.cut_links = 0     # how many more links get cut (with cut_after)
        self.apart = []        # pairs of devices out of range of each other
        self.links = {}        # conn handle -> Link
        self.h = 63
        self.stats = {"dropped": 0, "duplicated": 0, "reordered": 0, "cut": 0, "enomem": 0,
                      "adv_seen": 0, "connects": 0, "timeouts": 0}

    def rand(self, m):
        # xorshift32: the same sequence on CPython and both MicroPython builds
        x = self.r
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.r = x
        return x % m

    def new(self):
        d = Radio(self, len(self.devs))
        self.devs.append(d)
        return d

    def at(self, delay, fn, *args):
        self.n += 1
        self.q.append([self.now + delay, self.n, fn, args])

    def near(self, a, b):
        return a.on and b.on and (a, b) not in self.apart and (b, a) not in self.apart

    def separate(self, a, b):
        self.apart.append((a, b))
        for c, ln in list(self.links.items()):
            if (ln.c is a and ln.p is b) or (ln.c is b and ln.p is a):
                ln.close()

    def rejoin(self, a, b):
        self.apart = [x for x in self.apart if x != (a, b) and x != (b, a)]

    def power(self, d, on):
        d.on = on
        if not on:
            for ln in list(self.links.values()):
                if ln.c is d or ln.p is d:
                    ln.close()
            d.adv = None
            d.scan_end = 0
            d.rx = bytearray()

    def step(self, ms=10):
        end = self.now + ms
        while True:
            due = [e for e in self.q if e[0] <= end]
            if not due:
                break
            due.sort(key=lambda e: (e[0], e[1]))
            e = due[0]
            self.q.remove(e)
            if e[0] > self.now:
                self.now = e[0]
            e[2](*e[3])
        self.now = end
        self._air()

    def _air(self):
        # Adverts: each advertiser transmits every interval; a scanner inside a burst
        # hears it with probability window/interval.
        for a in self.devs:
            if not a.on or a.adv is None or self.now < a.adv_next:
                continue
            a.adv_next = self.now + a.adv_iv
            for s in self.devs:
                if s is a or s.scan_end <= self.now or not self.near(a, s):
                    continue
                if self.rand(1000) < s.duty:
                    self.stats["adv_seen"] += 1
                    s._irq(_SR, (0, memoryview(a.addr), 0 if a.connectable else 3, -50,
                                 memoryview(a.adv)))


class Link:
    def __init__(self, w, c, p):
        w.h += 1
        self.w, self.c, self.p, self.h = w, c, p, w.h
        self.mtu = 23
        self.cccd = False
        self.packets = 0
        self.inflight = 0
        self.open = True
        self.cut_at = None
        if w.cut_after is not None and w.cut_links > 0:
            w.cut_links -= 1
            self.cut_at = w.cut_after
        w.links[self.h] = self

    def close(self):
        if not self.open:
            return
        self.open = False
        del self.w.links[self.h]
        self.w.at(5, self.c._irq, _PD, (self.h, 0, memoryview(self.p.addr)))
        self.w.at(5, self.p._irq, _CD, (self.h, 0, memoryview(self.c.addr)))
        self.p.rx = bytearray()

    def data(self, fn, payload):
        # One data packet towards fn: faults apply here.
        w = self.w
        self.packets += 1
        if self.cut_at is not None and self.packets > self.cut_at:
            w.stats["cut"] += 1
            self.close()
            return
        x = w.rand(1000)
        if x < w.drop:
            w.stats["dropped"] += 1
            return
        delay = 8 + w.rand(8)
        if w.rand(1000) < w.reorder:
            w.stats["reordered"] += 1
            delay += 20 + w.rand(60)
        w.at(delay, fn, self, payload)
        if x < w.drop + w.dup:
            w.stats["duplicated"] += 1
            w.at(delay + 3 + w.rand(30), fn, self, payload)


class Radio:
    def __init__(self, w, i):
        self.w = w
        self.addr = bytes((2, 0x4c, 0x56, 0, 0, i))
        self.on = True
        self.active_ = False
        self.handler = None
        self.adv = None
        self.adv_iv = 1000
        self.adv_next = 0
        self.connectable = True
        self.scan_end = 0
        self.duty = 0
        self.mtu = 23
        self.vh = None
        self.rx = bytearray()
        self.append = False
        self.pending = None      # outgoing connect: [addr, due]
        self.deaf = False        # advertises but never accepts a connection
        self.irqs = 0

    # ---- plumbing
    def _irq(self, ev, data):
        if self.on and self.handler:
            self.irqs += 1
            self.handler(ev, data)

    def _link(self, conn):
        ln = self.w.links.get(conn)
        if ln is None or not ln.open:
            raise OSError(128)    # ENOTCONN
        return ln

    # ---- API
    def active(self, *a):
        if a:
            self.active_ = bool(a[0])
        return self.active_

    def config(self, *a, **kw):
        if "mtu" in kw:
            self.mtu = kw["mtu"]
        if a and a[0] == "mac":
            return (0, self.addr)
        return None

    def irq(self, handler):
        self.handler = handler

    def gatts_register_services(self, services):
        self.vh = 9               # same handle on every device, like identical firmware
        return ((self.vh,),)

    def gatts_set_buffer(self, h, size, append=False):
        self.append = append

    def gatts_read(self, h):
        b = bytes(self.rx)
        self.rx = bytearray()
        return b

    def gatts_write(self, h, data, send_update=False):
        pass

    def gap_advertise(self, interval_us, adv_data=None, connectable=True):
        if not self.on:
            raise OSError(5)
        if interval_us is None:
            self.adv = None
            return
        self.adv = bytes(adv_data)
        self.adv_iv = max(20, interval_us // 1000)
        self.connectable = connectable

    def gap_scan(self, duration_ms, interval_us=1280000, window_us=11250, active=False):
        if duration_ms is None:
            if self.scan_end > self.w.now:
                self.scan_end = 0
                self.w.at(1, self._irq, _SD, ())
            return
        if not self.on:
            raise OSError(5)
        self.duty = window_us * 1000 // interval_us
        self.scan_end = self.w.now + (duration_ms or 10 ** 9)
        self.w.at(duration_ms or 10 ** 9, self._scan_done, self.scan_end)

    def _scan_done(self, end):
        if self.scan_end == end:
            self.scan_end = 0
            self._irq(_SD, ())

    def gap_connect(self, addr_type, addr=None, timeout_ms=2000, *a):
        w = self.w
        if addr_type is None:
            if self.pending:
                self.pending = None
                w.at(1, self._irq, _PD, (0xFFFF, 0, memoryview(bytes(6))))
            return
        if self.pending:
            raise OSError(114)   # EALREADY
        addr = bytes(addr)
        self.pending = [addr]
        tgt = None
        for d in w.devs:
            if d.addr == addr:
                tgt = d
        ok = (tgt is not None and w.near(self, tgt) and tgt.adv is not None and tgt.connectable
              and not tgt.deaf)
        if ok:
            w.at(20 + w.rand(60), self._connected, self.pending, tgt)
        else:
            w.stats["timeouts"] += 1
            w.at(timeout_ms, self._timeout, self.pending, addr)

    def _timeout(self, tok, addr):
        if self.pending is tok:
            self.pending = None
            self._irq(_PD, (0xFFFF, 0, memoryview(addr)))

    def _connected(self, tok, tgt):
        if self.pending is not tok:
            return
        self.pending = None
        w = self.w
        if not (w.near(self, tgt) and tgt.adv is not None):
            self._irq(_PD, (0xFFFF, 0, memoryview(tgt.addr)))
            return
        w.stats["connects"] += 1
        tgt.adv = None            # a peripheral stops advertising once connected
        ln = Link(w, self, tgt)
        self._irq(_PC, (ln.h, 0, memoryview(tgt.addr)))
        tgt._irq(_CC, (ln.h, 0, memoryview(self.addr)))

    def gap_disconnect(self, conn):
        ln = self.w.links.get(conn)
        if ln is None:
            return False
        self.w.at(3, ln.close)
        return True

    def gattc_exchange_mtu(self, conn):
        ln = self._link(conn)
        m = min(ln.c.mtu, ln.p.mtu)
        ln.mtu = m

        def done():
            if ln.open:
                ln.c._irq(_MTU, (ln.h, m))
                ln.p._irq(_MTU, (ln.h, m))
        self.w.at(15, done)

    def gattc_write(self, conn, h, data, mode=0):
        ln = self._link(conn)
        data = bytes(data)
        if len(data) > ln.mtu - 3:
            raise ValueError("write longer than MTU-3")
        if h == self.vh + 1:
            ln.cccd = data[:1] == b"\x01"
            self.w.at(10, self._wdone, ln, h)
            return
        ln.data(self._to_server, data)
        if mode == 1:
            self.w.at(12, self._wdone, ln, h)

    def _wdone(self, ln, h):
        if ln.open:
            self._irq(_WD, (ln.h, h, 0))

    def _to_server(self, ln, data):
        if not ln.open:
            return
        p = ln.p
        if p.append:
            p.rx.extend(data)
        else:
            p.rx = bytearray(data)
        p._irq(_GW, (ln.h, p.vh))

    def gatts_notify(self, conn, h, data=None):
        ln = self._link(conn)
        data = bytes(data)
        if len(data) > ln.mtu - 3:
            raise ValueError("notify longer than MTU-3")
        if not ln.cccd:
            return               # client never subscribed: goes nowhere
        if ln.inflight >= NOTIFY_SLOTS:
            self.w.stats["enomem"] += 1
            raise OSError(12)    # ENOMEM: the stack's buffers are full
        ln.inflight += 1
        self.w.at(6, self._freed, ln)
        ln.data(self._to_client, data)

    def _freed(self, ln):
        ln.inflight -= 1

    def _to_client(self, ln, data):
        if ln.open:
            ln.c._irq(_NT, (ln.h, ln.p.vh, memoryview(data)))


WORLD = World()


def BLE():
    return WORLD.new()
