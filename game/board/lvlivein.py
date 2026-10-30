# Ship-to-ship items (Hail, 0.3.0): the parts of lvlive.py that run only when items move.
# Loaded per use and dropped straight after (lvship.drop), so none of it stays resident
# next to two phones and a sync: lvlive.Link.take loads it when a trailer arrives,
# Link.poll and Link.finish when a dial is due or done, and lvliveapi.py (a phone's hail
# or "seen") and lvlivex.py (the box file at install) use the same box-file and item
# helpers. The format is described at the top of lvlive.py.
import lvship
import lvlive as L
from binascii import hexlify
from io import IOBase
try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256


def probe(stage="save"):
    p = getattr(lvship, "heap_probe", None)
    if p:
        lvship.heap_stage = stage
        p()


class SaveWriter(IOBase):
    def __init__(self, f):
        self.f = f
        self.h = sha256()

    def write(self, b):
        if isinstance(b, str):
            b = b.encode()
        self.h.update(b)
        n = self.f.write(b)
        probe("serialize")
        return n


def save(path, obj, parts=None):
    import json
    import os
    with open(path + ".new", "wb") as f:
        writer = SaveWriter(f)
        if parts is None:
            json.dump(obj, writer)
        else:
            for part in parts:
                writer.write(part)
        probe()
        expected = writer.h.digest()
    writer = None
    actual = sha256()
    # Reuse readback storage instead of leaving one discarded bytes object
    # per chunk alongside the full durable game and any HTTP snapshot.
    chunk = bytearray(256)
    view = memoryview(chunk)
    with open(path + ".new", "rb") as f:
        while True:
            n = f.readinto(chunk)
            probe()
            if not n:
                break
            actual.update(view if n == len(chunk) else view[:n])
    if actual.digest() != expected:
        raise OSError("read back")
    os.rename(path + ".new", path)


class LoadReader(IOBase):
    # Observe the parser while its partly built object and input coexist.
    # MicroPython's JSON parser reads through readinto; CPython uses read.
    def __init__(self, f):
        self.f = f

    def readinto(self, b):
        n = self.f.readinto(b)
        probe("parse")
        return n

    def read(self, n=-1):
        b = self.f.read(n)
        probe("parse")
        return b


def load(path):
    import json
    try:
        with open(path) as f:
            j = json.load(LoadReader(f) if getattr(lvship, "heap_probe", None) else f)
            probe("parse " + path.rsplit("/", 1)[-1])
        return j if isinstance(j, dict) else None
    except (OSError, ValueError):
        return None


EPOCHS = 4              # a sender's past epochs kept (lk.hw: [epoch, seq, older epochs...])


def forget(sh):
    # Reset this ship (lvcode.reset, 0.3.0 review R2 m10): the hails that came in and
    # no phone has read go, and so do this ship's own still waiting (FIXREVIEW2 minor 10:
    # Reset says everyone's hails go). The rest of livebox.json stays: its epoch, sequence
    # and each sender's highest taken (replay protection).
    L = getattr(sh, "live", None)
    if L is not None:
        del L.inb[:]
        del L.out[:]
    p = sh.data + "/livebox.json"
    b = load(p)
    if b and (b.get("i") or b.get("o")):
        b["i"] = []
        b["o"] = []
        save(p, b)


def keep(lk):
    """The Link's queues and counters to /data/livebox.json (lk.v: the page's version)."""
    # Inbound rules have returned before the trailer checkpoint. Reclaim their
    # released frames/modules before this separate persistence transaction.
    lvship.free()
    lk.v += 1
    save(lk.f, None, boxparts(lk))


def boxparts(lk):
    # Encode one queue entry at a time, never a second expanded livebox.
    import json
    yield '{"e": %d, "s": %d' % (lk.ep, lk.seq)
    for key, queue in (("o", lk.out), ("i", lk.inb)):
        yield ', "' + key + '": ['
        for i, o in enumerate(queue):
            yield (", " if i else "") + json.dumps((o[0], hexlify(o[1]).decode(), o[2]))
        yield "]"
    yield ', "h": ' + json.dumps(dict((str(k), v) for k, v in lk.hw.items()))
    yield ', "l": ' + json.dumps(lk.lc) + "}"


