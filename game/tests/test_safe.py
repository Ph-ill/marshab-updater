# Safe mode, the fault notes and ship.json written whole (0.2.7, with review #1's fixes).
#   board/lvledcfg.py valid/save/toggle: the Ship light switch writes ship.json as temp file
#     + read back + rename, and only over a whole identity (valid); a failure at any step
#     (simulated) leaves ship.json byte-for-byte and no stray file. Review #1 M1: a read
#     error (EIO, no heap) or a missing ship.json is never replaced by {"led_notify": ...}.
#   board/lvsafe.py: check() at boot (play / safe / off), ship.json and crew.json put back
#     from .new/.old/.bak (M2: a missing ship.json after 0.2.6's .old route), a read error
#     that isn't "no such file" never overwritten (m3), crashed() counting (not on an
#     update's trial; nothing written past SAFE_CAP: m1), healthy(), retry()/rest(), the
#     game tried again on its own (M5), and the safe-mode server: the page, sign-in, /api/me
#     (m10), /api/state 503 {safe, detail} signed in only (m8), /api/ota (lvota), /status,
#     Try the game again.
#   board/main.py: ota_ok keeps an update after OTA_OK_MS and a 2xx to a phone or the ship's
#     own check that it serves the page (m7), crashed() notes (the short way when lvsafe
#     can't: M3) and restarts, task_error() stops the game only for the web server's accept
#     loop (M4), keep() restarts a task, safe mode "off" waits and restarts.
# Runs on CPython and MicroPython (stock and the game firmware's unix build):
#   python3 tests/test_safe.py && micropython tests/test_safe.py        (from game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE)
sys.path.insert(0, HERE + "/board")
import lvweb  # noqa: E402
import lvsafe  # noqa: E402
import lvledcfg  # noqa: E402
from lv import codes as K  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


ROOT = HERE + "/build/safe-test"
D = ROOT + "/data"


def rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rm(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass


def fresh():
    rm(ROOT)
    for p in (ROOT, D):
        try:
            os.mkdir(p)
        except OSError:
            pass


def put(p, t):
    with open(p, "w") as f:
        f.write(t)


def get(p):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None


def files():
    return sorted(os.listdir(D))


SHIP = '{"ship_id": 5, "ship_name": "Test", "hotspot_password": "not-a-real-one", "led_notify": false}'


# ---- lvledcfg: ship.json written whole, only over a whole identity ----------------------
V = lvledcfg.valid
check("valid: a ship", V(json.loads(SHIP)))
check("valid: ship_id as text", V({"ship_id": "3", "hotspot_password": "12345678"}))
check("valid: open hotspot", V({"ship_id": 2, "hotspot_open": True}))
check("valid: the updater's firmware-default password (none written)", V({"schema": 2, "ship_id": 3, "hotspot_open": False}))
for bad in (None, [1], {}, {"led_notify": True}, {"hotspot_password": "12345678"}, {"ship_id": True, "hotspot_password": "12345678"},
            {"ship_id": 9, "hotspot_password": "12345678"}, {"ship_id": 0, "hotspot_password": "12345678"},
            {"ship_id": 3, "hotspot_password": "short"}, {"ship_id": 3, "hotspot_password": 12345678},
            {"ship_id": "x", "hotspot_password": "12345678"}):
    check("not valid: %r" % (bad,), not V(bad))


class FakeShip:
    def __init__(self):
        self.v = 0
        self.said = []
        self.on = False

    def led_on(self, on):
        self.on = on
        return on

    def say(self, s):
        self.said.append(s)


class FakePhone:
    def __init__(self):
        self.ship = FakeShip()
        self.data = D


def raiser(where, e):
    def f(w):
        if w == where:
            raise e
    return f


fresh()
P = D + "/ship.json"
put(P, SHIP)
ph = FakePhone()
check("toggle on", lvledcfg.toggle(ph, True) is True)
c = json.loads(get(P))
check("led_notify saved", c["led_notify"] is True)
check("the rest kept", c["ship_id"] == 5 and c["hotspot_password"] == "not-a-real-one" and c["ship_name"] == "Test")
check("no stray files", files() == ["ship.json"], files())
for where in ("write", "read", "rename"):
    before = get(P)
    lvledcfg.fail = raiser(where, OSError("simulated " + where))
    lvledcfg.toggle(ph, where != "write")
    lvledcfg.fail = None
    check("fail at %s: ship.json as it was" % where, get(P) == before)
    check("fail at %s: no stray files" % where, files() == ["ship.json"], files())
    check("fail at %s: said so" % where, ph.ship.said[-2] == "led: setting not saved", ph.ship.said[-2:])
# Review #1 M1: a read of ship.json that fails for a reason other than "no such file" (a
# damaged block: EIO; no heap: MemoryError) used to be taken as "no ship.json" and the file
# replaced by {"led_notify": ...}: the next boot was ship 1 on the public placeholder hotspot.
for e in (OSError(5, "EIO"), MemoryError()):
    before = get(P)
    lvledcfg.fail = raiser("open", e)
    check("M1 %r: the switch still switches" % (e,), lvledcfg.toggle(ph, True) is True and ph.ship.on is True)
    lvledcfg.fail = None
    check("M1 %r: ship.json byte-for-byte" % (e,), get(P) == before and json.loads(get(P))["hotspot_password"] == "not-a-real-one")
    check("M1 %r: no stray files" % (e,), files() == ["ship.json"], files())
    check("M1 %r: said so" % (e,), "not whole" in ph.ship.said[-2], ph.ship.said[-2:])
put(P, '{"ship_id": 5, "hotspot_pass')            # a half-written file (what 0.2.6 could leave)
lvledcfg.toggle(ph, True)
check("unreadable ship.json left alone", get(P) == '{"ship_id": 5, "hotspot_pass')
check("unreadable: said", "not whole" in ph.ship.said[-2], ph.ship.said[-2:])
for t in ('{"led_notify": false}', '{"ship_name": "x"}', '{"ship_id": 3, "hotspot_password": ""}', "[1, 2]"):
    put(P, t)
    lvledcfg.toggle(ph, True)
    check("not an identity left alone: " + t, get(P) == t and files() == ["ship.json"], files())
rm(P)
lvledcfg.toggle(ph, True)
check("M1: no ship.json: none written", files() == [], files())
check("the password never in what the ship says", not any("not-a-real-one" in s for s in ph.ship.said))
check("lvledcfg dropped after the switch", "lvledcfg" not in sys.modules)
import lvledcfg  # noqa: E402,F811

# ---- lvsafe.check / crashed / healthy / retry ------------------------------------------
fresh()
said = []
n_ = lambda: lvsafe.count(lvsafe.faults(D))   # noqa: E731
check("nothing: play", lvsafe.check(False, D, said.append) is None)
check("nothing: nothing written", files() == [], files())
put(P, SHIP)
check("ship.json fine: play", lvsafe.check(False, D, said.append) is None)
check("ship.json fine: backed up at boot (m5)", json.loads(get(P + ".bak")) == json.loads(SHIP))
t = get(P + ".bak")
lvsafe.fail = raiser("write", OSError("no writes please"))
check("same again: play, no write", lvsafe.check(False, D, said.append) is None and get(P + ".bak") == t)
lvsafe.fail = None
lvsafe.crashed("ValueError: x", False, 1234, D)
check("one crash: play", n_() == 1 and lvsafe.check(False, D) is None)
lvsafe.crashed("ValueError: y", True, 1234, D)
check("a trial crash isn't counted", n_() == 1)
lvsafe.crashed("MemoryError: memory allocation failed, allocating 4096 bytes", False, 99, D)
w = lvsafe.check(False, D)
check("two in a row: safe mode, the kind only", w == "safe: 2 crashes in a row (MemoryError)", w)
check("the why kept short", len(lvsafe.faults(D)["why"]) <= 64)
check("on trial: play (lvboot decides)", lvsafe.check(True, D) is None)
lvsafe.retry(D)
check("try again: one more go", n_() == 1 and lvsafe.check(False, D) is None)
check("by hand: no auto try counted", lvsafe.faults(D).get("tries") == 0 and lvsafe.retry_ms(D) == lvsafe.RETRY_MS[0])
lvsafe.crashed("TypeError: z", False, 5, D)
lvsafe.retry(D, True)
check("on its own: tries counted, the next wait longer", lvsafe.faults(D)["tries"] == 1 and lvsafe.retry_ms(D) == lvsafe.RETRY_MS[1])
for _ in range(9):
    lvsafe.retry(D, True)
check("the wait stops growing", lvsafe.retry_ms(D) == lvsafe.RETRY_MS[-1])
# m1: a safe mode that keeps stopping is counted up to SAFE_CAP, then "off", and no more writes
lvsafe.rest(D)
check("rest: safe mode", n_() == lvsafe.SAFE_AFTER and (lvsafe.check(False, D) or "").startswith("safe:"))
for i in range(lvsafe.SAFE_CAP + 3):
    lvsafe.crashed("RuntimeError: loop", False, 1, D)
check("m1: counted up to SAFE_CAP", n_() == lvsafe.SAFE_CAP)
w = lvsafe.check(False, D)
check("m1: then off", w == "off: safe mode stopped 3 times in a row", w)
hits = []
lvsafe.fail = hits.append
lvsafe.crashed("RuntimeError: loop", False, 1, D)
lvsafe.fail = None
check("m1: past the cap nothing written", "write" not in hits and n_() == lvsafe.SAFE_CAP, hits)
lvsafe.rest(D)
check("m1: after off, safe mode once more", (lvsafe.check(False, D) or "").startswith("safe: 2 crashes"))
# m2: a failed note is tried once more
rm(D + "/fault.json")
first = [1]


def once(w):
    if w == "rename" and first:
        first.pop()
        raise OSError("once")


lvsafe.fail = once
lvsafe.crashed("ValueError: q", False, 1, D)
lvsafe.fail = None
check("m2: the note is tried again", n_() == 1)
rm(D + "/fault.json")
check("ship.json backed up", json.loads(get(P + ".bak")) == json.loads(SHIP))
put(P, '{"ship_id": 5, "hots')
check("broken ship.json + backup: put back, play", lvsafe.check(False, D, said.append) is None
      and json.loads(get(P)) == json.loads(SHIP))
check("said where from", said[-1] == "safe: ship.json not usable, put back from ship.json.bak", said[-1:])
put(P, "[1, 2]")
check("not an object counts as broken", lvsafe.check(False, D, said.append) is None and json.loads(get(P))["ship_id"] == 5)
put(P, '{"led_notify": true}')
check("not a whole identity (what 0.2.6's toggle could leave) + backup: put back",
      lvsafe.check(False, D, said.append) is None and json.loads(get(P)) == json.loads(SHIP))
# Review #1 M2: 0.2.6's crew.json-style route (move ship.json to .old, rename .new in) cut
# between its two renames leaves no ship.json at all: the ship came up as ship 1 on the
# public placeholder hotspot. Now it is put back from .old (or .new, or .bak).
SHIP2 = SHIP.replace('"Test"', '"Two"')
for have in ((".old",), (".new",), (".new", ".old"), (".bak",)):
    fresh()
    for x in have:
        put(P + x, SHIP2 if x != ".bak" else SHIP)
    if have == (".new", ".old"):
        put(P + ".new", '{"ship_id": 5, "ho')           # the .new cut short: .old it is
    check("M2 missing, %s: play" % "+".join(have), lvsafe.check(False, D, said.append) is None, said[-1:])
    want = SHIP if have == (".bak",) else SHIP2
    check("M2 missing, %s: put back" % "+".join(have), json.loads(get(P)) == json.loads(want), get(P))
    check("M2 missing, %s: said" % "+".join(have), said[-1].startswith("safe: ship.json missing, put back from"), said[-1:])
    check("M2 missing, %s: .old gone, .bak made" % "+".join(have), not lvsafe.exists(P + ".old") and lvsafe.exists(P + ".bak"), files())
fresh()
put(P + ".new", '{"ship_id": 5, "ho')
w = lvsafe.check(False, D)
check("missing, only a broken trace: off", (w or "").startswith("off: ship.json missing"), w)
fresh()
put(P, '{"ship_name": "x"}')
check("a bench board's own (not whole) settings, nothing to put back: play, left alone",
      lvsafe.check(False, D) is None and get(P) == '{"ship_name": "x"}')
put(P, "{bad")
check("broken, no backup, a board never set up (no crew.json): plays the defaults, as 0.2.6 (review #3 M1)",
      lvsafe.check(False, D) is None)
put(D + "/crew.json", "{}")
w = lvsafe.check(False, D)
check("broken, no backup, a crew ship: off", w is not None and w.startswith("off:"), w)
check("off even on trial", (lvsafe.check(True, D) or "").startswith("off:"))
check("no stray .new", [f for f in files() if f.endswith(".new")] == [], files())
check("review #3 M1: the reason is in fault.json", lvsafe.faults(D).get("boot") == w, lvsafe.faults(D))
rm(D + "/crew.json")
rm(D + "/fault.json")
# m3: a read error that isn't "no such file", with nothing to put back, is "off" for now
# and never written over (every file unreadable here: the .bak too)
put(P, SHIP)
lvsafe.check(False, D)
put(P + ".bak", SHIP2)
for e in (OSError(5, "EIO"), MemoryError()):
    lvsafe.fail = raiser("open", e)
    w = lvsafe.check(False, D, said.append)
    lvsafe.fail = None
    check("m3 %r: off, looking again" % (e,), (w or "").startswith("off: ship.json unreadable and nothing to put back"), w)
    check("m3 %r: ship.json untouched" % (e,), get(P) == SHIP and get(P + ".bak") == SHIP2)
# Review #2 M4: a ship.json that stays unreadable (littlefs gives a damaged block
# LFS_ERR_CORRUPT, OSError 84, on every read) with a good .bak was "off" on every boot,
# forever: no hotspot, so no update either. Now: looked at again after a pause, then put
# back from the .bak (refreshed at every boot, so at most this boot's changes behind).
real_open = open


def bad_open(path, *a, **k):
    if path.endswith("/ship.json"):
        raise OSError(84)
    return real_open(path, *a, **k)


def sticky(fn):
    # ship.json unreadable until it is written over (as a damaged block until the rename)
    lvsafe.open = bad_open
    try:
        return fn()
    finally:
        del lvsafe.open


for have in (".bak", ".new"):
    fresh()
    put(P, SHIP)
    lvsafe.check(False, D)
    if have == ".new":
        rm(P + ".bak")
        put(P + ".new", SHIP2)
    got = []
    w = sticky(lambda: lvsafe.check(False, D, said.append, got))
    check("M4 unreadable, good %s: play" % have, w is None, w)
    want = SHIP if have == ".bak" else SHIP2
    check("M4 unreadable, good %s: put back" % have, json.loads(get(P)) == json.loads(want), get(P))
    check("M4 unreadable, good %s: said so" % have, said[-1] == "safe: ship.json unreadable, put back from ship.json" + have, said[-1:])
    check("M4 unreadable, good %s: cfg from it" % have, got == [json.loads(want)], got)
    check("M4 unreadable, good %s: no stray files" % have, files() == ["fault.json", "ship.json", "ship.json.bak"], files())
    check("M4 unreadable, good %s: noted in fault.json (review #3 M1)" % have,
          lvsafe.faults(D) == {"boot": "ship.json unreadable, put back from ship.json" + have}, lvsafe.faults(D))
fresh()
put(P, SHIP)
check("M4 unreadable on a board never set up (no crew.json): the defaults, as 0.2.6",
      sticky(lambda: lvsafe.check(False, D, said.append)) is None)
put(D + "/crew.json", "{}")
w = sticky(lambda: lvsafe.check(False, D, said.append))
check("M4 unreadable, nothing to put back: off", (w or "").startswith("off: ship.json unreadable"), w)
rm(D + "/crew.json")
check("M4 unreadable, nothing to put back: untouched", get(P) == SHIP)
flaky = [1]


def flake(w):
    if w == "open" and flaky:
        flaky.pop()
        raise OSError(5, "EIO")


lvsafe.fail = flake
check("m3: an error that passes on the second look: play", lvsafe.check(False, D) is None and get(P) == SHIP)
lvsafe.fail = None
# m4: crew.json put back too (never "off": safe mode signs in from it)
C = D + "/crew.json"
CREW = json.dumps(K.make_config(["1234"] + [None] * 7, b"safe-test-salt16"))
put(C, CREW)
lvsafe.check(False, D)
check("m4: crew.json backed up", json.loads(get(C + ".bak")) == json.loads(CREW))
put(C, '{"salt": "ab')
check("m4: broken crew.json put back", lvsafe.check(False, D, said.append) is None and json.loads(get(C)) == json.loads(CREW))
rm(C)
rm(C + ".bak")
put(C + ".old", CREW)
check("m4: missing crew.json from 0.2.6's .old", lvsafe.check(False, D) is None and json.loads(get(C)) == json.loads(CREW)
      and not lvsafe.exists(C + ".old"))
rm(C + ".bak")
put(C, "{bad")
check("m4: broken crew.json, nothing to put back: still play", lvsafe.check(False, D) is None)
# Review #2 M3 (rv2/order.py, wear.py): "only when it differs" compared json.dumps text,
# and a MicroPython dict's key order isn't the file's, so both .bak files were rewritten at
# every boot there. Compared as objects now: count the writes over boots, on every port.
fresh()
SHIPW = ('{"ship_id": 5, "hotspot_password": "xxxxxxxxxxxx", "fleet_key": "00112233445566778899aabbccddeeff", '
         '"launch_date": "2026-09-01", "ota_src": "ota-phonetest", "led_notify": true, "bat_chg_pull": "none", '
         '"country": "US", "channel": 6, "ssid_prefix": "LV-", "http_port": 80, "captive_dns": true}')
put(P, SHIPW)
put(C, CREW)
hits = []
lvsafe.fail = hits.append
lvsafe.check(False, D, said.append)
first_boot = hits.count("write")
writes = []
for boot in range(4):
    hits[:] = []
    lvsafe.check(False, D, said.append)
    writes.append(hits.count("write"))
lvsafe.fail = None
check("M3: the first boot writes both backups", first_boot == 2, first_boot)
check("M3: later boots write nothing (%s)" % sys.implementation.name, writes == [0, 0, 0, 0], writes)
check("M3: files as they were", get(P) == SHIPW and files() == ["crew.json", "crew.json.bak", "ship.json", "ship.json.bak"], files())
put(P, SHIPW.replace('"led_notify": true', '"led_notify": false'))
hits[:] = []
lvsafe.fail = hits.append
lvsafe.check(False, D, said.append)
lvsafe.fail = None
check("M3: a real change is backed up (one write)", hits.count("write") == 1 and json.loads(get(P + ".bak"))["led_notify"] is False, hits)

# Review #2 M5 (rv2/new_repro.py): putting ship.json back from .new went through save(),
# which writes ship.json.new, the very file it was restoring from, and removes it on a
# failure: the only good copy gone, and the next boot a fake ship 1. Now .new and .old are
# renamed into place (nothing rewritten), and .bak is copied through ship.json.bak.new.
fresh()
put(P + ".new", SHIP2)
put(C, CREW)
first = [1]


def restore_fails_once(w):
    if w == "restore" and first:
        first.pop()
        raise OSError(28)                       # ENOSPC, once, on the restore's rename
lvsafe.fail = restore_fails_once
w = lvsafe.check(False, D, said.append)
lvsafe.fail = None
check("M5: a failed restore from .new: off for now", (w or "").startswith("off: ship.json missing"), w)
check("M5: ... and .new still there, whole", get(P + ".new") == SHIP2, files())
w = lvsafe.check(False, D, said.append)
check("M5: the next boot puts it back", w is None and json.loads(get(P)) == json.loads(SHIP2) and not lvsafe.exists(P + ".new"), (w, files()))
fresh()
put(P + ".bak", SHIP)
put(P + ".new", '{"ship_id": 5, "ho')            # a .new cut short
lvsafe.fail = raiser("rename", OSError(28))
w = lvsafe.check(False, D, said.append)
lvsafe.fail = None
check("M5: a failed copy from .bak: off, .bak whole", (w or "").startswith("off:") and get(P + ".bak") == SHIP, (w, files()))
check("M5: ... through its own temp file (no .bak.new left)", not lvsafe.exists(P + ".bak.new"), files())
check("M5: then put back", lvsafe.check(False, D, said.append) is None and json.loads(get(P)) == json.loads(SHIP))
# M5 part 2: 'set up for a crew' no longer hangs on files a restore can delete. Every crew
# ship has crew.json; a missing ship.json next to one is "off", never the defaults.
for f in ("crew.json", "crew.json.bak", "crew.json.old"):
    fresh()
    put(D + "/" + f, CREW)
    w = lvsafe.check(False, D, said.append)
    check("M5: no ship.json, no traces of it, but %s: off" % f, (w or "").startswith("off: ship.json missing"), w)
fresh()
check("M5: a bench board with nothing at all still plays", lvsafe.check(False, D, said.append) is None)
# Review #2 m2: a ship damaged by 0.2.6's toggle ({"led_notify": ...} alone) arrives with no
# .bak: it played as ship 1 on the placeholder hotspot. With crew.json it is "off".
fresh()
put(C, CREW)
put(P, '{"led_notify": true}')
w = lvsafe.check(False, D, said.append)
check("m2: identity-less ship.json on a crew ship, nothing to put back: off", (w or "").startswith("off: ship.json not usable"), w)
check("m2: ... left as it is", get(P) == '{"led_notify": true}')
rm(C)
rm(C + ".bak")
got = []
check("m2: the same on a bench board (no crew.json): plays its own settings", lvsafe.check(False, D, said.append, got) is None
      and got == [{"led_notify": True}], got)
# Review #2 m3 (rv2/guard_repro.py D): a stale .old (a power cut after a restore, or 0.2.6)
# came back ahead of the fresher .bak. Leftovers next to a good file go; .bak before .old.
CREWb = json.dumps(K.make_config(["4321"] + [None] * 7, b"safe-test-salt16"))
fresh()
put(P, SHIP)
put(C, CREWb)
put(C + ".old", CREW)
put(P + ".new", SHIP2)
lvsafe.check(False, D, said.append)
check("m3: leftovers next to good files removed", files() == ["crew.json", "crew.json.bak", "ship.json", "ship.json.bak"], files())
check("m3: said so", "safe: a leftover crew.json.old removed" in said and "safe: a leftover ship.json.new removed" in said, said[-4:])
rm(C)
put(C + ".old", CREW)                           # (a stale .old again, written after)
lvsafe.check(False, D, said.append)
check("m3: crew.json lost: the .bak (newer codes), not the stale .old", json.loads(get(C)) == json.loads(CREWb))
check("m3: and the .old went once crew.json was good", not lvsafe.exists(C + ".old"), files())
lvsafe.check(False, D, said.append)
check("m3: ...on the next boot", not lvsafe.exists(C + ".old"), files())
fresh()
put(C, CREW)

# Review #2 m7: crew_ok is codes.load's own rule, so a crew.json the game can't sign in
# from never becomes the .bak
CK = json.loads(CREW)
check("m7: a crew.json codes.load takes", lvsafe.crew_ok(CK))
for bad, why in ((dict(CK, codes=["ab"] * 8), "short codes"), (dict(CK, codes=[1] * 8), "numbers"),
                 (dict(CK, salt="zz" * 16), "salt not hex"), (dict(CK, salt="ab" * 4), "salt short"),
                 (dict(CK, codes="ab"), "codes not a list"), (dict(CK, codes=CK["codes"][:7] + ["ab"]), "a short 8th")):
    check("m7: not good: " + why, not lvsafe.crew_ok(bad))
from binascii import unhexlify  # noqa: E402
# Review #3 m7: exactly 8 codes was stricter than codes.load (any count: fewer means the
# rest have none, more are ignored), so a crew.json the game signs in from was never
# backed up. Every shape codes.load takes is good now, every code cleared included.
for good, why in ((dict(CK, codes=CK["codes"][:7]), "7 codes"), (dict(CK, codes=CK["codes"][:1]), "1 code"),
                  (dict(CK, codes=CK["codes"] + ["junk"]), "a 9th (ignored by codes.load)"),
                  (dict(CK, codes=[None] * 8), "every code cleared"), ({"salt": CK["salt"]}, "no codes key")):
    check("m7: good: " + why, lvsafe.crew_ok(good))
    put(C + ".x", json.dumps(good))
    b = K.load(C + ".x")
    check("m7: ... and codes.load takes it (%s)" % why, b.salt == unhexlify(CK["salt"]))
rm(C + ".x")
put(C, json.dumps(dict(CK, codes=["ab"] * 8)))
put(C + ".bak", CREW)
lvsafe.check(False, D)
check("m7: an unloadable crew.json put back from .bak, never backed up",
      json.loads(get(C)) == CK and json.loads(get(C + ".bak")) == CK)
put(P, SHIP)
lvsafe.fail = lambda wh: (_ for _ in ()).throw(OSError("x")) if wh == "rename" else None
check("save fails cleanly", lvsafe.save(D + "/fault.json", "{}") is False and not lvsafe.exists(D + "/fault.json.new"))
lvsafe.fail = None


# ---- the safe-mode server --------------------------------------------------------------
class W:
    def __init__(self):
        self.b = b""

    def write(self, d):
        self.b += bytes(d)

    async def drain(self):
        pass


def req(method, path, body=b"", tok=None):
    r = lvweb.Req()
    r.method = method
    path, _, q = path.partition("?")
    r.path = path
    r.q = lvweb.parse_query(q)
    r.hdr = {"user-agent": "t"}
    if tok:
        r.hdr["x-crew-token"] = tok
    r.body = body
    r.peer = "192.168.4.2"
    return r


def call(web, *a, **k):
    w = W()
    asyncio.run(web.route(req(*a, **k), w))
    head, _, body = w.b.partition(b"\r\n\r\n")
    code = int(head.split(b" ")[1])
    try:
        return code, json.loads(body)
    except ValueError:
        return code, body


fresh()
os.chdir(ROOT)
# a crew.json as the updater writes it (lv/codes.py), crew 0 with code 1234
put(D + "/crew.json", CREW)
put(D + "/fault.json", '{"n": 2, "why": "MemoryError: allocating 4096 bytes in lvphone"}')
os.mkdir("www")
put("www/app.html.gz", "page")
boots = []
cfg = {"ship_id": 5, "http_port": 80, "captive_dns": True}
web, sh = lvsafe.server(lvweb, cfg, "2 crashes in a row (MemoryError)", "192.168.4.1", lambda: boots.append(1),
                        D, ROOT + "/")
code, b = call(web, "GET", "/")
check("safe: the page", code == 200 and b == b"page", (code, b))
code, b = call(web, "GET", "/status")
check("safe: status says so", code == 200 and b.startswith(b"SAFE 2 crashes"), b)
check("m8: status has the kind only", b"4096" not in b and b"lvphone" not in b, b)
code, b = call(web, "GET", "/api/crew")
check("safe: crew + why", code == 200 and b["set"][0] is True and b["set"][1] is False and "MemoryError" in b["safe"], b)
check("m8: crew has the kind only", "4096" not in json.dumps(b) and "detail" not in b, b)
check("M5: no retry time before it is set", b["retry_s"] is None, b)
code, b = call(web, "GET", "/api/state")
check("safe: state signed out", code == 401)
code, b = call(web, "GET", "/api/me")
check("m10: /api/me signed out", code == 401)
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "0000"}')
check("safe: wrong code", code == 403 and b["left"] >= 1, (code, b))
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "1234"}')
check("safe: sign in", code == 200 and b["crew"] == 0, (code, b))
tok = b["token"]
code, b = call(web, "GET", "/api/me")
check("m10: a reload stays signed in (/api/me)", code == 200 and b["crew"] == 0 and b["token"] == tok, (code, b))
code, b = call(web, "GET", "/api/state", tok=tok)
check("safe: state 503 {safe}", code == 503 and "MemoryError" in b["safe"], (code, b))
check("m8: signed in, the crash's own words", b.get("detail") == "MemoryError: allocating 4096 bytes in lvphone", b)
code, b = call(web, "POST", "/api/act", b"{}", tok=tok)
check("safe: no game", code == 503)
code, b = call(web, "GET", "/api/ota")
check("safe: the update status", code == 200 and b.get("ota") == 1, (code, b))
check("lvota dropped", "lvota" not in sys.modules)
code, b = call(web, "POST", "/api/ota/cancel")
check("safe: update writes need sign-in", code == 401)
# 0.3.0 review R1 M2: safe mode's upload goes to lvotap; if that won't load (damaged, or a
# broken copy ahead of it), lvota.api answers instead of the request dying unanswered
_sh = ROOT + "/shadow"
os.mkdir(_sh)


