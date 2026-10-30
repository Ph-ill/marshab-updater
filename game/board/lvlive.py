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
#     (no wait for a broadcast), but only while X was heard in the last NEAR (30 s, about
#     two scans): twice (the second FAST later), then once a minute. Across all crewmates
#     at most one hail dial every GAP (20 s), so hails waiting for several ships out of
#     range never tie up the one radio (0.3.0 review R2 M1). Of the crewmates that could be
#     dialled, the one whose last hail dial is oldest goes first (never dialled, or back in
#     range after OUT unheard, counts as oldest), and a crewmate that keeps failing (heard, but its
#     ship won't answer) backs off: 1, 2, 4... minutes up to MAXB (10 min), so it can't
#     starve one that just came back (FIXREVIEW2 J1). The normal sync's cooldown and
#     failure backoff are put back as they were after these dials, so they never slow
#     ordinary syncing. Any sync with X (either side dialling) carries them too.
#   * Times are the loop's ticks_ms, which wraps (2**30 ms, about 12.4 days): every comparison here
#     and in lvlivein/lvliveapi goes through dt() (FIXREVIEW2 minor 4).
#   * Each waiting item keeps the day it was queued (the ship's clock.date()); it leaves
#     the queue when a later day starts, delivered or not (the page shows "Didn't go"), so a
#     crewmate who never comes back can't keep a hail or a "seen" waiting for good. A clock
#     set back a day expires nothing (FIXREVIEW3 f2).
#   * Item kinds: 0 ack, 1 hail (body: phrase, back, from crew, the sender's clock when sent
#     as minutes since 1970 mod 65536, big-endian, 0xFFFF unknown), 2 "seen" (body: the
#     hail's epoch and seq). Any other kind (a later release's) is acked and dropped, so a newer
#     ship's items never stick in an older ship's queue.
#   * Advert ship byte: bit 5 = this ship reads live items (capability gating: nothing is
#     queued for, dialled to or sent to a ship without it). Bit 6 = this ship has Hail but
#     it is paused (turned off, after a crash in Hail's own code, the fleet switch): its
#     crewmates' pages say it isn't taking hails right now, not that it needs an update.
#     Bit 7 = its hail light is switched off in Settings: a sender's page says the hail
#     will show as a note only (FIXREVIEW2 J5; 0.2.7 ships ignore bits 5-7).
#   * Coexistence: no hail dial starts while the ship's web server is mid-answer, or within
#     OTA_MS of an update piece arriving from a phone (main.py sets ship.ota_t), so Hail
#     never adds a link to a running upload. Links the other ship opens are as before, but
#     their items aren't taken (nor acked: the other ship sends them again) meanwhile.
# Kill switches: ON below (a release can turn Hail off fleet-wide over the air), the
# Settings switch (live.json "on"), and the fault net: a crash lvsafe counted whose
# traceback names Hail's own modules (fault.json "live") turns it off at the next boot,
# once per crash, until a phone turns it back on (Settings, or the Home card).
# Safety: Hail's own code in every hooked call is wrapped, and only an error raised there
# counts against Hail (FIXREVIEW2 J2). A MemoryError there is taken as passing (nothing
# taken is acked or kept, so the peer sends it again; Hail stays on) up to TRANSIENT in a
# row, the count cleared by any sync that completes; any other error, or more of them, and
# the hooks come off (the originals back, the session class and advert parser left as
# plain ones, the link finished as a fault), live.json says why, and ordinary syncing
# carries on. An error from the core's own sync code is the core's: a MemoryError ends the
# link (TRANSIENT in a row with no good sync between, and it goes on as a crash would
# without Hail), anything else goes on as a crash at once; CORE is set first, so main.py's
# crash note doesn't name Hail for it. The light (lvflick.py) never plays during a link, in
# quiet hours, without a phone's clock since the start, or past the daily allowance (12).
import lvship
from lv import sync as S

MARK = 0xA7
LEN = 20
MAXI = 6
FAST = 20000          # the second dial
EVERY = 60000         # then a waiting item: one dial a minute...
NEAR = 30000          # ...while the peer was heard in the last 30 s
GAP = 20000           # one hail dial at most per 20 s, all crewmates together
TRANSIENT = 3         # MemoryErrors in a row taken as passing
CALM_MS = 600000      # ... "in a row": none for 10 min ends the run, as a good sync does
CAP = 32
PAUSED = 64
NOLIGHT = 128
MAXB = 600000         # a crewmate whose ship keeps failing: dials at most this far apart
OUT = 90000           # not heard for this long: out of range (its dial history starts over)
MAXIN = 24
LIGHTS = 12           # hail flickers a day
OTA_MS = 10000
ON = True             # the fleet-wide kill switch: a release with False turns Hail off
D = "/data"
CORE = 0              # set when an error from the core's sync code goes on as a crash
Session0 = S.Session
parse0 = S.parse_advert


