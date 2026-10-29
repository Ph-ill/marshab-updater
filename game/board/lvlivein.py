# Ship-to-ship items (Hail, 0.3.0): the parts of lvlive.py that run only when items move.
# Loaded per use and dropped straight after (lvship.drop), so none of it stays resident
# next to two phones and a sync: lvlive.Link.take loads it when a trailer arrives,
# Link.poll and Link.finish when a dial is due or done, and lvliveapi.py (a phone's hail
# or "seen") and lvlivex.py (the box file at install) use the same box-file and item
# helpers. The format is described at the top of lvlive.py.
import lvship
import lvlive as L
from binascii import hexlify
try:
    from hashlib import sha256
except ImportError:  # pragma: no cover
    from uhashlib import sha256


def save(path, obj):
    import json
    import os
    t = json.dumps(obj)
    with open(path + ".new", "w") as f:
        f.write(t)
    with open(path + ".new") as f:
        if f.read() != t:
            raise OSError("read back")
    os.rename(path + ".new", path)


def load(path):
    import json
    try:
        with open(path) as f:
            j = json.load(f)
        return j if isinstance(j, dict) else None
    except (OSError, ValueError):
        return None


def keep(lk):
    """The Link's queues and counters to /data/livebox.json (lk.v: the page's version)."""
    lk.v += 1
    save(lk.f, {"e": lk.ep, "s": lk.seq, "o": [[o[0], hexlify(o[1]).decode(), o[2]] for o in lk.out],
                "i": [[o[0], hexlify(o[1]).decode(), o[2]] for o in lk.inb],
                "h": dict((str(k), v) for k, v in lk.hw.items()), "l": lk.lc})


def mac(lk, frm, b):
    return sha256(lk.sh.fk + bytes((frm,)) + b).digest()[:4]


def item(lk, kind, to, body, seq=None):
    if seq is None:
        lk.seq = seq = lk.seq % 65535 + 1
    b = bytes((kind, to, lk.ep, seq >> 8, seq & 255)) + bytes(body) + bytes(11 - len(body))
    return b + mac(lk, lk.node.ship, b)


def send(lk, kind, to, body):
    """Queue an item for ship `to` (0-7); -> its (epoch, seq) reference, 3 bytes."""
    it = item(lk, kind, to, body)
    lk.out.append([to, it, lk.sh.clock.date()])     # (it goes when the day turns: expire)
    x = lk.nx.get(to)
    if x is None or x[0] >= 2:
        lk.nx[to] = [0, 0]
    lk.due = 0
    lk.n["out"] += 1
    keep(lk)
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
    me, ch = lk.node.ship, 0
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
        s.acks.append(item(lk, 0, frm, b[2:5], 0))
        q = [b[2], b[3] << 8 | b[4]]
        h = lk.hw.get(frm)
        if h and h[0] == q[0] and q[1] <= h[1]:
            lk.n["dup"] += 1
            continue
        if b[0] == 1 and old(lk, b):        # sent over a day ago: acked, not kept
            lk.hw[frm] = q
            lk.n["old"] += 1
            ch = 1
            continue
        _in(lk, frm, b)                     # (kept before it's marked taken: a MemoryError
        lk.hw[frm] = q                      # between the two and the repeat still goes in)
        lk.n["in"] += 1
        lk.tf = 0
        ch = 1
        if b[0] == 1:                   # a hail: the light (a "seen" is quiet)
            flick(lk)
    if ch:
        keep(lk)


def _in(lk, frm, b):
    if b[0] > 2:                        # a later release's kind: acked, not kept
        return
    q = lk.inb
    if len(q) >= L.MAXIN:               # full (nobody's opened the game): the oldest goes
        q.pop(0)
    c = lk.sh.clock                     # when it came: the phone's clock if known, and the
    q.append([frm, b, int(c.epoch_ms()) if c.known() else None, lk.now])    # loop's ms


def mins(c):
    # The ship's clock as minutes since 1970, mod 65536 (a hail's send time); None unknown
    return int(c.epoch_ms()) // 60000 & 65535 if c.known() else None


def old(lk, b):
    """A hail its sender's clock says went over a day ago (delivered late): not kept."""
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
    k = [o for o in lk.out if d and o[2] != d]
    if k:
        for o in k:
            lk.out.remove(o)
        lk.n["gone"] += len(k)
        keep(lk)


def flick(lk):
    try:                         # the checks and the light: lvflick.py, per use
        import lvflick
        lvflick.maybe(lk)
    except Exception as e:       # the light is a nicety: never the link's problem
        lk.sh.say("live: no hail light %r" % (e,))
    finally:
        lvship.drop("lvflick")


def dial(lk, b, now):
    """Dial the first ship with a hail waiting that can take one now (Link.poll, idle radio):
    heard in the last L.NEAR, its own next dial due, and none to anyone for L.GAP; sets
    lk.due, the earliest time another look is worth an import. Old items go first."""
    expire(lk)
    due = now + 5000                # nobody in range: look again in 5 s
    for o in lk.out:
        to = o[0]
        p = b.peers.get(to)
        x = lk.nx.get(to) or [0, 0]
        if p is None or p.addr is None or not p.info or not p.info.get("cap") \
                or not p.seen or now - p.seen >= L.NEAR:
            continue
        if p.info["busy"] or now < x[1] or now < lk.gap:
            due = min(due, max(x[1], lk.gap, now + 1000))
            continue
        x[0] += 1
        x[1] = now + (L.FAST if x[0] < 2 else L.EVERY)
        lk.nx[to] = x
        lk.gap = now + L.GAP
        lk.forced = (p, p.fails, p.next_try, lk._for(to))
        lk.n["dial"] += 1
        b._connect(p, now)
        if b.state != "connecting":     # the stack said no: put the backoff back
            f, lk.forced = lk.forced, None
            p.fails, p.next_try = f[1], f[2]
            lk.n["dial_fail"] += 1
        due = 0                         # look again once the radio is idle
        break
    lk.due = due


def done(lk, f, p, s, now):
    """After a session this Link dialled: count it, give the stack its backoff back."""
    ok = s is not None and s.complete()
    lk.n["dial_ok" if ok else "dial_fail"] += 1
    p.fails, p.next_try = f[1], f[2]
    # anything left: the next session, but only if this one moved something (an
    # item the peer won't take, say a bad mac, keeps to the 2-then-1-a-minute dials)
    if ok:
        lk.tf = 0
        k = lk._for(p.ship)
        if 0 < k < f[3]:                # moved some, more for them: straight on (the GAP
            lk.nx[p.ship] = [0, now + 1000]     # is between crewmates, not within one)
            lk.gap = 0
    lk.due = 0