def shadowed(src, t=None):
    put(_sh + "/lvotap.py", src)
    sys.path.insert(0, _sh)
    sys.modules.pop("lvotap", None)
    if sys.implementation.name == "cpython":
        import importlib
        importlib.invalidate_caches()
    said = []
    _say, sh.say = sh.say, said.append
    try:
        code, b = call(web, "POST", "/api/ota/put?f=0&n=10&o=0", b"x", tok=tok if t is None else t)
    finally:
        sh.say = _say
        sys.path.remove(_sh)
        sys.modules.pop("lvotap", None)
    return code, b, said


# 0.3.0 fix review FR1 m3: whatever goes wrong loading it, a clear answer the page doesn't
# retry as "busy" (500 DAMAGED; before, only ImportError was caught here, and lvota.api's
# own answer was a 503 the page called "busy")
code, b, _said = shadowed("raise ImportError('damaged')\n")
check("R1 M2 / FR1 m3: safe mode, lvotap won't load: 500, says it's damaged", code == 500
      and b["err"] == lvsafe.DAMAGED and "damaged" in b["err"] and "USB" in b["err"], (code, b))
check("R1 M2: ... and says why in the log", _said and "upload code ImportError" in _said[0], _said)
check("R1 M2: ... nothing left loaded", "lvotap" not in sys.modules and "lvota" not in sys.modules)
for _src, _e in (("x = (\n", "SyntaxError"), ("raise ValueError('x')\n", "ValueError"),
                 ("async def api(web, req, w):\n    raise KeyError('k')\n", "KeyError"),
                 ("api = None\n", "TypeError")):
    code, b, _said = shadowed(_src)
    check("FR1 m3: lvotap %s: 500 damaged, not retried" % _e, code == 500 and b["err"] == lvsafe.DAMAGED,
          (code, b))
    check("FR1 m3: ... logged as %s" % _e, _said and _said[0] == "safe: upload code " + _e, _said)
    check("FR1 m3: ... nothing left loaded (%s)" % _e, "lvotap" not in sys.modules and "lvota" not in sys.modules)
