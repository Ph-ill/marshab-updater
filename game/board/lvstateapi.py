# Story responses are loaded per request, not retained through OTA or light playback.
from lv import ops as O
from lv import record as R
from lv import engage as EN
from lv.engine import Engine
from lv.state import N
import lvphone

# ---- /api/state
def state_body(self, you, last, minute):
    """Everything in /api/state except "story" (streamed separately)."""
    sh = self.ship
    st, p, log = sh.st, sh.pack, sh.log
    d = st.day
    eng = Engine(p, st, log)
    opens = []
    for it in st.pend:
        ctype, idx, opened, close = it[0], it[1], it[2], it[3]
        A, B = it[4], it[5]
        if ctype == O.DILEMMA and A != you:
            continue
        card = p.cards[idx]
        kind = R.DILEMMA if ctype == O.DILEMMA else R.VOTE
        tally = [0] * card.nopt
        mine = None
        for s, o in log.answers(kind, idx, opened, close):
            if o < card.nopt:
                tally[o] += 1
            if s == you:
                mine = o
        if ctype == O.DECISION:
            lean = card.lpos if eng.fleet_lean(card.laxis) >= 0 else card.lneg
        elif ctype == O.DILEMMA:
            lean = card.lpos if st.trait(A, card.laxis) >= 0 else card.lneg
        else:
            lean = card.lpos
        opens.append({"type": ctype, "card": idx, "a": A, "b": B, "opened": opened,
                      "close": close, "tally": tally, "mine": mine, "lean": lean})
    act = None
    for r in log.values():
        if R.kind(r) == R.ACTION and R.ship(r) == you and R.day(r) == d:
            act = [r[5], r[6], r[7]]
    best = []
    for c in range(N):
        bj, bb = -1, None
        for j in range(N):
            if j != c and (bb is None or st.bond(c, j) > bb):
                bj, bb = j, st.bond(c, j)
        best.append(bj)
    upd = {}
    for k in sh.days.updated:
        upd[str(k)] = sh.days.updated[k]
    return {
        "day": d, "season": p.season, "you": you, "here": sh.me, "last": last,
        "loc": list(st.loc), "cond": list(st.cond), "morale": list(st.morale),
        "traits": [[st.trait(c, a) for a in range(3)] for c in range(N)],
        "bonds": [st.bond(you, j) for j in range(N)],
        "best": best, "bestb": [st.bond(c, best[c]) for c in range(N)],
        "res": list(st.res), "kit": list(st.medkit),
        "open": opens, "act": act, "ending": st.ending,
        "updated": upd,
        "eng": EN.view(self.eng, self.local, p, st, log, you, minute),
        "v": sh.v, "start": sh.cal.start if sh.cal is not None else None,
        "led": sh.led.enabled,
        # Bluetooth contact, for the crew list and the gift picker: [ship index, seconds
        # since this ship last heard it, its log matched ours then] per ship heard in the
        # last day (lvship keeps lv/ble's peers that long); null with no radio. Ages count
        # to lv/ble's last peer sweep (every 10 s), so no clock of our own. Not in the log.
        "air": [[k, max(0, sh.ble._swept - q.seen) // 1000, q.diff_since is None]
                for k, q in sh.ble.peers.items()] if sh.ble else None,
        # This board's battery (lvbatt.py): [percent, mV, charging], null without one.
        "bat": sh.bat[:3] if sh.bat else None,
    }


def state_writer(self, you, last, minute):
    import json
    from binascii import b2a_base64
    sh = self.ship
    body = state_body(self, you, last, minute)
    # Each field encoded on its own and the dict emptied as it goes, so the whole body
    # never sits on the heap twice (dict + one big JSON string): /api/state is the board's
    # heap peak with two phones playing. Each field is one b',"key":value' allocation,
    # not a tuple plus two buffers (about 1 KB less retained). These bytes
    # give the exact Content-Length (MicroPython's json writes non-ASCII as UTF-8).
    parts = []
    tl = 1                                  # the closing }
    for k in list(body):
        v = body.pop(k)
        kp = (',%s:' % json.dumps(k)).encode()
        v = json.dumps(v).encode()
        parts.append(kp + v)
        tl += len(kp) + len(v)
        v = kp = None
    if lvphone.probe:
        lvphone.probe()
    body = None
    d = sh.st.day
    days = sh.days
    refs = [days.ref(x) for x in range(1, d + 1)]    # this version, even if a replay lands
    n = 0
    for x in range(1, d + 1):
        n += days.length(x)
    pre = b'{"story":"'
    tl += 1                                 # the story's closing quote
    b64 = (n + 2) // 3 * 4

    async def write(w):
        import lvweb
        w.write(lvweb.head(200, "application/json", len(pre) + b64 + tl))
        w.write(pre)
        carry = b""
        days.readers += 1
        try:
            for i in range(len(refs)):
                carry += days.load(refs[i])
                k = len(carry) // 3 * 3
                if k >= 384 or (i == len(refs) - 1 and k):
                    w.write(b2a_base64(carry[:k])[:-1])
                    carry = carry[k:]
                    await lvweb.drain(w)
        finally:
            days.readers -= 1
        if carry:
            w.write(b2a_base64(carry)[:-1])
        w.write(b'"')
        for field in parts:
            w.write(field)
        w.write(b"}")
        if lvphone.probe:
            lvphone.probe()
        await lvweb.drain(w)
    return write