def parse(adv):
    i = parse0(adv)
    if i is not None:
        j = bytes(adv).find(b"\xff\xffLV")
        x = adv[j + 5] if 0 <= j < len(adv) - 5 else 0
        i["cap"] = x & CAP
        i["off"] = x & PAUSED
        i["nl"] = x & NOLIGHT
    return i


def dt(a, b):
    # a - b for the loop's ticks_ms (they wrap at 2**30, about 12.4 days, as lv's
    # ticks_diff: valid within half of that either way)
    return ((a - b + 0x20000000) & 0x3FFFFFFF) - 0x20000000


def due(now, t):
    # a deadline t (0: none) reached; one more than an hour ahead is from before a wrap
    if not t:
        return True
    d = dt(t, now)
    return d <= 0 or d > 3600000


def near(now, p, ms=NEAR):
    return p is not None and bool(p.seen) and 0 <= dt(now, p.seen) < ms


class Session(Session0):
    # The node's Link (node.live, set by install) does the work; without one (switched
    # off, or a fault) this is the plain sync session.
    # Hail's parts never raise into the core's code: an error is kept (Link.hx) and
    # Link.poll takes it to fault() once the core's poll is done.
    def __init__(self, node, now, size=20, opener=True):
        k = self.lk = getattr(node, "live", None)
        self.to = None
        self.acks = []
        try:
            p = k.ble.peer if k is not None and opener else None
            self.to = p.ship if p is not None and p.info and p.info.get("cap") else None
        except Exception as e:
            k.hx = e
        Session0.__init__(self, node, now, size, opener)

    def _send_msg(self, msg, now):
        k = self.lk
        if self.to is not None and k is not None and (msg[0] == 72 or msg[0] == 68):
            try:
                msg += k.trailer(self, msg[0] == 72)
            except Exception as e:
                k.hx = e
        Session0._send_msg(self, msg, now)

    def _msg(self, m, now):
        k = self.lk
        if k is not None and k.node.live is k:
            try:
                if len(m) >= 11 and m[0] == 72:
                    if self.to is None and m[2] < 16:
                        self.to = m[2]
                    if m[2] == self.to:
                        k.take(self, m, 11 + 2 * m[10])
                elif m[0:1] == b"D" and self.to is not None:
                    k.take(self, m, 3)
            except Exception as e:
                k.hx = e
        Session0._msg(self, m, now)