code, b, _said = shadowed("raise MemoryError('memory allocation failed')\n")
check("FR1 m3: out of heap loading it: 503 busy (worth a retry)", code == 503 and b["err"] == "busy", (code, b))
code, b, _said = shadowed("raise ValueError('x')\n", t="nope")
check("FR1 m3: signed out: 401, not the damage", code == 401, (code, b))
rm(_sh)
code, b = call(web, "POST", "/api/safe/retry")
check("safe: retry needs sign-in", code == 401)
code, b = call(web, "GET", "/hotspot-detect.html")
check("safe: captive probe to the page", code == 302)
code, b = call(web, "POST", "/api/logout", b"{}", tok=tok)
code2, b2 = call(web, "GET", "/api/me")
check("m10: signed out after Sign out", code == 200 and code2 == 401, (code, code2))
code, b = call(web, "POST", "/api/login", b'{"crew": 0, "pin": "1234"}')
tok = b["token"]
from lv.clock import ticks_ms  # noqa: E402
sh.retry = (ticks_ms(), 60000)
code, b = call(web, "GET", "/api/crew")
check("M5: when the game is tried again", 58 <= b["retry_s"] <= 60, b)
code, b = call(web, "GET", "/api/state", tok=tok)
check("M5: in the signed-in 503 too", 58 <= b["retry_s"] <= 60, b)


