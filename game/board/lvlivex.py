# The once-in-a-while parts of lvlive.py (Hail, 0.3.0): install (the checks and the hooks),
# a Link's start (its box file read back), and the fault net. Loaded for each and dropped
# straight after (lvship.drop), so none of it stays resident next to two phones and a sync.
# The box-file helpers (load, save) are lvlivein's, loaded alongside and dropped too.
import lvship
from lv import sync as S
from binascii import unhexlify
import lvlive as L
from lvlivein import load, save


def setup(lk, ship, data, cfg):
    import os
    lk.sh, lk.ble, lk.node = ship, ship.ble, ship.node
    lk.f = data + "/livebox.json"
    lk.cf = data + "/live.json"
    lk.cfg = cfg or {}
    lk.v = 1
    lk.nx = {}            # ship -> [dials, next ms]
    lk.forced = None
    lk.due = 0            # Link.poll: no dial is worth a look before this
    lk.now = 0
    lk.n = {"dial": 0, "dial_ok": 0, "dial_fail": 0, "in": 0, "acked": 0, "dup": 0, "bad": 0, "out": 0}
    b = load(lk.f) or {}
    lk.ep = b.get("e")
    if lk.ep is None:
        lk.ep = os.urandom(1)[0]
    lk.seq = b.get("s", 0)
    lk.out = [[o[0], unhexlify(o[1])] for o in b.get("o", ())]
    lk.inb = [[o[0], unhexlify(o[1])] for o in b.get("i", ())]
    lk.hw = {}
    for k, v in b.get("h", {}).items():
        lk.hw[int(k)] = v
    lk.lc = b.get("l") or [0, 0]


def fault(lk, e):
    sh = lk.sh
    try:
        import sys
        sys.print_exception(e)
    except Exception:
        pass
    why = "fault: %r" % (e,)
    sh.say("live: off after a " + why)
    L.unhook(lk)
    sh.live = None
    sh.live_why = why[:80]
    try:
        c = load(lk.cf) or {}
        c.update({"on": False, "why": why[:80], "at": sh.clock.date()})
        save(lk.cf, c)
    except Exception:
        pass
    try:
        if lk.ble.state != "idle":
            lk.fin0(lk.now, "live fault")
    except Exception:
        pass


def core_ok():
    try:
        import lvfrozen
        if not str(getattr(lvfrozen, "CORE", "")).startswith("2661c2144844"):
            return False
    except ImportError:
        pass                                # a desk run: the sources are the core
    import lv
    o = getattr(lv, "OVERRIDES", ()) or ()
    return "ble" not in o and "sync" not in o


def crash(data):
    """The crash board/lvsafe.py last counted, as a short fingerprint, or None. Only a
    counted crash (fault.json "n" >= 1) counts: lvsafe also writes fault.json for a boot
    note alone ("boot": a file put back, a ship.json that plays but isn't whole), which is
    no reason to turn Hail off. The file is set aside (fault.last.json) after 10 healthy
    minutes, so a crash only turns Hail off at the boot straight after it."""
    j = load(data + "/fault.json")
    if not j:
        return None
    try:
        n = int(j.get("n", 0))
    except (TypeError, ValueError):
        n = 1                               # a count that won't read: take it as a crash
    if n < 1:
        return None
    return ("%s|%s|%s" % (n, j.get("why"), j.get("up")))[:120]


def install(ship, data):
    cf = data + "/live.json"
    c = load(cf) or {}
    why = None
    fx = crash(data)
    # (a phone turned it back on since this very crash: leave it on)
    if fx is not None and c.get("on", True) and c.get("fx") != fx:
        why = "restarted after a fault"
        c.update({"on": False, "why": why, "at": ship.clock.date()})
        save(cf, c)
    if not L.ON:
        why = "paused for the fleet"
    elif not c.get("on", True):
        why = c.get("why") or "turned off"
    elif getattr(ship, "ble", None) is None:
        why = "no Bluetooth"
    elif not core_ok():
        why = "core changed"
    elif getattr(ship, "fk", None) is None:
        why = "no fleet key"
    ship.live_why = why
    ship.live = None
    if why:
        return None
    lk = L.Link()
    setup(lk, ship, data, c)
    b = lk.ble
    lk.poll0, lk.fin0, lk.adv0 = b.poll, b._finish, lk.node.advert
    if b.cfg.get("peer_ttl_ms", 0) < 86400000:
        b.cfg["peer_ttl_ms"] = 86400000     # remember crewmates' addresses for a day
    b.poll, b._finish = lk.poll, lk.finish
    lk.node.advert = lk.advert
    S.Session, S.parse_advert = L.Session, L.parse      # (both stay: plain without a Link)
    b.adv = None                                        # (the advert made again, with the bit)
    lk.node.live = ship.live = lk
    return lk