def mac(lk, frm, b):
    return sha256(lk.sh.fk + bytes((frm,)) + b).digest()[:4]


def item(lk, kind, to, body, seq=None):
    if seq is None:
        lk.seq = seq = lk.seq % 65535 + 1
    b = bytes((kind, to, lk.ep, seq >> 8, seq & 255)) + bytes(body) + bytes(11 - len(body))
    return b + mac(lk, lk.node.ship, b)


def send(lk, kind, to, body):
    """Queue an item for ship `to` (0-7); -> its (epoch, seq) reference, 3 bytes."""
    if len(lk.out) >= 24:
        raise ValueError("live out-box full")
    it = item(lk, kind, to, body)
    lk.out.append([to, it, lk.sh.clock.date()])     # (it goes when the day turns: expire)
    x = nx(lk, to)
    if x[0] >= 2 and x[3] < 2:          # (a ship that keeps failing keeps its backoff)
        x[0] = x[1] = 0
    lk.due = 0
    lk.n["out"] += 1
    try:
        keep(lk)
    except Exception:
        # An in-RAM item is not evidence of a durable enqueue on retry.
        lk.out.pop()
        lk.n["out"] -= 1
        raise
    return it[2:5]


def take(lk, s, m, off):
    """Items off the air: a trailer at m[off:] in session s (with ship s.to)."""
    frm = s.to
    if len(m) < off + 2 or m[off] != L.MARK:
        return
    n = m[off + 1]
    if n > L.MAXI or len(m) < off + 2 + n * L.LEN:
        lk.n["bad"] += 1
        return
    me, ch, fl = lk.node.ship, 0, 0
    for j in range(off + 2, off + 2 + n * L.LEN, L.LEN):
        b = bytes(m[j:j + L.LEN])
        if b[1] != me or b[16:] != mac(lk, frm, b[:16]):
            lk.n["bad"] += 1
            continue
        if b[0] == 0:
            for o in lk.out:
                if o[0] == frm and o[1][2:5] == b[5:8]:
                    lk.out.remove(o)
                    lk.n["acked"] += 1
                    _in(lk, frm, b)
                    ch = 1
                    break
            continue
        q = [b[2], b[3] << 8 | b[4]]

        h = lk.hw.get(frm)
        if h and h[0] != q[0] and q[0] in h[2:]:
            # an epoch this sender has left behind (its box file was made again since): a
            # recording played back (0.3.0 review R3 m4). Not taken, not acked.
            lk.n["bad"] += 1
            continue
        s.acks.append(item(lk, 0, frm, b[2:5], 0))
        if h and h[0] == q[0] and q[1] <= h[1]:
            lk.n["dup"] += 1
            continue
        if h:                               # the epochs left behind, newest first
            q += h[2:] if h[0] == q[0] else ([h[0]] + h[2:])[:EPOCHS]
        od = b[0] == 1 and old(lk, b)
        if od:                              # sent over a day ago (by its clock): kept and
            lk.n["old"] += 1                # listed, no light (clocks jump: FIXREVIEW3 f2)
        dl = _in(lk, frm, b)                # answers queue before the reply HELLO
        lk.hw[frm] = q                      # between the two and the repeat still goes in)
        lk.n["in"] += 1
        ch = 1
        if b[0] == 1 and not od:        # a hail: the light (a "seen" is quiet)
            fl = 1
        elif dl:
            fl = 2
    if ch:
        keep(lk)                        # (raises: Link.take puts RAM back, nothing acked)
    duels(lk)                           # ACKs may have freed room for durable replies
    if fl:                              # once it's kept: a failed save gets no light
        c = lk.lc[1]
        flick(lk, fl == 2)
        if lk.lc[1] != c:
            try:
                keep(lk)                # (the light's day count: lk.lc)
            except Exception:
                pass