async def retry():
    w = W()
    await web.route(req("POST", "/api/safe/retry", b"{}", tok), w)
    await asyncio.sleep(1.2)
    return w.b


b = asyncio.run(retry())
check("safe: retry 200 then restart", b.startswith(b"HTTP/1.0 200") and boots == [1], (b[:20], boots))
check("safe: retry left one more go", lvsafe.count(lvsafe.faults(D)) == 1)
lvsafe.rest(D)
boots = []
asyncio.run(lvsafe.auto_retry(sh, 50, lambda: boots.append(1)))
j = lvsafe.faults(D)
check("M5: on its own: restarts with one more go", boots == [1] and lvsafe.count(j) == 1 and j["tries"] == 1, (boots, j))
check("M5: and the next wait is longer", lvsafe.retry_ms(D) == lvsafe.RETRY_MS[1])
# m7: the ship's own check that it serves the page (main.serves), against the safe server
src = open(HERE + "/board/main.py").read()
src = src[:src.index("\nT0 = time.ticks_ms()")]
g = {"__name__": "main_test"}
exec(src, g)
web.ok2xx = 7
web.served, sh.http_hits = 3, 4
# safe mode's start() runs main.py's net_hooks, which sets lvweb.MAX_BODY to a whole upload
# piece (1 KB); the upload probe sends one (FR1 m1)
_mb0 = lvweb.MAX_BODY
lvweb.MAX_BODY = 1024
check("m7: the safe server serves the page", asyncio.run(g["serves"](web)) is True)
check("m7: the counts a phone moves left as they were", (web.ok2xx, web.served, sh.http_hits) == (7, 3, 4),
      (web.ok2xx, web.served, sh.http_hits))


class AP:
    # the hotspot as network.WLAN(AP_IF) shows it
    def __init__(self, on, essid):
        self.on, self.essid = on, essid

    def active(self):
        return self.on

    def config(self, k):
        return self.essid


class Srv:
    def __init__(self, done):
        self.task = self

    def done(self):
        return self.d


cfg["ssid_prefix"] = "LV-"
web.ap = AP(True, "LV-5")
web.srv = Srv(False)
web.srv.d = False
check("M1: hotspot up as LV-5, server listening: serves", asyncio.run(g["serves"](web)) is True)
web.ap = AP(False, "LV-5")
check("M1: hotspot down: no keep", asyncio.run(g["serves"](web)) is False)
web.ap = AP(True, "LV-1")
check("M1: hotspot up as another ship (a fake ship 1): no keep", asyncio.run(g["serves"](web)) is False)
web.ap = AP(True, "LV-5")
web.srv.d = True
check("M1: the accept loop has stopped: no keep", asyncio.run(g["serves"](web)) is False)
web.srv.d = False
# Review #3 m3: the SSID readback is only a cross-check. A core whose AP config("essid")
# raises, answers bytes or nothing still serves (an endless trial otherwise); a readback
# that names another ship (a fake ship 1) still doesn't.
for e, yes in ((b"LV-5", True), ("", True), (None, True), (b"", True), (b"LV-1", False), ("LV-15", False)):
    web.ap = AP(True, e)
    check("m3: an AP up reading back %r: %s" % (e, "serves" if yes else "no keep"), asyncio.run(g["serves"](web)) is yes)


class APx(AP):
    def config(self, k):
        raise ValueError("unknown config param")
web.ap = APx(True, "LV-5")
check("m3: a readback that raises: serves", asyncio.run(g["serves"](web)) is True)
web.ap = APx(False, "LV-5")
check("m3: ... but not with the AP down", asyncio.run(g["serves"](web)) is False)
web.ap = AP(True, "LV-5")
# Review #3 m2: a phone's own request while the check runs (the page streams and lets
# it in) keeps its counts: only what the probes added comes off
web.served, sh.http_hits = 3, 4


async def with_phone():
    ph = W()
    r = await asyncio.gather(g["serves"](web), web.handle(g["Sink"](b"GET /api/crew HTTP/1.0\r\n\r\n"), ph))
    return r[0]
check("m2: serves with a phone's request alongside", asyncio.run(with_phone()) is True)
check("m2: ... the phone's request still counted", (web.served, sh.http_hits) == (4, 5), (web.served, sh.http_hits))
web.served, sh.http_hits = 3, 4
# Review #3 m1 (POST-side check): the update must still refuse an unsigned write. An
# update whose /api/ota/put lets anyone in (here: who() says crew 0 to everyone) is not kept.
web.phone.who = lambda req: 0
check("m1: /api/ota/put open to anyone: no keep", asyncio.run(g["serves"](web)) is False)
del web.phone.who
check("m1: ... and refused again: serves", asyncio.run(g["serves"](web)) is True)
# 0.3.0 fix review FR1 m1: the upload route is probed even after a phone's 2xx (main.PUT),
# with a full 1 KB piece: a set whose lvweb.MAX_BODY can't take lvota.CHUNK is not kept
check("FR1 m1: PUT is the upload probe alone", [p[:2] for p in g["PUT"]] == [("POST", "/api/ota/put")], g["PUT"])
check("FR1 m1: the upload probe passes on its own", asyncio.run(g["serves"](web, g["PUT"])) is True)
_mb = lvweb.MAX_BODY
lvweb.MAX_BODY = 1023
check("FR1 m1: MAX_BODY under a piece (413): no keep", asyncio.run(g["serves"](web, g["PUT"])) is False)
lvweb.MAX_BODY = _mb
web.phone.who = lambda req: 0
check("FR1 m1: upload open to anyone: no keep, phone's 2xx or not", asyncio.run(g["serves"](web, g["PUT"])) is False)
del web.phone.who
rm(D + "/ota") if lvsafe.exists(D + "/ota") else None
# a request that raises mid-way (said by Server.handle, the answer may be half out) fails
real_api = web.phone.api
web.phone.api = lambda req: 1 / 0
check("m1: an error said while answering /api/crew: no keep", asyncio.run(g["serves"](web)) is False)
web.phone.api = real_api
check("m2: and the counts as they were", (web.served, sh.http_hits) == (3, 4), (web.served, sh.http_hits))
# Review #2 M1 (rv2/serves_repro.py): a broken update whose request parser raises on every
# real request passed serves() (it called route directly). Now the raw bytes go through
# Server.handle, as a phone's do.
real_rr = lvweb.read_req


async def broken_read_req(reader):
    raise AttributeError("typo in read_req")
lvweb.read_req = broken_read_req
check("M1: a broken request parser: no keep", asyncio.run(g["serves"](web)) is False)
lvweb.read_req = real_rr
busy = lvweb.MAX_CONN
web.busy = busy
check("M1: every slot busy (503): not now", asyncio.run(g["serves"](web)) is False)
web.busy = 0
check("M1: and the counts still as they were", (web.ok2xx, web.served, sh.http_hits) == (7, 3, 4),
      (web.ok2xx, web.served, sh.http_hits, web.refused))
os.rename("www/app.html.gz", "www/gone")
check("m7: no page, no keep", asyncio.run(g["serves"](web)) is False)
lvweb.MAX_BODY = _mb0
os.chdir(HERE)

# ---- main.py: the keep rule, crashes, tasks, safe mode off -------------------------------
src = open("board/main.py").read()
src = src[:src.index("\nT0 = time.ticks_ms()")]
g = {"__name__": "main_test"}
exec(src, g)


class T:
    # the time functions main.py uses (CPython has none of them)
    slept = []

    @staticmethod
    def ticks_ms():
        return 1000

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    def sleep_ms(ms):
        T.slept.append(ms)


