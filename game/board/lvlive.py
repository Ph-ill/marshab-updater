# Ship-to-ship live items (Hail, 0.3.0) on the existing Bluetooth sync link.
# The resident part: only what every sync runs (the advert, the session hooks, the check
# for a due dial). What runs when items actually move is in lvlivein.py (loaded per use:
# taking items off the air, queueing one, dialling, the box file); install and the fault net are in lvlivex.py; what a
# phone asks for is in lvliveapi.py, loaded per request. Installed by
# board/main.py over the frozen core (2661c2144844) by subclassing and wrapping, never by
# replacing lv/ble.py or lv/sync.py, and never in the radio IRQ handler.
#
# On the air
#   * Items ride as a trailer on the sync HELLO ('H') and DONE ('D') messages. Old ships
#     ignore bytes after what they parse, so a ship without this syncs normally with one
#     that has it; the trailer only goes to a ship whose advert says it reads them (advert
#     ship byte bit 5), and only when there is something to deliver or acknowledge.
#       trailer = MARK, n, then n items of LEN (20) bytes, at most MAXI (6): a HELLO with a
#                 full trailer is 243 B, inside the 16 chunks a message may have at MTU 23.
#       item    = kind, to ship, epoch, seq (2), body (11), mac (4)
#       mac     = sha256(fleet key + from ship + the first 16 bytes)[:4]: only the fleet's
#                 ships can make one; "from" is the ship the session is with.
#     The opener (central) puts its items in its HELLO (it knows whom it dialled); the
#     answerer learns the peer from that HELLO, takes the items and puts the acks and its
#     own items in its HELLO; the opener acks those in its DONE. Kind 0 is an ack: its body
#     is the epoch and seq it acknowledges.
#   * Replays and repeats: each ship numbers its items (seq, on flash, with a random epoch
#     byte chosen when its box file is first made); a receiver keeps the highest (epoch,
#     seq) taken from each ship and acks, but doesn't take again, anything not newer.
#   * Delivery: a ship with an item for crewmate X dials X's last known address directly
#     (no wait for a broadcast), at most twice in the first seconds (the second 5 s
#     later), then once a minute while X was heard in the last 10 minutes. The normal
#     sync's cooldown and failure backoff are put back as they were after these dials, so
#     they never slow ordinary syncing. Any sync with X (either side dialling) carries
#     them too.
#   * Item kinds: 0 ack, 1 hail (body: phrase, back, from crew), 2 "seen" (body: the hail's
#     epoch and seq). Any other kind (a later release's) is acked and dropped, so a newer
#     ship's items never stick in an older ship's queue.
#   * Advert ship byte: bit 5 = this ship reads live items (capability gating: nothing is
#     queued for, dialled to or sent to a ship without it). Bit 6 is kept free.
#   * Coexistence: no hail dial starts while the ship's web server is mid-answer, or within
#     OTA_MS of an update piece arriving from a phone (main.py sets ship.ota_t), so Hail
#     never adds a link to a running upload. Links the other ship opens are as before.
# Kill switches: ON below (a release can turn Hail off fleet-wide over the air), the
# Settings switch (live.json "on"), and the fault net (any crash: off until a phone says).
# Safety: every hooked call is wrapped; on any error the hooks come off (the originals
# back, the session class and advert parser left as plain ones, the link finished as a
# fault), live.json says why, and ordinary syncing carries on. A restart after a crash leaves live features off until a phone turns them back on
# (Settings > Ship-to-ship). The light (lvflick.py) never plays during a link, in quiet
# hours, without a phone's clock since the start, or past the daily allowance (12).
import lvship
from lv import sync as S

MARK = 0xA7
LEN = 20
MAXI = 6
FAST = 5000           # the second dial
EVERY = 60000         # then a waiting item: one dial a minute...
HEARD = 600000        # ...while the peer was heard in the last 10 min
CAP = 32
MAXIN = 24
LIGHTS = 12           # hail flickers a day
OTA_MS = 10000
ON = True             # the fleet-wide kill switch: a release with False turns Hail off
D = "/data"
Session0 = S.Session
parse0 = S.parse_advert


def parse(adv):
    i = parse0(adv)
    if i is not None:
        j = bytes(adv).find(b"\xff\xffLV")
        x = adv[j + 5] if 0 <= j < len(adv) - 5 else 0
        i["cap"] = x & CAP
    return i


