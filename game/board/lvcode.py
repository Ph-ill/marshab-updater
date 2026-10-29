# "Change your code" (the page's Settings, web/settings.js): a signed-in crew member sets a
# new sign-in code on this ship. POST /api/code {old, new} with X-Crew-Token, answered from
# main.py's ota_route; this module is imported for the request and dropped after it (the
# lvota / lvfunnel pattern), so it holds no RAM between requests and the frozen core
# (lv/codes.py, lvphone.py) stays as it is.
#
#   200 {ok}                        the new code works from now on, the old one doesn't;
#                                   this phone stays signed in (sessions are untouched)
#   401 {err}                       no signed-in session (the page signs out)
#   400 {err}                       the new code isn't 4 digits, is the old one, or the
#                                   old code isn't 4 digits: no try is counted
#   403 {err, left}                 the old code is wrong: counted with the sign-in's tries
#   429 {err, wait}                 too many wrong codes: the sign-in's own lockout
#                                   (lv/codes.py MAX_TRIES, LOCK_MS), for this crew member
#   409 {err}                       no code set up for this crew member (bench.py sets them)
#   500 {err}                       the file couldn't be written: the old code still works
#
# The codes are lv/codes.py's: exactly 4 digits (CodeBook.check refuses anything else at
# the sign-in), kept in data/crew.json as sha256(salt || crew byte || digits). A crew member
# signs in by picking their name, then the code, so two people may share a code; nothing
# checks for that (refusing would tell you someone else's code). The old code is checked
# by CodeBook.check itself, so a wrong one counts toward the same lockout as a wrong
# sign-in and a lockout from either side blocks both.
#
# The file: only the one 64-hex digest changes, replaced in the file's own text, so the
# salt, every other crew member's entry and anything else in it stay byte-for-byte. The
# new text is written to crew.json.new, read back and checked, and only then renamed over
# crew.json (littlefs and POSIX replace the target in one step, so crew.json is always
# either the old file or the new one). A rename that fails is a failure (crew.json as it
# was): 0.2.5/0.2.6 then moved crew.json to crew.json.old first, which left a moment with
# no crew.json at all; board/lvsafe.py still puts a crew.json back from a .old left by that.
# Then crew.json.bak (board/lvsafe.py's backup) gets the same text at once (bak()), so a
# crew.json lost before the next boot is put back with the new code, never the old one.
# The in-memory book changes only after the file has. Codes are never printed or logged.
# Only this ship's file changes: the other ships keep the old code until bench.py or the
# updater's ship setup writes theirs. Reset this ship keeps crew.json (RESET below).
from lv import codes as K
from lv.clock import ticks_ms

PATH = "/crew.json"
fail = None             # tests: called at "write", "read" and "rename" to simulate a failure


def _hit(where):
    if fail:
        fail(where)


def _four(v):
    # ASCII digits only: str.isdigit() also takes other scripts' digits on CPython.
    return isinstance(v, str) and len(v) == 4 and all("0" <= ch <= "9" for ch in v)