class Quick:
    # lvship as main.py uses it, with every wait cut to a moment (now: a clock tests move)
    now = [0]
    DEFAULTS = {"ship_id": 1, "ssid_prefix": "LV-", "hotspot": True}

    @staticmethod
    def sleep_ms(ms):
        return asyncio.sleep(min(ms, 20) / 1000)

    @staticmethod
    def drop(name):
        sys.modules.pop(name, None)

    @staticmethod
    def ticks_ms():
        return Quick.now[0]

    @staticmethod
    def ticks_diff(a, b):
        return a - b

    @staticmethod
    def load_config():
        return "load_config"


g["time"] = T
g["lvship"] = Quick
web = lvweb.Server(sh, ip="192.168.4.1", say=lambda s: None)
g["net_hooks"](lvweb, web)
asyncio.run(lvweb.send(W(), 404, "x"))
check("404 not counted", web.ok2xx == 0)
asyncio.run(lvweb.send_json(W(), 200, {}))
check("200 counted", web.ok2xx == 1)
web.ok2xx = 0


class FakeOta:
    n = 0

    @staticmethod
    def good():
        FakeOta.n += 1
        return True


class FakeWeb:
    # a set that serves the page (or doesn't: up) and counts no 2xx of its own
    def __init__(self):
        self.ok2xx = 0
        self.served = 0
        self.up = False
        self.put = True    # its /api/ota/put refuses an unsigned piece (401)
        self.ship = FakeShip()
        self.ship.http_hits = 0

    async def handle(self, r, w):
        post = r.b.startswith(b"POST")
        w.write(b"HTTP/1.0 401 Unauthorized\r\n" if post and (self.up or self.put)
                else b"HTTP/1.0 500 Oops\r\n" if not self.up or post else b"HTTP/1.0 200 OK\r\n")
        if self.up and not post:
            self.ok2xx += 1


sys.modules["lvota"] = FakeOta
g["OTA_OK_MS"] = 10


async def fake_kept(web):
    # main.py's kept(): board/lvotak.py's keep() as it is (lvota.good(), fault.json set aside,
    # lvota let go), its update-path check (tested in tests/test_ota.py) taken as passed
    import lvotak

    async def ok(web=None):
        return True
    lvotak.check = ok
    try:
        return await lvotak.keep(web, g["FAULT"], g["FAULT_LAST"])
    finally:
        sys.modules.pop("lvotak", None)


g["kept"] = fake_kept


async def keeps(fw, how):
    t = asyncio.create_task(g["ota_ok"](fw))
    await asyncio.sleep(0.2)
    before = FakeOta.n
    how(fw)
    await asyncio.sleep(0.2)
    return before, FakeOta.n


fw = FakeWeb()
a, b2 = asyncio.run(keeps(fw, lambda f: setattr(f, "ok2xx", 1)))
check("keep: not without a 2xx", a == 0)
check("keep: after the first 2xx", b2 == 1)
check("lvota dropped after", "lvota" not in sys.modules)
# FR1 m1: a phone's 2xx doesn't excuse a broken upload route
sys.modules["lvota"] = FakeOta
FakeOta.n = 0
fw = FakeWeb()
fw.put = False


async def no_put(fw):
    t = asyncio.create_task(g["ota_ok"](fw))
    await asyncio.sleep(0.2)
    fw.ok2xx = 1
    await asyncio.sleep(0.2)
    a = FakeOta.n
    t.cancel()
    await asyncio.sleep(0)
    return a


check("FR1 m1: a phone's 2xx, the upload route broken: not kept", asyncio.run(no_put(fw)) == 0)
sys.modules["lvota"] = FakeOta
FakeOta.n = 0
fw = FakeWeb()
a, b2 = asyncio.run(keeps(fw, lambda f: setattr(f, "up", True)))
check("m7: not while the ship's own check fails", a == 0)
check("m7: kept once it serves the page, no phone needed", b2 == 1 and fw.ok2xx == 0, (b2, fw.ok2xx))
# Review #3 m4: the phone game was wanted (the hotspot on, phone_game asks for it) but no
# web server came up (a core shadowed, say): not kept. And past SELF_MS of failing checks
# main.py restarts the ship itself, a counted boot (a soft-reset trial on ota-hwfix's lvboot
# has no deadline of its own: endless otherwise).
sys.modules["lvota"] = FakeOta
FakeOta.n = 0
rb = []
g["reboot"] = lambda: rb.append(1)
a, b2 = asyncio.run(keeps(None, lambda f: None))
check("m4: no web server, none wanted: kept", b2 == 1)
sys.modules["lvota"] = FakeOta
FakeOta.n = 0


async def wants(web, after):
    t = asyncio.create_task(g["ota_ok"](web, True))
    await asyncio.sleep(0.15)
    a = (FakeOta.n, list(rb))
    Quick.now[0] += after
    await asyncio.sleep(0.15)
    t.cancel()
    return a, (FakeOta.n, list(rb))


a, b2 = asyncio.run(wants(None, g["SELF_MS"] + 1))
check("m4: the phone game wanted, no web server: not kept", a == (0, []), a)
check("m4: ... restarted past SELF_MS (a counted boot), never kept", b2 == (0, [1]), b2)
rb[:] = []
fw = FakeWeb()
a, b2 = asyncio.run(wants(fw, g["SELF_MS"] + 1))
check("m3: a set that never shows it serves: restarted past SELF_MS", a == (0, []) and b2 == (0, [1]), (a, b2))
rb[:] = []
fw = FakeWeb()
fw.up = True
a, b2 = asyncio.run(wants(fw, 0))
check("m4: the phone game wanted and served: kept", a == (1, []), a)
Quick.now[0] = 0
sys.modules["lvota"] = FakeOta
# wanted(): phone_game true/false as set; "auto" asks the firmware for a core (none here)
check("m4: wanted, phone_game true", g["wanted"]({"phone_game": True}) is True)
check("m4: wanted, phone_game false", g["wanted"]({"phone_game": False}) is False)
real_lv = sys.modules.get("lv")


class LvStub:
    fw = (None, None)

    @staticmethod
    def firmware():
        return LvStub.fw


sys.modules["lv"] = LvStub
check("m4: wanted, auto with no frozen core", g["wanted"]({"phone_game": "auto"}) is False)
LvStub.fw = ("2661c2144844", "0.2.0")
check("m4: wanted, auto with a frozen core", g["wanted"]({}) is True)
LvStub.firmware = None
check("m4: wanted, auto, an lv without firmware(): no", g["wanted"]({}) is False)
if real_lv is None:
    sys.modules.pop("lv", None)
else:
    sys.modules["lv"] = real_lv

# crashed(): noted (by lvsafe, or the short way when it can't: M3), then a restart; the
# trial flag read at the crash (m9)
FD = D + "/fault.json"
fresh()
g["FAULT"] = FD
g["FAULT_LAST"] = D + "/fault.last.json"
boots = []
noted = []
trial = [False]
g["reboot"] = lambda: boots.append(1)
g["flag"] = lambda p: trial[0]
real = lvsafe.crashed
lvsafe.crashed = lambda why, trial, up, live=False: noted.append((why, trial, up)) or lives.append(live)
lives = []
try:
    g["crashed"](ValueError("boom"), 0)
    try:                          # 0.3.0 review R2 M3: a crash in Hail's own code says so
        import lvlive
        lvlive.parse(None)
    except Exception as e:
        g["crashed"](e, 0)
    noted.pop()
    trial[0] = True
    g["crashed"](ValueError("x" * 99), 0)
    trial[0] = False

    def oom(*a, **k):        # (takes live= too, so the fault is the MemoryError meant, not a TypeError)
        raise MemoryError()
    lvsafe.crashed = oom
    g["crashed"](MemoryError(), 0)
    g["crashed"](MemoryError(), 0)
    trial[0] = True
    g["crashed"](MemoryError(), 0)
    trial[0] = False
except BaseException as e:
    check("crashed never raises", False, repr(e))
