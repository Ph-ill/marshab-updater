# Ship-to-ship sync: the part that does not care how bytes travel.
#
# Two ships that meet swap whatever records the other lacks. The choice log is a set
# (lv/chlog.py merges by union, highest seq per key), so a sync only has to make the two
# sets equal; the order records arrive in, duplicates and half-finished syncs never
# change the story. That is what lets every transport here be lossy and lazy.
#
# Adverts (BLE manufacturer data, 15 bytes, fits a legacy 31-byte advert with flags):
#   company 0xFFFF (test id), 'LV', proto, ship | flags << 4, flight day,
#   fleet id (2 B), record count (2 B, little-endian), log digest (4 B)
# A ship that hears a different digest from a ship of its own fleet and protocol starts
# a session (lv/ble.py decides who connects and when).
#
# Session (symmetric; both ends run the same code over one GATT characteristic):
#   HELLO  'H' proto ship day count(2) digest(4) nb bucket hashes (2 B each)
#   RECS   'R' then whole 13-byte records
#   DONE   'D' records sent (2 B)
# The log is cut into buckets by author (8 crew + admin) and 8-day block, plus one for
# records of a newer schema. Each side sends every record in a bucket whose hash differs
# from the peer's. If every bucket matches but the digests don't (a 16-bit collision),
# it sends everything. Nothing is ever deleted, so "send what might be missing" is safe.
#
# Messages go out in chunks: [payload length, msg id, index, count] + payload. One message
# is in flight at a time; the receiver reassembles by index (any order, duplicates
# dropped), acks with [0, 0, msg id, 0] and re-acks repeats. No ack within RETRY_MS:
# the message is sent again, RETRIES times, then the session fails. Records merge as
# each RECS message completes, so a link that drops mid-transfer keeps what arrived and
# the next meeting sends the rest. A session also fails when nothing arrives for
# IDLE_MS or it runs past SESSION_MS: a ship that walks away or switches off never
# holds anyone up.
#
# Transports: a Session only needs feed(bytes) for what arrives and pump(send) with a
# send(chunk) -> bool. lv/ble.py is the real one (Pico W radio); sim/link.py wires two
# Sessions together in memory for the tests, and sim/season.py's delivery scenarios
# stay the simulator's model of gossip.
from lv import record as R

try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256

PROTO = 1
COMPANY = b"\xff\xff"      # Bluetooth SIG "no company / testing" id
MAGIC = b"LV"
ADV_LEN = 15
F_BUSY = 1                 # flag nibble: in a session, don't connect now

AUTHORS = 9                # crew 0..7, then everything else (admin) in one column
BLOCKS = 6                 # 8-day blocks of authored day; later days share the last
NB = AUTHORS * BLOCKS + 1  # + newer-schema records
HDR = 4
MAX_PARTS = 16            # chunks per message: HELLO and RECS are < 128 B, 16 B a chunk at MTU 23

RETRY_MS = 1500
RETRIES = 4
IDLE_MS = 6000
SESSION_MS = 30000
PER_MSG = 9                # records per RECS message (117 B: one chunk at MTU 128)

RUN, OK, FAIL = 0, 1, 2


def fleet_id(fleet_key):
    return sha256(b"lv-fleet" + bytes(fleet_key)).digest()[:2]


def bucket(rec):
    s = rec[1] >> 4
    b = rec[4] >> 3
    return (s if s < 8 else 8) * BLOCKS + (b if b < BLOCKS else BLOCKS - 1)


def _add(h, i, rec):
    v = h[2 * i] | (h[2 * i + 1] << 8)
    v = (v + (rec[9] | (rec[10] << 8)) + rec[11] + 1) & 0xFFFF
    h[2 * i] = v & 255
    h[2 * i + 1] = v >> 8


