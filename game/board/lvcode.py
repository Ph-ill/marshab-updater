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
# either the old file or the new one). Where a rename can't replace a file, the old one is
# moved to crew.json.old first and put back if the second rename fails. The in-memory book
# changes only after the file has. Codes are never printed or logged.
# Only this ship's file changes: the other ships keep the old code until bench.py or the
# updater's ship setup writes theirs. Reset this ship keeps crew.json (main.py RESET).
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
        try:
            _hit("rename")
            os.rename(tmp, path)
        except OSError:
            # A filesystem that won't rename onto a file: move the old one aside first.
            old = path + ".old"
            os.rename(path, old)
            try:
                _hit("rename2")
                os.rename(tmp, path)
            except OSError:
                os.rename(old, path)
                raise
            os.remove(old)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


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
