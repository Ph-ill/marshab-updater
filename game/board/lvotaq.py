# Over-the-air updates: the upload's wait for a quiet moment (0.3.0). Its own tiny module
# so that main.py can wait before it loads lvotap.py (~3 KB): the wait is when the phones
# and the radio are busiest, and the update's code shouldn't sit on the heap through it.
# Used by main.py's route, lvotap.api (safe mode, lvota.api) and nothing else; dropped after.
QUIET_MS = 60000          # the signature check waits this long at most for the radio
PIECE_MS = 3000           # any other piece waits this long at most for the other requests


def lit(sh, lvship):
    """A light playback still running (sh.ledtest: its start, counted as Test light's 10 s)?
    The same staleness rule as Test light's 429 (lvledtest.start, main.py): a mark more than
    5 s past its end belongs to a task that never ran its finally, so it is cleared here
    instead of making every piece wait QUIET_MS until a restart (0.3.0 review 2 M3)."""
    t = getattr(sh, "ledtest", None)
    if t is None:
        return False
    if 10000 - lvship.ticks_diff(lvship.ticks_ms(), t) > -5000:
        return True
    sh.ledtest = None
    return False


async def quiet(web, q, body):
    """Before the signature check (the envelope's last piece): wait, up to QUIET_MS, until
    no Bluetooth sync is running and this is the only request being answered. The check
    (lvsig, ~4 KB with its code, and its numbers) is the update's biggest moment for the
    heap; a sync with a crewmate back from a long time away is the radio's, and two phones'
    /api/state answers are the web server's. This way none of them is held at the same
    time as the check. Nothing awaits between here and the end of the check, so nothing new
    starts in between (syncs only start in the radio's poll, never in its interrupt handler,
    and requests only in the server's tasks). The phone's upload has no time limit on a
    piece, so it just waits; past QUIET_MS (a sync that won't end, phones that never pause)
    the check goes ahead as before.
    A light playback also retains its code until it ends: all pieces allow QUIET_MS
    for it to finish before loading upload code. Other pieces otherwise wait up to
    PIECE_MS for the other requests only (a sync can
    take minutes, and a piece is small): with the season's whole log in RAM, a piece written
    and hashed while two phones' answers are half sent was the update's peak (~4.5 KB over
    what the game alone needs, tests/mp_sync_heap.py --everyone)."""
    try:
        last = q.get("f") == "0" and int(q.get("o", "-1")) + len(body) >= int(q.get("n", "0"))
    except ValueError:
        return
    b = getattr(getattr(web, "ship", None), "ble", None) if last else None
    import lvship
    ms = QUIET_MS if last or lit(web.ship, lvship) else PIECE_MS
    t0 = lvship.ticks_ms()
    while ((b is not None and b.busy()) or getattr(web, "busy", 0) > 1 or lit(web.ship, lvship)) \
            and lvship.ticks_diff(lvship.ticks_ms(), t0) < ms:
        await lvship.sleep_ms(50)