class Node:
    """One ship's side of syncing: its log, plus cached advert numbers.
    on_new(list of records) is called with every batch that added something; the board
    runtime uses it to replay the story and spot gifts (sim/season.Ship.receive does the
    same thing for the simulator)."""

    def __init__(self, log, ship, fleet_key, day=0, on_new=None):
        self.log = log
        self.ship = ship
        self.fid = fleet_id(fleet_key)
        self.day = day
        self.on_new = on_new
        self.ver = 0
        self._cv = -1
        self._dig = b""
        self._bk = None
        self.got = 0       # records received over any link
        self.new = 0       # of those, new to this ship

    def merge(self, recs):
        fresh = []
        for r in recs:
            self.got += 1
            if self.log.merge(r) > 0:
                fresh.append(r)
        if fresh:
            self.ver += 1
            self.new += len(fresh)
            if self.on_new:
                self.on_new(fresh)
        return len(fresh)

    def add(self, rec):
        # A record authored on this ship.
        if self.log.merge(rec) > 0:
            self.ver += 1
            return True
        return False

    def _cache(self):
        if self._cv != self.ver:
            self._dig = self.log.digest()
            self._bk = None
            self._cv = self.ver
        return self._dig

    def digest(self):
        return self._cache()

    def buckets(self):
        self._cache()
        if self._bk is None:
            h = bytearray(2 * NB)
            for r in self.log.values():
                _add(h, bucket(r), r)
            for r in self.log.unknown:
                _add(h, NB - 1, r)
            self._bk = bytes(h)
        return self._bk

    def advert(self, busy=False):
        n = len(self.log) + len(self.log.unknown)
        return (COMPANY + MAGIC + bytes((PROTO, (self.ship & 15) | ((F_BUSY if busy else 0) << 4),
                                         self.day & 255)) +
                self.fid + bytes((n & 255, (n >> 8) & 255)) + self.digest())

    def wanted(self, theirs):
        # Which buckets the peer may be missing, from its bucket hashes: a bytearray with
        # 1 per bucket to send, or None for "send everything" (every bucket agrees but the
        # digests don't, i.e. a hash collision, or the peer sent no usable hashes).
        mine = self.buckets()
        if len(theirs) != len(mine):
            return None
        diff = bytearray(NB)
        nd = 0
        for i in range(NB):
            if mine[2 * i] != theirs[2 * i] or mine[2 * i + 1] != theirs[2 * i + 1]:
                diff[i] = 1
                nd += 1
        return diff if nd else None


class Plan:
    """What to send a peer, produced lazily: one 8-day shard's matching keys at a time
    (the log keeps changing while we send, as the peer's records merge in; each shard's
    keys are taken when we get to it, and records are fetched by key as they go)."""

    def __init__(self, log, diff):
        self.log = log
        self.diff = diff
        self.shards = sorted(log.recs)
        self.keys = []
        self.unk = list(log.unknown) if diff is None or diff[NB - 1] else []

    def take(self, n):
        out = []
        d, log = self.diff, self.log
        while len(out) < n:
            if self.keys:
                out.append(log.get(self.keys.pop()))
            elif self.shards:
                sh = log.recs.get(self.shards.pop(0)) or {}
                for k in sh:
                    s = (k >> 12) & 15
                    b = k >> 19
                    if d is None or d[(s if s < 8 else 8) * BLOCKS + (b if b < BLOCKS else BLOCKS - 1)]:
                        self.keys.append(k)
            elif self.unk:
                out.append(self.unk.pop())
            else:
                break
        return out


def parse_advert(adv):
    """Our fields from raw advertising data, or None. Walks the AD structures."""
    i, n = 0, len(adv)
    while i + 1 < n:
        ln = adv[i]
        if ln == 0:
            break
        if adv[i + 1] == 0xFF and ln - 1 == ADV_LEN and i + 2 + ADV_LEN <= n:
            p = bytes(adv[i + 2:i + 2 + ADV_LEN])
            if p[0:2] == COMPANY and p[2:4] == MAGIC:
                return {"proto": p[4], "ship": p[5] & 15, "busy": bool((p[5] >> 4) & F_BUSY),
                        "day": p[6], "fid": p[7:9], "n": p[9] | (p[10] << 8), "digest": p[11:15]}
        i += ln + 1
    return None


def adv_data(payload):
    # Flags (LE general discoverable, no BR/EDR) + manufacturer data.
    return b"\x02\x01\x06" + bytes((len(payload) + 1, 0xFF)) + payload


def chunks(mid, msg, size):
    # Split one message into chunks of at most `size` bytes including the header.
    room = size - HDR
    cnt = (len(msg) + room - 1) // room or 1
    out = []
    for k in range(cnt):
        p = msg[k * room:(k + 1) * room]
        out.append(bytes((len(p), mid, k, cnt)) + p)
    return out