lvsafe.crashed = real
check("crashed: noted", noted[0] == ("ValueError: boom", False, 1000), noted)
check("R2 M3: a crash elsewhere: not Hail's", lives[0] is False, lives)
if hasattr(sys, "print_exception"):     # (MicroPython: the traceback is read for it)
    check("R2 M3: a crash in lvlive: Hail's", lives[1] is True, lives)
check("m9: the trial read at the crash", noted[1][1] is True and len(noted[1][0]) < 64, noted)
j = json.loads(get(FD))
check("M3: no heap for lvsafe: noted the short way", j["n"] == 2 and j["why"] == "noted the short way", j)
check("M3: not on a trial either", files() == ["fault.json"], files())
check("crashed: restart every time", boots == [1] * 6, boots)
put(FD, '{"n": 5, "why": "x"}')
g["note"](False)
check("M3: the short way stops at the cap too", json.loads(get(FD))["n"] == 5)
# Review #2 m4: the short way kept only n and why (safe mode's next wait, tries, fell back to
# 30 min after every crash it noted), and rewrote the file at the cap on every crash
put(FD, '{"n": 1, "why": "MemoryError: x", "up": 5, "tries": 3}')
g["note"](False)
j = json.loads(get(FD))
check("m4: the short way keeps tries", j == {"n": 2, "why": "noted the short way", "up": 5, "tries": 3}, j)
put(FD, '{"n": 5, "why": "x", "tries": 2}')
real_o = g.get("open")
wrote = []


def no_write_open(path, mode="r", *a):
    if "w" in mode:
        wrote.append(path)
    return real_open(path, mode, *a)


g["open"] = no_write_open
g["note"](False)
g["note"](False)
del g["open"]
check("m4: at the cap the short way writes nothing", wrote == [] and get(FD) == '{"n": 5, "why": "x", "tries": 2}', wrote)
put(FD, "[1]")
g["note"](False)
check("m4: the short way over a broken note", json.loads(get(FD))["n"] == 1, get(FD))
# Review #2 M2: crashed() let go of nothing: MAIN (run()'s finished task, its coroutine
# holding the whole game) and FATAL (the accept loop's task, holding web.handle) kept it
# all, and so did lvweb.head (net_hooks' counter, whose closure holds the server). Now
# they are cleared first. On MicroPython, the heap the note sees is measured.
for k in ("MAIN", "FATAL", "CRASH"):
    check("M2: %s cleared by crashed()" % k, g[k] == [], g[k])
if sys.implementation.name == "micropython":
    import gc
    saved = dict((m, sys.modules[m]) for m in g["GAME"] if m in sys.modules)
    gc.collect()
    base = gc.mem_alloc()
    seen = []

    def build():
        import lvweb as W2
        sh2 = FakeShip()
        sh2.http_hits = 0
        sh2.big = [bytearray(1000) for _ in range(30)]     # the game's heap (ship, story, phones...)
        web2 = W2.Server(sh2, say=lambda s: None)
        g["net_hooks"](W2, web2)

        async def run():
            g["MAIN"][:] = [asyncio.current_task()]
            w = web2

            async def srv():
                c = w
                await asyncio.sleep(10)
            g["FATAL"][:] = [asyncio.create_task(srv())]
            await asyncio.sleep(0)
            g["CRASH"].append(MemoryError("memory allocation failed, allocating 4096 bytes"))
            g["MAIN"][0].cancel()
            await asyncio.sleep(1)
        asyncio.run(run())

    def measure(why, trial, up, live=False):
        gc.collect()
        seen.append((gc.mem_alloc() - base, why))
    lvsafe.crashed = measure
    boots = []
    try:
        build()
    except BaseException as e:
        g["crashed"](g["CRASH"][0] if g["CRASH"] else e, 0)
    lvsafe.crashed = real
    sys.modules.update(saved)
    check("M2: crashed() noted the crash's own words", seen and seen[0][1].startswith("MemoryError: memory allocation"), seen)
    check("M2: the game's heap is let go before the note (< 4 KB of 30 KB live)", seen[0][0] < 4096, seen)
    print("M2: live after crashed()'s clean-up: %d B (the game held 30,000+)" % seen[0][0])

# task_error(): only the web server's accept loop stops the game (M4)
class Tk:
    def __init__(self):
        self.off = 0

    def cancel(self):
        self.off += 1


m, srv_task, led_task = Tk(), Tk(), Tk()
g["MAIN"][:] = [m]
g["FATAL"][:] = [srv_task]
g["task_error"](None, {"exception": ValueError("led"), "future": led_task})
check("M4: a light task's error doesn't stop the game", m.off == 0 and g["CRASH"] == [])
e = OSError(23)
g["task_error"](None, {"exception": e, "future": srv_task})
check("M4: the accept loop's does", m.off == 1 and g["CRASH"] == [e])
del g["CRASH"][:]
if sys.implementation.name == "micropython":
    # the real thing: MicroPython calls the handler as the task dies
    async def run():
        g["MAIN"][:] = [asyncio.current_task()]
        asyncio.get_event_loop().set_exception_handler(g["task_error"])

        async def bad():
            raise ValueError("the light")
        asyncio.create_task(bad())
        await asyncio.sleep(0.05)
        t = asyncio.create_task(bad())
        g["FATAL"][:] = [t]
        await asyncio.sleep(0.05)
        return "still here"
    try:
        r = asyncio.run(run())
    except BaseException as e:
        r = e
    check("M4: the fatal task cancels run()", isinstance(r, asyncio.CancelledError) and repr(g["CRASH"][0]).startswith("ValueError"), (r, g["CRASH"]))
    asyncio.new_event_loop()
    del g["CRASH"][:]
    g["FATAL"][:] = []

# keep(): a task that stops is started again, with a growing pause
runs = []


async def flaky_task():
    runs.append(1)
    if len(runs) < 3:
        raise OSError("dns")
    return "done"
check("keep: started again until it runs", asyncio.run(g["keep"]("dns", flaky_task)) == "done" and len(runs) == 3)
# Review #2 m8: the pause doubled for good; a run of more than a minute starts it at 5 s again
said_keep = []
real_print = g.get("print")
g["print"] = said_keep.append
runs = []


async def long_then_fail():
    runs.append(1)
    if len(runs) <= 3:
        raise OSError("dns")            # three quick failures: 5, 10, 20 s
    if len(runs) == 4:
        Quick.now[0] += 3600000         # then it runs for an hour and fails
        raise OSError("dns")
    return "done"
asyncio.run(g["keep"]("dns", long_then_fail))
del g["print"]
pauses = [x.split("again in ")[1] for x in said_keep]
check("m8: the pause starts at 5 s again after a long run", pauses == ["5 s", "10 s", "20 s", "5 s"], pauses)

# Review #2 M6: healthy() at minute 10 is main.py's own: fault.json goes, nothing imported
put(FD, '{"n": 1, "why": "x"}')
sys.modules.pop("lvsafe", None)
asyncio.run(g["healthy"]())
check("M6: healthy removes fault.json", not lvsafe.exists(FD))
check("review #3 M1: ... set aside as fault.last.json, notes kept", json.loads(get(D + "/fault.last.json")) == {"n": 1, "why": "x"})
put(FD, '{"n": 1, "boot": "ship.json plays as it is"}')
sys.modules["lvota"] = FakeOta
asyncio.run(g["ota_ok"]())
check("review #3 M1: an update kept sets fault.json aside too (its note kept)", not lvsafe.exists(FD)
      and json.loads(get(D + "/fault.last.json")) == {"n": 1, "boot": "ship.json plays as it is"})
check("M6: healthy imports nothing (no lvsafe, no lvledcfg)", "lvsafe" not in sys.modules and "lvledcfg" not in sys.modules)
asyncio.run(g["healthy"]())
check("M6: healthy with no fault.json is fine", not lvsafe.exists(FD))
sys.modules["lvsafe"] = lvsafe

