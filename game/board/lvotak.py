# Over-the-air updates: the check before a trial is kept (0.3.0, review R1 M2). main.py's
# ota_ok calls keep() once the update has been up OTA_OK_MS and has served a phone. Serving
# a phone isn't enough: the next update needs the upload's whole chain (lvotaq's wait,
# lvotap's pieces, lvota's envelope and status, lvsig's signature check), and a set that
# keeps itself without it can never be updated over the air again, not even from safe mode
# (it uses the same modules) -- only a USB cable would fix it, and that means opening the
# case. So before lvota.good() keeps it, every module of that chain, and safe mode's
# lvsafe (it serves the same upload on a ship that keeps crashing: fix review FR1 m4), is
# imported (and dropped again straight after: one at a time, so the heap holds one of them
# at once), its entry points are looked up, lvota.KEYS must hold the release key (KIDS:
# FR1 M1), the staging status is read, and lvsig checks a fixed
# signature: RFC 8032's test 1 (the empty message), which must verify, and the same with
# one bit flipped, which must not (refused before the long part: costs nothing). A stale
# lvota.py next to the shipped lvota.mpy (MicroPython imports the .py first) or a damaged
# file fails here, and the trial is not kept: lvboot's deadline, or main.py's SELF_MS
# restart, rolls it back to the set that worked.
# The check is the signature check's moment for the heap without the upload's code (only
# this module and lvsig), and it waits up to WAIT_MS for the radio and the phones to be
# quiet first, as the update's own check does (lvotaq). Loaded for this one call and dropped.
import sys
from binascii import unhexlify

WAIT_MS = 15000
NEEDS = (("lvlight", ("_pin", "_hold", "_busy")),
         ("lvcheck", ("serves",)),
         ("lvsetup", ("boot", "config", "wanted", "prepare")),
         ("lvphoneinit", ("setup",)),
         ("lvphoneapi", ("api", "gift")),
         ("lvstateapi", ("state_body", "state_writer")),
         ("lvotaq", ("quiet",)),
         ("lvotap", ("api", "put", "piece", "envelope", "append", "entry", "sha_file")),
         ("lvota", ("api", "status", "env_piece", "envelope_prep", "envelope_done", "apply",
                    "good", "KEYS")),
         ("lvsafe", ("check", "crashed", "start", "server")))
# The release key(s) the next update can be signed with (tools/ota/sign_release.py). A set
# whose lvota.KEYS lacks it would pass every other check here and then refuse every later
# update as "signed with a key this ship doesn't know": kept, it could only be fixed over
# USB (0.3.0 fix review FR1 M1 / FR3 i1). tools/build_release.py refuses to build one too.
KIDS = ("2111b2e9",)


def _drop(name):
    try:
        del sys.modules[name]
    except KeyError:
        pass


def keys_ok(keys):
    """lvota.KEYS can check the next update: a non-empty dict of 32-byte Ed25519 keys, one
    of them under a key id in KIDS that is really its id (sha256(key)[:4] in hex)."""
    if not isinstance(keys, dict) or not keys:
        return False
    for k in keys.values():
        if not isinstance(k, (bytes, bytearray)) or len(k) != 32:
            return False
    try:
        import hashlib
    except ImportError:  # pragma: no cover
        import uhashlib as hashlib
    from binascii import hexlify
    for kid in KIDS:
        k = keys.get(kid)
        if k is not None and str(hexlify(hashlib.sha256(k).digest()[:4]), "ascii") == kid:
            return True
    return False


def _look(name, attrs):
    had = name in sys.modules
    m = __import__(name)
    try:
        for a in attrs:
            if not hasattr(m, a):
                raise ImportError("%s has no %s" % (name, a))
        if name == "lvota":
            if not keys_ok(m.KEYS):
                raise ValueError("lvota.KEYS doesn't hold the release key")
            m.status()
    finally:
        m = None
        if not had:
            _drop(name)


def sig_ok():
    had = "lvsig" in sys.modules
    import lvsig
    try:
        pub = unhexlify("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = unhexlify("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
                        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        bad = bytearray(sig)
        bad[63] |= 0x80                       # S >= L: refused before the long part
        return lvsig.verify(pub, b"", sig) is True and lvsig.verify(pub, b"", bad) is False
    finally:
        lvsig = None
        if not had:
            _drop("lvsig")


async def check(web=None):
    """True if the update path works; raises (ImportError, MemoryError, ...) or False if not."""
    import gc
    if web is not None:
        import lvship
        b = getattr(getattr(web, "ship", None), "ble", None)
        t0 = lvship.ticks_ms()
        while ((b is not None and b.busy()) or getattr(web, "busy", 0) > 0) \
                and lvship.ticks_diff(lvship.ticks_ms(), t0) < WAIT_MS:
            await lvship.sleep_ms(100)
    for name, attrs in NEEDS:
        _look(name, attrs)
        gc.collect()
    return sig_ok()


async def keep(web, fault, fault_last):
    """main.py's ota_ok: check the update path, then keep the trial (lvota.good()). True once
    done (kept, or nothing was on trial); False to try again later (the check failed)."""
    import os
    if not await check(web):
        print("ota: self-check: the update's signature check failed")
        return False
    import lvota
    try:
        if lvota.good():
            print("ota: update kept")
            try:
                os.rename(fault, fault_last)        # the new set starts with a clean count
            except OSError:
                pass
    finally:
        lvota = None
        _drop("lvota")                              # main.py holds none of it after
    return True