def _in(lk, frm, b):
    if 3 <= b[0] <= 9:
        return duel_take(lk, frm, b[0], b[5:16])
    if b[0] > 9:                        # a later release's kind: acked, not kept
        return
    q = lk.inb
    if len(q) >= L.MAXIN:               # full (nobody's opened the game): the oldest goes
        q.pop(0)
    c = lk.sh.clock                     # when it came: the phone's clock if known, and the
    q.append([frm, b, int(c.epoch_ms()) if c.known() else None, lk.now])    # loop's ms


def duel_take(lk, frm, kind, b):
    if len(b) != 11 or not 3 <= kind <= 9:
        return False
    while True:
        unknown = getattr(lk, "duel_unknown", None)
        # Parse before loading receive rules. The HTTP stream can still own
        # its compact snapshot here; do not add rule bytecode to the parser.
        lvship.free()
        j = load(lk.sh.data + "/duel.json") or {"g": [], "r": {}}
        lvship.free()
        import lvduel
        try:
            j, change = lvduel.receive(lk, frm, kind, b, j)
        finally:
            lvship.drop("lvduel")
            lvduel = None
        if change is None:
            return False
        try:
            duel_store(lk, j)
        except Exception:
            lk.duel_unknown = unknown
            raise
        light, retry = change
        if retry is None:
            p = getattr(lk.sh, "duel_probe", None)
            if p:
                p(j)
            return light
        kind, b = retry
        j = change = None


def duel_store(lk, j):
    # Publish the game before loading outbox cleanup and replay helpers.
    # Neither receive rules nor outbox bytecode need overlap this first save.
    lvship.free()
    save(lk.sh.data + "/duel.json", j)
    lk.v += 1
    probe()
    import lvduelstore
    try:
        lvduelstore.cleanout(lk, j)
        lvduelstore.flush(lk, j)
    finally:
        lvship.drop("lvduelstore")
        lvduelstore = None


def mins(c):
    # The ship's clock as minutes since 1970, mod 65536 (a hail's send time); None unknown
    return int(c.epoch_ms()) // 60000 & 65535 if c.known() else None


def old(lk, b):
    """A hail its sender's clock says went over a day ago (delivered late, or one of the two
    clocks wrong): counted only."""
    t = b[8] << 8 | b[9]
    m = mins(lk.sh.clock)
    if t == 65535 or not t or m is None:    # (0: a sender that didn't say)
        return False
    a = (m - t) & 65535                 # minutes ago (a sender's clock a little ahead: ~65535)
    return 1440 < a < 65536 - 60


def expire(lk):
    """Waiting items from an earlier day go (hail.json shows an undelivered hail as "Didn't
    go" for a day: lvliveapi._hl); a "seen" for a crewmate who never came back goes too."""
    d = lk.sh.clock.date()
    k = []
    for o in lk.out:
        if o[1][0] > 2:                # duels survive the day turning
            continue
        if d and not isinstance(o[2], int):
            o[2] = d                    # queued before the clock was known: today's
        elif d and o[2] < d:            # (a clock set back expires nothing: FIXREVIEW3 f2)
            k.append(o)
    if k:
        for o in k:
            lk.out.remove(o)
        lk.n["gone"] += len(k)
        keep(lk)


def duels(lk):
    web = getattr(lk.sh, "web", None)
    ble = getattr(lk, "ble", None)
    if (web is not None and web.busy > 0) or (ble is not None and ble.state != "idle"):
        # ACKs can make room during a streamed answer. Flush/recovery is a
        # separate transaction: schedule it after HTTP and the radio session,
        # not beside a snapshot or another receive frame.
        lk.duel_due = 0
        return
    import os
    try:
        os.stat(lk.sh.data + "/duel.json")
    except OSError:
        return
    try:
        import lvduel
        lvduel.maintain(lk)
    finally:
        lvship.drop("lvduel")