# Review #2 m1: cfg is built from the ship.json lvsafe.check() read, not a second read
c = g["config"]([{"ship_id": "5", "hotspot_password": "x" * 12}])
check("m1: cfg from what check() read", c["ship_id"] == 5 and c["ssid_prefix"] == "LV-" and c["hotspot_password"] == "x" * 12, c)
check("m1: a bench board with no ship.json: the defaults", g["config"]([])["ship_id"] == 1)
check("m1: ship_id clamped as load_config does", g["config"]([{"ship_id": 12}])["ship_id"] == 8 and g["config"]([{"ship_id": "x"}])["ship_id"] == 1)
check("m4: lvsafe unusable at boot: load_config as 0.2.6", g["config"](None) == "load_config")
fresh()
put(P, SHIP)
got = []
lvsafe.check(False, D, said.append, got)
check("m1: check() hands back ship.json as read", got == [json.loads(SHIP)], got)

# Review #3 M1 (rv3/upgrade_matrix.py): every ship.json that failed lvledcfg.valid() was
# "off" at boot, so a 0.2.6 ship with an empty or 64-character password, a float ship_id
# or no password key... could never take 0.2.7 (its trial went dark, lvboot rolled it back)
# nor any later release. Now: a usable ship number plays, exactly as 0.2.6 played that
# file (main.config(got) == 0.2.6's lvship.load_config, the same hotspot password rule);
# valid() only decides the .bak. Off only with no usable ship number on a crew ship with
# nothing to put back, and the reason is in fault.json "boot". Every shape the review
# listed, on an update's trial and kept, with a crew.json as every real ship has.
ls = open(HERE + "/board/lvship.py").read()
g26 = {}
exec(ls[ls.index("\nDEFAULTS = {"):ls.index("\ndef phone_game")], g26)     # 0.2.6's own config rule


def ap_pw(c):
    # board/lvwifi.py's rule (unchanged since 0.2.5): the password the hotspot gets
    pw = str(c.get("hotspot_password") or "")
    return "" if c.get("hotspot_open") else pw if 8 <= len(pw) <= 63 else "CHANGE_ME"


MATRIX = [
    ("bench-provisioned", {"ship_id": 3, "hotspot_password": "fake-pass-123", "hotspot_open": False}, "whole"),
    ("updater, firmware-default pw (no key)", {"schema": 2, "ship_id": 6, "ship_name": "Starship-06", "hotspot_open": False}, "whole"),
    ("hotspot_password empty", {"ship_id": 4, "hotspot_password": ""}, "plays"),
    ("open hotspot, empty password", {"ship_id": 2, "hotspot_open": True, "hotspot_password": ""}, "plays"),
    ("64-hex WPA PSK as password", {"ship_id": 7, "hotspot_password": "a" * 64}, "plays"),
    ("ship_id as float 1.0", {"ship_id": 1.0, "hotspot_password": "fake-pass-123"}, "plays"),
    ("ship_id as digits", {"ship_id": "8", "hotspot_password": "fake-pass-123"}, "whole"),
    ("password a number", {"ship_id": 5, "hotspot_password": 12345678}, "plays"),
    ("no ship_id (0.2.6's default ship 1)", {"hotspot_password": "fake-pass-123", "fleet_key": "fake"}, "off"),
    ("0.2.6 toggle damage {led_notify}", {"led_notify": True}, "off"),
    ("ship_id 0", {"ship_id": 0, "hotspot_password": "fake-pass-123"}, "off"),
    ("ship_id 9", {"ship_id": 9, "hotspot_password": "fake-pass-123"}, "off"),
    ("ship_id 2.5", {"ship_id": 2.5}, "off"),
    ("ship_id true", {"ship_id": True}, "off"),
    ("ship_id \"x\"", {"ship_id": "x"}, "off"),
]
quick_d = Quick.DEFAULTS
Quick.DEFAULTS = g26["DEFAULTS"]            # main.config builds on lvship.DEFAULTS
for name, sc, want in MATRIX:
    for tr in (True, False):
        fresh()
        put(P, json.dumps(sc))
        put(D + "/crew.json", CREW)
        got = []
        w = lvsafe.check(tr, D, said.append, got)
        tag = "M1 matrix, %s, %s" % (name, "trial" if tr else "kept")
        fj = lvsafe.faults(D)
        if want == "off":
            check(tag + ": off", (w or "").startswith("off: ship.json not usable"), w)
            check(tag + ": the reason in fault.json", fj.get("boot") == w and "n" not in fj, fj)
            check(tag + ": ship.json left as it is", json.loads(get(P)) == sc)
            continue
        check(tag + ": plays", w is None, w)
        c = g["config"](got)
        o = g26["load_config"](P)
        check(tag + ": as 0.2.6 played it (cfg)", c == o, (c, o))
        check(tag + ": the same hotspot password rule", ap_pw(c) == ap_pw(o))
        check(tag + ": the ship it says", c["ship_id"] == int(sc["ship_id"]))
        if want == "whole":
            check(tag + ": backed up, nothing to note", json.loads(get(P + ".bak")) == sc and "boot" not in fj, (files(), fj))
        else:
            check(tag + ": never backed up", not lvsafe.exists(P + ".bak"), files())
            check(tag + ": noted, once", fj.get("boot") == "ship.json plays as it is, but isn't whole (no backup made)", fj)
            hits = []
            lvsafe.fail = hits.append
            lvsafe.check(tr, D, said.append)
            lvsafe.fail = None
            check(tag + ": the next boot writes nothing", "write" not in hits, hits)
Quick.DEFAULTS = quick_d
# a usable but not whole ship.json next to a good .bak: the file plays (it says which
# ship), the .bak stays the last whole one
fresh()
put(P + ".bak", SHIP)
put(P, '{"ship_id": 5, "hotspot_password": ""}')
got = []
check("M1: usable, not whole, a .bak there: plays the file", lvsafe.check(False, D, said.append, got) is None
      and got == [{"ship_id": 5, "hotspot_password": ""}], got)
check("M1: ... the .bak untouched", get(P + ".bak") == SHIP)
# an off ship looks again every OFF_MS: the same reason is not written again
fresh()
put(D + "/crew.json", CREW)
put(P, '{"led_notify": true}')
lvsafe.check(False, D, said.append)
hits = []
lvsafe.fail = hits.append
w = lvsafe.check(False, D, said.append)
lvsafe.fail = None
check("M1: off again: no new write (no wear)", w.startswith("off:") and "write" not in hits, hits)
lvsafe.crashed("ValueError: q", False, 1, D)
check("M1: a crash note keeps the boot note", lvsafe.faults(D).get("boot") == w and lvsafe.count(lvsafe.faults(D)) == 1)
# review #3 m6: a backup cut short (.bak.new) is cleaned up next to a good file
fresh()
put(P, SHIP)
put(P + ".bak.new", SHIP)
lvsafe.check(False, D, said.append)
check("m6: a leftover ship.json.bak.new removed", not lvsafe.exists(P + ".bak.new") and "safe: a leftover ship.json.bak.new removed" in said, files())

# safe_mode "off": nothing on the air, a wait, then a restart (safe mode once more after the cap)
rested = []
real_f, real_r = lvsafe.faults, lvsafe.rest
lvsafe.faults = lambda d=None: {"n": lvsafe.SAFE_CAP}
lvsafe.rest = lambda d=None: rested.append(1)
boots = []
T.slept = []
g["safe_mode"]({}, "off: safe mode stopped 3 times in a row")
check("m1: off waits OFF_MS, rests, restarts", T.slept == [lvsafe.OFF_MS] and rested == [1] and boots == [1], (T.slept, rested, boots))
lvsafe.faults = lambda d=None: {}
g["safe_mode"]({}, "off: ship.json can't be read just now")
check("m3: off for a read error: no rest, restarts", rested == [1] and boots == [1, 1])
lvsafe.faults, lvsafe.rest = real_f, real_r
import lvcode  # noqa: E402  (Reset this ship: lvcode.reset since 0.3.0)
check("RESET clears fault.json (m11)", "fault.json" in lvcode.RESET, lvcode.RESET)
print("test_safe: %d checks ok (%s)" % (ok[0], sys.implementation.name))