def save(path, old_digest, new_digest):
    """Swap one digest in crew.json. Returns True, or False (crew.json as it was)."""
    import os
    with open(path) as f:
        txt = f.read()
    if txt.count(old_digest) != 1:
        return False
    new = txt.replace(old_digest, new_digest)
    txt = None
    tmp = path + ".new"
    try:
        _hit("write")
        with open(tmp, "w") as f:
            f.write(new)
        _hit("read")
        with open(tmp) as f:
            ok = f.read() == new
        if not ok:
            raise OSError("crew.json.new reads back wrong")
        _hit("rename")
        os.rename(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    bak(path, new)
    return True


def bak(path, text):
    """crew.json.bak (board/lvsafe.py's last good copy, put back if crew.json is ever lost)
    := the new crew.json at once, so a crew.json damaged before the next boot can't bring
    the old code back (review #3 m5). Written whole (bak.new, read back, rename); if that
    fails the stale .bak is removed instead (the next boot makes a fresh one from crew.json),
    so an old code is never what a restore finds."""
    import os
    b = path + ".bak"
    try:
        _hit("bak")
        with open(b + ".new", "w") as f:
            f.write(text)
        with open(b + ".new") as f:
            if f.read() != text:
                raise OSError("crew.json.bak.new reads back wrong")
        os.rename(b + ".new", b)
    except OSError:
        for p in (b + ".new", b):
            try:
                os.remove(p)
            except OSError:
                pass


def change(phone, req):
    """-> (status, JSON-able)."""
    you = phone.who(req)
    if you is None:
        return 401, {"err": "signed out"}
    try:
        import json
        b = json.loads(req.body or b"{}")
        old, new = b["old"], b["new"]
    except Exception:
        return 400, {"err": "bad request"}
    if not _four(new):
        return 400, {"err": "Your new code needs to be 4 digits."}
    if not _four(old):
        return 400, {"err": "Your current code is 4 digits."}
    if new == old:
        return 400, {"err": "Your new code is the same as your current one."}
    book = phone.book
    st, v = book.check(you, old, ticks_ms())
    if st == K.WRONG:
        return 403, {"err": "That isn't your current code.", "left": v}
    if st == K.LOCKED:
        return 429, {"err": "Too many tries.", "wait": v}
    if st == K.NO_CODE:
        return 409, {"err": "No code set up for you on this ship yet."}
    if st != K.OK:
        return 400, {"err": "bad request"}
    d = K.digest(book.salt, you, new)
    try:
        done = save((phone.data or "data") + PATH, book.codes[you], d)
    except OSError:
        done = False
    if not done:
        return 500, {"err": "The ship couldn't save it. Your current code still works."}
    book.codes[you] = d
    return 200, {"ok": True}


# "Reset this ship" (the page's Settings, POST /api/reset from main.py's ota_route): the players' progress goes, the ship's setup stays.
# Deleted from /data: log.bin (every record this ship holds: taps, votes, gifts; other ships
# in range sync theirs back), days.bin (the days told), clock.json (the saved flight day and
# time; the launch date in ship.json brings the day back once a phone tells the time),
# local.bin (what phones opened and saw), and funnel.bin (the phones the home-screen funnel
# has seen, and which opened the game from the icon: board/lvfunnel.py). Sign-ins and
# sessions live in RAM, so the restart forgets them.
# fault.json (board/lvsafe.py: the crash count) goes too: a reset ship starts with a clean count.
# Kept: ship.json (identity, hotspot password, ota_src, the Ship light), crew.json (the crew
# codes, including any changed in Settings: board/lvcode.py), their backups ship.json.bak and
# crew.json.bak (lvsafe), the installed software and ota/ (the update state and rollback
# copy), maint/safe.
RESET = ("log.bin", "days.bin", "clock.json", "local.bin", "funnel.bin", "fault.json", "hail.json")


async def reset(lvweb, web, req, w, reboot=None):
    # POST /api/reset {confirm: this ship's number} with a signed-in X-Crew-Token, else
    # 401/403 and nothing changes. 200 (-> True), then the files go and the board restarts (reboot:
    # main.py's, for the tests; else machine.reset). Moved here from main.py in 0.3.0 so
    # its code is only in RAM for the request (main.py imports this module per request and
    # drops it; the restart task below keeps what it needs).
    try:
        import asyncio
    except ImportError:  # pragma: no cover
        import uasyncio as asyncio
    if req.method != "POST":
        return await lvweb.send_json(w, 404, {"err": "no such thing"})
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    sh = web.ship
    try:
        import json
        ok = int(json.loads(req.body or b"{}")["confirm"]) == sh.cfg["ship_id"]
    except Exception:
        ok = False
    if not ok:
        return await lvweb.send_json(w, 403, {"err": "Type this ship's number to confirm."})
    await lvweb.send_json(w, 200, {"ok": True, "restart_ms": 1500})

    async def later():
        await asyncio.sleep(1)
        # No await from here on: nothing can write a file back before the restart.
        import os
        for f in RESET:
            try:
                os.remove(sh.data + "/" + f)
            except OSError:
                pass
        # Hail (0.3.0 review R2 m10): hail.json went above; hails no phone has read yet go
        # too (lvlivein.forget, per use)
        try:
            import lvlivein
            lvlivein.forget(sh)
        except Exception:
            pass
        # (nothing printed here: lvcode never prints, test_code.py; main.py says it)
        if reboot:
            return reboot()
        import machine
        machine.reset()
    asyncio.create_task(later())
    return True