class Session(Session0):
    # The node's Link (node.live, set by install) does the work; without one (switched
    # off, or a fault) this is the plain sync session.
    def __init__(self, node, now, size=20, opener=True):
        k = self.lk = getattr(node, "live", None)
        p = k.ble.peer if k is not None and opener else None
        self.to = p.ship if p is not None and p.info and p.info.get("cap") else None
        self.acks = []
        Session0.__init__(self, node, now, size, opener)

    def _send_msg(self, msg, now):
        if self.to is not None and self.lk is not None and (msg[0] == 72 or msg[0] == 68):
            msg += self.lk.trailer(self, msg[0] == 72)
        Session0._send_msg(self, msg, now)

    def _msg(self, m, now):
        k = self.lk
        if k is not None and k.node.live is k:
            if len(m) >= 11 and m[0] == 72:
                if self.to is None and m[2] < 16:
                    self.to = m[2]
                if m[2] == self.to:
                    k.take(self, m, 11 + 2 * m[10])
            elif m[0:1] == b"D" and self.to is not None:
                k.take(self, m, 3)
        Session0._msg(self, m, now)


class Link:
    # Made by lvlivex.setup (its state: the box file read back). Item work is lvlivein's.
    def take(self, s, m, off):
        import lvlivein              # (only when a trailer came: items are rare)
        try:
            lvlivein.take(self, s, m, off)
        finally:
            lvship.drop("lvlivein")

    def trailer(self, s, hello):
        it = s.acks[:MAXI]
        del s.acks[:len(it)]
        if hello:
            for o in self.out:
                if o[0] == s.to and len(it) < MAXI:
                    it.append(o[1])
        if not it:
            return b""
        return bytes((MARK, len(it))) + b"".join(it)

    # ---- hooks: BleSync.poll and _finish, Node.advert
    def advert(self, busy=False):
        a = bytearray(self.adv0(busy))
        a[5] |= CAP
        return bytes(a)

    def web_busy(self):
        w = getattr(self.sh, "web", None)
        if w is not None and w.busy > 0:
            return True
        t = getattr(self.sh, "ota_t", 0)
        return bool(t) and lvship.ticks_diff(lvship.ticks_ms(), t) < OTA_MS

    def poll(self, now):
        b = self.ble
        self.now = now
        try:
            # dialling lives in lvlivein, loaded only when a dial could be due (`due`: the
            # earliest next dial, or a re-check in 1-5 s), so a waiting hail costs no heap
            if self.out and now >= self.due and b.state == "idle" and not self.web_busy():
                import lvlivein
                try:
                    lvlivein.dial(self, b, now)
                finally:
                    lvship.drop("lvlivein")
            self.poll0(now)
        except Exception as e:
            self.fault(e)

    def finish(self, now, why):
        f, self.forced = self.forced, None
        b = self.ble
        p, s = b.peer, b.sess
        try:
            self.fin0(now, why)
        finally:
            if f and f[0] is p:
                import lvlivein
                try:
                    lvlivein.done(self, f, p, s, now)
                finally:
                    lvship.drop("lvlivein")

    def _for(self, to):
        n = 0
        for o in self.out:
            if o[0] == to:
                n += 1
        return n

    def fault(self, e):
        try:
            import lvlivex
            lvlivex.fault(self, e)
        except Exception:            # (no memory for the rest: the hooks off, at least)
            unhook(self)
            self.sh.live = None
            self.sh.live_why = "fault"
        finally:
            lvship.drop("lvlivex")
            lvship.drop("lvlivein")


def unhook(lk):
    b = lk.ble
    for k in ("poll", "_finish"):
        try:
            delattr(b, k)
        except (AttributeError, TypeError):
            pass
    try:
        delattr(lk.node, "advert")
    except (AttributeError, TypeError):
        pass
    lk.node.live = None
    b.adv = None


def install(ship, data=D):
    """-> the Link, or None with ship.live_why saying why live features are off."""
    import lvlivex                  # the checks and hooking up: lvlivex.py, per use
    try:
        return lvlivex.install(ship, data)
    finally:
        lvship.drop("lvlivex")
        lvship.drop("lvlivein")