class Session:
    """One sync with one peer. Feed it every chunk that arrives (feed) and call pump()
    often; pump sends through send(chunk) -> bool (False = link busy, try again later).
    `size` is the largest chunk the link carries (ATT MTU - 3)."""

    def __init__(self, node, now, size=20, opener=True):
        self.node = node
        self.size = size
        self.t0 = self.heard = now
        self.state = RUN
        self.why = ""
        self.peer = None          # peer ship, from its HELLO
        self.q = []               # chunks waiting for the link
        self.mid = 0
        self.wait = None          # (msg id, message) waiting for an ack
        self.sent_at = 0
        self.tries = 0
        self.parts = {}           # msg id -> {index: payload}
        self.seen = []            # last completed msg ids from the peer
        self.src = None           # Plan of what to send, once their HELLO is in
        self.hello_sent = False
        self.done_sent = self.done_acked = self.done_got = False
        self.sent = self.recv = self.added = 0
        self.retries = self.dups = 0
        if opener:
            self._hello(now)

    # ---- sending
    def _send_msg(self, msg, now):
        self.mid = self.mid % 255 + 1
        self.wait = (self.mid, msg)
        self.tries = 0
        self._queue(now)

    def _queue(self, now):
        mid, msg = self.wait
        self.q.extend(chunks(mid, msg, self.size))
        self.sent_at = now

    def _hello(self, now):
        nd = self.node
        n = len(nd.log) + len(nd.log.unknown)
        self.hello_sent = True
        self._send_msg(b"H" + bytes((PROTO, nd.ship, nd.day & 255, n & 255, (n >> 8) & 255)) +
                       nd.digest() + bytes((NB,)) + nd.buckets(), now)

    def _next(self, now):
        # The previous message was acked: what goes next?
        if self.src is None:
            return
        b = self.src.take(PER_MSG) if self.src else []
        if b:
            self.sent += len(b)
            self._send_msg(b"R" + b"".join(b), now)
        elif not self.done_sent:
            self.done_sent = True
            self.src = None
            self._send_msg(b"D" + bytes((self.sent & 255, (self.sent >> 8) & 255)), now)

    # ---- receiving
    def feed(self, data, now):
        # data: one chunk, or several back to back (a GATT server buffer in append mode).
        i, n = 0, len(data)
        while i + HDR <= n and self.state != FAIL:
            ln = data[i]
            c = data[i:i + HDR + ln]
            i += HDR + ln
            if len(c) < HDR + ln:
                break
            self.heard = now
            self._chunk(c, now)

    def _chunk(self, c, now):
        ln, mid, k, cnt = c[0], c[1], c[2], c[3]
        if mid == 0:                       # ack
            if self.wait and self.wait[0] == k:
                done = self.wait[1][0:1] == b"D"
                self.wait = None
                if done:
                    self.done_acked = True
                self._next(now)
                self._check()
            return
        if mid in self.seen:               # a repeat of something already handled
            self.dups += 1
            self.q.append(bytes((0, 0, mid, 0)))
            return
        if cnt == 0 or k >= cnt or cnt > MAX_PARTS:
            return
        got = self.parts.get(mid)
        if got is None:
            # The peer has one message in flight at a time: anything older is abandoned.
            # (Also bounds what a broken or hostile peer can make us hold.)
            if len(self.parts) >= 2:
                self.parts.pop(min(self.parts))
            got = self.parts[mid] = {}
        if k in got:
            self.dups += 1
            return
        got[k] = bytes(c[HDR:])
        if len(got) < cnt:
            return
        msg = b"".join([got[j] for j in range(cnt)])
        del self.parts[mid]
        self.seen.append(mid)
        if len(self.seen) > 16:
            self.seen.pop(0)
        self.q.append(bytes((0, 0, mid, 0)))
        self._msg(msg, now)

    def _msg(self, m, now):
        t = m[0:1]
        if t == b"H":
            if len(m) < 11 or m[1] != PROTO:
                return self._fail("proto")
            self.peer = m[2]
            nb = m[10]
            theirs = m[11:11 + 2 * nb]
            if m[6:10] == self.node.digest():
                self.src = False           # same log: nothing to send
            else:
                self.src = Plan(self.node.log, self.node.wanted(theirs))
            if not self.hello_sent:
                self._hello(now)       # the answering side says hello back first
            elif self.wait is None:
                self._next(now)
        elif t == b"R":
            recs = [m[j:j + R.LEN] for j in range(1, len(m) - R.LEN + 1, R.LEN)]
            self.recv += len(recs)
            self.added += self.node.merge(recs)
        elif t == b"D":
            self.done_got = True
            self._check()

    def _check(self):
        if self.done_acked and self.done_got and self.state == RUN:
            self.state = OK

    def complete(self):
        # Everything both ways got through, even if our DONE's ack was lost with the link.
        return self.state == OK or (self.done_got and self.done_sent and self.state == RUN)

    def _fail(self, why):
        if self.state == RUN:
            self.state = FAIL
            self.why = why
        return None

    # ---- driving
    def pump(self, send, now):
        if self.state != RUN:
            # Flush the last acks so the peer can finish too.
            while self.q and send(self.q[0]):
                self.q.pop(0)
            return self.state
        if now - self.t0 > SESSION_MS:
            self._fail("too long")
        elif now - self.heard > IDLE_MS:
            self._fail("silent")
        elif self.wait and not self.q and now - self.sent_at > RETRY_MS:
            if self.tries >= RETRIES:
                self._fail("no ack")
            else:
                self.tries += 1
                self.retries += 1
                self._queue(now)
        while self.q and send(self.q[0]):
            self.q.pop(0)
        return self.state