def flick(lk, duel=False):
    try:                         # the checks and the light: lvflick.py, per use
        import lvflick
        return lvflick.maybe(lk, duel)
    except Exception as e:       # the light is a nicety: never the link's problem
        lk.sh.say("live: no hail light %r" % (e,))
    finally:
        lvship.drop("lvflick")


def nx(lk, to):
    # lk.nx[to]: [dials, next dial ms (0 now), last dial ms (0 never), failures in a row]
    x = lk.nx.get(to)
    if x is None:
        x = lk.nx[to] = [0, 0, 0, 0]
    while len(x) < 4:                   # (an older entry)
        x.append(0)
    return x


def failed(lk, x, now):
    # a dial that got nowhere: from the second in a row, back off 1, 2, 4... min, MAXB at most
    x[3] += 1
    if x[3] >= 2:
        x[1] = now + min(L.MAXB, L.EVERY << min(x[3] - 2, 8))


def dial(lk, b, now):
    """Dial one ship with a hail waiting that can take one now (Link.poll, idle radio): heard
    in the last L.NEAR, its own next dial due, and none to anyone for L.GAP. Of those, the
    one whose last hail dial is oldest (never dialled first), so ships that keep failing
    take turns with, and can't starve, one that just came back (FIXREVIEW2 J1). Sets
    lk.due, the earliest time another look is worth an import."""
    expire(lk)
    wait = 5000                     # nobody in range: look again in 5 s
    best = None
    seen = []
    for o in lk.out:
        to = o[0]
        if to in seen:
            continue
        seen.append(to)
        p = b.peers.get(to)
        x = nx(lk, to)
        if (x[2] or x[3]) and not L.near(now, p, L.OUT):
            x[0] = x[1] = x[2] = x[3] = 0   # out of range a while: back, it starts over (and first)
        if not L.near(now, p) or p.addr is None or not p.info or not p.info.get("cap"):
            continue
        # GAP between hail dials; a crewmate not dialled yet (new, or back in range) waits
        # only a quarter of it, so a run of dials to ships that won't answer can't hold up
        # one that just came back (FIXREVIEW2 J1)
        g = lk.gap if x[2] or not lk.gap else lk.gap - L.GAP + L.GAP // 4
        if p.info["busy"] or not L.due(now, x[1]) or not L.due(now, g):
            r = max(0 if L.due(now, x[1]) else L.dt(x[1], now), 0 if L.due(now, g) else L.dt(g, now))
            wait = min(wait, max(1000, r))
            continue
        a = L.dt(now, x[2]) if x[2] else 0x3FFFFFFF        # how long since its last dial
        if best is None or a > best[0]:
            best = (a, to, p, x)
    if best is None:
        lk.due = now + wait
        return
    a, to, p, x = best
    x[0] += 1
    x[1] = now + (L.FAST if x[0] < 2 else L.EVERY)
    x[2] = now or 1
    lk.gap = now + L.GAP
    lk.forced = (p, p.fails, p.next_try, lk._for(to))
    lk.n["dial"] += 1
    b._connect(p, now)
    if b.state != "connecting":     # the stack said no: put the backoff back
        f, lk.forced = lk.forced, None
        p.fails, p.next_try = f[1], f[2]
        lk.n["dial_fail"] += 1
        failed(lk, x, now)
    lk.due = 0                      # look again once the radio is idle


def done(lk, f, p, s, now):
    """After a session this Link dialled: count it, give the stack its backoff back."""
    ok = s is not None and s.complete()
    lk.n["dial_ok" if ok else "dial_fail"] += 1
    p.fails, p.next_try = f[1], f[2]
    x = nx(lk, p.ship)
    # anything left: the next session, but only if this one moved something (an
    # item the peer won't take, say a bad mac, keeps to the 2-then-1-a-minute dials)
    if ok:
        x[3] = 0
        k = lk._for(p.ship)
        if 0 < k < f[3]:                # moved some, more for them: straight on (the GAP
            x[0], x[1] = 0, now + 1000  # is between crewmates, not within one)
            lk.gap = 0
    else:
        failed(lk, x, now)
    lk.due = 0
