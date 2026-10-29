# Over-the-air updates, the upload itself (0.3.0): POST /api/ota/put, the signed envelope
# and then every file in pieces. main.py and safe mode (lvsafe.py) send that one request
# here instead of to lvota.py, and drop this module straight after (lvship.drop), so the
# busiest part of an update carries ~2 KB of code instead of lvota's ~8 KB:
#   * a file piece (f >= 1) needs only this module. Its size and checksum come from one
#     line of ota/new/ix (written next to the envelope once its signature checked out:
#     fixed-width lines, read with a seek), not from the whole manifest parsed again for
#     every piece as up to 0.2.7.
#   * the envelope's last piece: lvota reads it and hashes the manifest, then is dropped
#     before the signature check (lvsig), and loaded again to finish (check the manifest,
#     write eh, ix and ok). So at the update's biggest moment the heap holds this module
#     and lvsig, not lvota as well. A caller that already holds lvota (the tests,
#     lvota.put) keeps it: only a copy this module loaded itself is dropped.
# Everything the upload means, and what is refused, is described at the top of lvota.py.
# A piece that fails for want of heap (MemoryError: the request is closed unanswered) is
# sent again by the phone (web/ota.js: a few tries, then "Install" again resumes from
# what's on flash); and a ship that keeps crashing ends up in safe mode, which serves
# this same upload with no game loaded (tests/mp_sync_heap.py --safe measures it).
import os
import sys

OTA = "ota"
NEW = OTA + "/new"
IX = NEW + "/ix"
REC = 139                 # one ix line: "%08d" size, sha256 hex, path padded to 64, spaces, "\n"


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _size(p):
    try:
        return os.stat(p)[6]
    except OSError:
        return -1


def _drop(name):
    try:
        del sys.modules[name]
    except KeyError:
        pass


def ix_line(path, size, sha):
    """The ix line for one manifest file (lvota writes them, in manifest order). The path is
    only for an error message: one that isn't plain ASCII (a line is a fixed number of
    bytes) is shown as "?"."""
    for c in path:
        if not " " < c < "\x7f":
            path = "?"
            break
    return "%08d %s %s\n" % (size, sha, (path + " " * 64)[:64])


def entry(f):
    """File f (1-based) of the staged update -> (size, sha256 hex, path), or None. An update
    staged by 0.2.7 or older has no ix: lvota writes it from the manifest, once."""
    if not _exists(IX):
        had = "lvota" in sys.modules
        import lvota
        try:
            lvota.index()
        finally:
            lvota = None
            if not had:
                _drop("lvota")
    n = _size(IX) // REC
    if not 1 <= f <= n:
        return None
    with open(IX, "rb") as fh:
        fh.seek((f - 1) * REC)
        s = fh.read(REC)
    try:
        s = str(s, "ascii")
        if len(s) != REC or s[8] != " " or s[73] != " ":
            return None
        return int(s[:8]), s[9:73], s[74:138].rstrip()
    except (ValueError, UnicodeError):
        return None


def sha_file(p):
    try:
        import hashlib
    except ImportError:  # pragma: no cover
        import uhashlib as hashlib
    from binascii import hexlify
    h = hashlib.sha256()
    buf = bytearray(512)
    with open(p, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(buf[:n] if n < 512 else buf)
    return str(hexlify(h.digest()), "ascii")


def append(p, off, body, size):
    """Write `body` at `off`, which must be the end of what's there, within `size`.
    -> None, or the (status, answer) refusing it: 409 says where to carry on from."""
    have = max(0, _size(p))
    if off != have:
        return 409, {"err": "wrong offset", "have": have}
    if off + len(body) > size:
        return 400, {"err": "more than the file's size"}
    with open(p, "ab") as f:
        f.write(body)
    return None


def piece(f, off, body):
    """A piece of file f (f >= 1) -> (status, JSON-able)."""
    if not _exists(NEW + "/ok"):
        return 409, {"err": "send the update's signature first", "have": None}
    e = entry(f)
    if e is None:
        if not _exists(IX):
            return 409, {"err": "send the update's signature first", "have": None}
        return 400, {"err": "bad request"}
    size, sha, path = e
    p = "%s/f%d" % (NEW, f)
    if _exists(p + ".ok"):
        return 200, {"ok": True, "have": size, "done": True}
    if _size(p) != size:
        have = append(p, off, body, size)
        if have is not None:
            return have
        have = off + len(body)
        if have < size:
            return 200, {"ok": True, "have": have}
    # else: every byte landed before, but its check never ran (the request died after the
    # write: no heap for the hash, a dropped connection, a power cut). Any piece of it checks
    # it now; lvota.status shows such a file one byte short, so the phone sends one (0.3.0).
    have = size
    if sha_file(p) != sha:
        os.remove(p)
        return 400, {"err": "%s didn't match its signed checksum" % path, "have": 0}
    os.rename(p, p + ".ok")
    return 200, {"ok": True, "have": have, "done": True}


def _verify(key, msg, sig):
    import gc
    import lvsig
    try:
        import lvweb
        lvsig.probe = lvweb.probe       # the heap tests' sampler (None on a board)
    except Exception:
        pass
    gc.collect()
    try:
        return lvsig.verify(key, msg, sig)
    finally:
        lvsig = None
        _drop("lvsig")                  # ~4 KB on the heap: only ever needed for this


def envelope(q, off, body):
    """A piece of the envelope (f=0) -> (status, JSON-able); its last one is checked."""
    import gc
    had = "lvota" in sys.modules
    import lvota
    try:
        r = lvota.env_piece(q, off, body)
        if r is not None:
            return r
        p = NEW + "/env"
        h, msg, sig, key, why = lvota.envelope_prep(p)
        ok = False
        if why is None:
            if not had:
                lvota = None
                _drop("lvota")
                gc.collect()
            ok = _verify(key, msg, sig)
            msg = sig = key = None
            import lvota
        return lvota.envelope_done(p, h, ok, why)
    finally:
        lvota = None
        if not had:
            _drop("lvota")


def put(q, body):
    """POST /api/ota/put -> (status, JSON-able)."""
    try:
        f = int(q.get("f", "-1"))
        off = int(q.get("o", "-1"))
    except ValueError:
        return 400, {"err": "bad request"}
    if f == 0:
        try:
            return envelope(q, off, body)
        except MemoryError:
            # the check ran out of heap: nothing is lost (the envelope stays on flash, not
            # yet ok), and 503 is what the phone retries after a pause; its last piece again
            # checks it (lvota.env_piece). Not 403 "unreadable": it isn't (0.3.0 R1 m1).
            return 503, {"err": "busy", "have": None}
    return piece(f, off, body)


async def api(web, req, w, waited=False):
    """main.py and lvsafe.py route POST /api/ota/put here. waited: the caller (main.py) has
    already waited for a quiet moment (lvotaq), before this module was loaded."""
    import lvweb
    if req.method != "POST":
        return await lvweb.send_json(w, 404, {"err": "no such thing"})
    if web.get_phone().who(req) is None:
        return await lvweb.send_json(w, 401, {"err": "signed out"})
    body = req.body or b""
    if not waited:
        import lvotaq
        try:
            await lvotaq.quiet(web, req.q, body)
        finally:
            lvotaq = None
            _drop("lvotaq")
    code, obj = put(req.q, body)
    return await lvweb.send_json(w, code, obj)