class Link:
    # Made by lvlivex.setup (its state: the box file read back). Item work is lvlivein's.
    def take(self, s, m, off):
        if len(m) < off + 2 or m[off] != MARK:
            return
        if self.ota() or getattr(getattr(self.sh, "web", None), "radio_hold", False):
            # A full game-state answer owns the large working set. Leave the
            # trailer unacknowledged: its durable sender retries after release.
            # Compact /api/live streams do not hold radio receive off.
            self.n["held"] += 1
            return
        z = None
        try:
            # what taking changes in RAM, to put back if it fails part way (a MemoryError
            # saving livebox.json, say): then nothing is acked, nothing counts as taken
            # (no "repeat" when the peer sends it again) and no light (FIXREVIEW2 J3)
            z = (dict(self.hw), self.inb[:], self.out[:], dict(self.n))
            import lvlivein          # (only when a trailer came: items are rare)
            lvlivein.take(self, s, m, off)
        except Exception as e:
            del s.acks[:]            # no acks, so the peer sends them again
            if z is not None:
                self.hw = z[0]
                self.inb[:] = z[1]
                self.out[:] = z[2]
                self.n = z[3]
                # Duel's write-ahead transaction may already have committed a
                # reply before the trailer's final save failed. Recover that
                # durable outbox, not a snapshot predating its publication.
                try:
                    from lvlivein import load
                    from binascii import unhexlify
                    b = load(self.f)
                    if b is not None:
                        self.out[:] = [[o[0], unhexlify(o[1]), o[2]] for o in b.get("o", [])]
                except Exception:
                    pass
            z = None
            if isinstance(e, MemoryError):
                self.n["oom"] += 1   # passing, up to TRANSIENT in a row
                self.calm(self.now)
                self.tf += 1
                if self.tf > TRANSIENT:
                    self.hx = e
            else:
                self.hx = e
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
        a[5] |= CAP if self.cfg.get("light", True) else CAP | NOLIGHT
        return bytes(a)

    def ota(self):
        t = getattr(self.sh, "ota_t", 0)
        return bool(t) and lvship.ticks_diff(lvship.ticks_ms(), t) < OTA_MS

    def web_busy(self):
        w = getattr(self.sh, "web", None)
        return w is not None and w.busy > 0 or self.ota()

    def want(self, now):
        # Worth loading lvlivein: an item past its day (it goes), or one for a crewmate
        # heard in the last NEAR whose ship takes items now (cap: lvlivein.dial's own test).
        # Else a waiting item costs no import at all (one for a paused ship nearby included).
        # A dial that couldn't go now anyway (the GAP, its own next dial, a busy or
        # addressless ship) waits too (FIXREVIEW2 minor 6).
        # An entry in nx to start over (out of range OUT: lvlivein.dial) counts as worth it
        # (once: then it's clear). The GAP for a crewmate not dialled yet: a quarter of it.
        d = self.sh.clock.date()
        g = self.gap
        g4 = due(now, g if not g else g - GAP + GAP // 4)
        g = due(now, g)
        for o in self.out:
            p = self.ble.peers.get(o[0])
            if o[1][0] <= 2 and d and not (isinstance(o[2], int) and o[2] >= d):
                return True
            x = self.nx.get(o[0])
            h = x is not None and len(x) > 3 and (x[2] or x[3])    # (lvlivein.nx pads)
            if h and not near(now, p, OUT):
                return True
            if (g if x is not None and len(x) > 2 and x[2] else g4) and near(now, p) and p.addr is not None \
                    and p.info and p.info.get("cap") and not p.info.get("busy"):
                if x is None or due(now, x[1]):
                    return True

    def poll(self, now):
        b = self.ble
        self.now = now
        try:
            if due(now, self.duel_due) and b.state == "idle" and not self.web_busy():
                self.duel_due = now + 3600000
                import lvlivein
                try:
                    lvlivein.duels(self)
                finally:
                    lvship.drop("lvlivein")
                    lvlivein = None
            # dialling lives in lvlivein, loaded only when a dial could be due (`due`: the
            # earliest next dial, or a re-check in 1-5 s), so a waiting hail costs no heap
            if self.out and due(now, self.due) and b.state == "idle" and not self.web_busy():
                if self.want(now):
                    import lvlivein
                    try:
                        lvlivein.dial(self, b, now)
                    finally:
                        lvship.drop("lvlivein")
                        lvlivein = None
                else:
                    self.due = now + 5000
        except Exception as e:
            self.hx = e
        try:
            self.poll0(now)
        except MemoryError as e:
            # the core's own (Hail's parts in it never raise): not Hail's, so it doesn't
            # count against Hail; the link ends, and a run of them goes on as a crash would
            self.calm(now)
            self.cm += 1
            if self.cm > TRANSIENT:
                core()
                raise
            self.n["oom"] += 1
            self.end("live: core out of memory")
        except Exception:
            core()
            raise
        e, self.hx = self.hx, None
        if e is not None:
            self.fault(e)

    def finish(self, now, why):
        f, self.forced = self.forced, None
        b = self.ble
        p, s = b.peer, b.sess
        try:
            self.fin0(now, why)
            if s is not None and s.complete():
                self.tf = self.cm = 0        # a good sync: no run of errors (FIXREVIEW2 J2)
        except Exception:
            core()
            raise
        finally:
            if f and f[0] is p:
                try:
                    import lvlivein
                    lvlivein.done(self, f, p, s, now)
                except Exception as e:
                    self.hx = e
                finally:
                    lvship.drop("lvlivein")

    def end(self, why):
        try:
            if self.ble.state != "idle":
                self.fin0(self.now, why)
        except Exception:
            pass

    def _for(self, to):
        n = 0
        for o in self.out:
            if o[0] == to:
                n += 1
        return n

    def calm(self, now):
        # a run of MemoryErrors ends at a good sync (finish) or after CALM_MS without one
        if self.et and dt(now, self.et) > CALM_MS:
            self.tf = self.cm = 0
        self.et = now or 1

    def fault(self, e):
        # e: raised in Hail's own code
        if isinstance(e, MemoryError):
            self.calm(self.now)
        if isinstance(e, MemoryError) and self.tf < TRANSIENT:
            self.tf += 1                 # passing (the heap's tightest moment): Hail stays on
            self.n["oom"] += 1
            self.end("live: no memory")
            return
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


def core():
    global CORE
    CORE = 1


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
    pause(lk.node)
    b.adv = None


def pause(node):
    # Hail here but not running: the advert's bit 6 (PAUSED) says so to crewmates' ships
    a0 = node.advert

    def adv(busy=False):
        a = bytearray(a0(busy))
        a[5] |= PAUSED
        return bytes(a)
    node.advert = adv


def install(ship, data=D):
    """-> the Link, or None with ship.live_why saying why live features are off."""
    import lvlivex                  # the checks and hooking up: lvlivex.py, per use
    try:
        return lvlivex.install(ship, data)
    finally:
        lvship.drop("lvlivex")
        lvship.drop("lvlivein")
