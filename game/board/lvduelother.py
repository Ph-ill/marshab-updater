# Invitation, reveal and recovery rules, not retained while scoring a shot.
from lvduel import (ACTIVE, belongs, commit, emit, end, finish, fleet, fresh,
                    defer, gid, hexlify, history, keep, lvship, owed, mine, moved, rejected,
                    repeat, result, retire, reveal, room, sync, terminal, unhexlify, layout_call,
                    maint_call, DAY)

# Idle age under which an END 3 heard while invited reads as a withdrawal.
WD = 3 * DAY - 12 * 3600


def take(lk, frm, kind, b, j):
    # Mutate only: the caller releases this module before durable publication.
    # None means no change; (light, retry) commits before optional recovery.
    ident = b[1:3] if kind in (3, 4) else b[:2]
    g = next((x for x in j["g"] if x["to"] == frm and gid(x) == ident), None)
    if kind in (3, 4) and b[0] != 1:
        temp = fresh(lk, frm, ident, frm, "called")
        rejected(lk, j, temp, 4)
        return False, None
    light = False
    if kind == 3:
        other = next((x for x in j["g"] if x["to"] == frm and x["s"] in ACTIVE), None)
        # Opposing inviter roles must be arbitrated before an ID-only lookup.
        # Equal IDs cannot carry an END: it would also cancel the winning invite.
        if other and other["i"] == lk.node.ship and other["s"] in ("draft", "wait"):
            if frm > lk.node.ship and gid(other) == ident:
                return
            if frm < lk.node.ship:
                if gid(other) == ident:
                    lk.out[:] = [o for o in lk.out if not belongs(o, other)]
                    keep(lk)
                    j["g"].remove(other)
                else:
                    terminal(other, "called")
                    end(lk, other, 3)
                other = g = None
        if g is not None:
            repeat(lk, g)
            return False, None
        if other or sum(x["s"] in ACTIVE for x in j["g"]) >= 3:
            rejected(lk, j, fresh(lk, frm, ident, frm, "called"), 5)
            return False, None
        # Still owing this crewmate a retired game's END/REVEAL, as "new" checks: put
        # the invitation away (END 3) once those items are acked, so at most two stubs
        # (one retired below) are ever owed to one crewmate (review 0.3.1-9 #5).
        # Their ship can invite again then.
        if owed(j, frm):
            rejected(lk, j, fresh(lk, frm, ident, frm, "called"), 3)
            return False, None
        # Keep one completed game per opponent, for the reveal screen and rematch.
        for x in [x for x in j["g"] if x["to"] == frm and x["s"] not in ACTIVE]:
            retire(lk, j, x)
        room(lk, j)
        g = fresh(lk, frm, ident, frm, "invited")
        g["c"] = hexlify(b[3:11]).decode()
        j["g"].append(g)
        light = True
    elif g is None:
        tick = lvship.ticks_ms()
        previous = getattr(lk, "duel_unknown", None)
        elapsed = lvship.ticks_diff(tick, previous) if previous is not None else 3600000
        # A retired game's stub keeps this crewmate's j["e"] slot (review 0.3.1-8 #1);
        # the reply waits on it (review 0.3.1-9 #3).
        if kind not in (8, 9) and owed(j, frm):
            defer(j, frm, hexlify(ident).decode(), 0)
            return False, None
        if kind not in (8, 9) and (elapsed >= 3600000 or elapsed < 0):
            temp = fresh(lk, frm, ident, frm, "called")
            temp["unknown"] = True
            sync(lk, temp)
            j["e"] = [x for x in j.get("e", []) if x["to"] != frm] + [temp]
            lk.duel_unknown = tick
            return False, None
        return
    elif kind == 4:
        if g["s"] != "wait" and not (g.get("why") == 2 and not g.get("c")):
            return
        g["c"] = hexlify(b[3:11]).decode()
        if g["s"] == "wait":
            g["s"] = "active"
        moved(lk, g)
    elif kind == 7:
        return layout_call("proof", lk, frm, b, j, g)
    elif kind == 8:
        why = b[2]
        if why not in (1, 2, 3, 4, 5, 6):
            return
        if why == 2 and g.get("why") == 2 and g.get("win") is False and g["s"] in ("reveal", "done"):
            if g.get("mutual"):
                return
            # A local resignation is immutable, even after verification/counting.
            # Crossing ENDs agree on no result; retract only this game's loss.
            g["mutual"] = 1
            if g.get("counted"):
                r = j["r"][str(frm)]
                r[1] -= 1
                if r == [0, 0]:
                    del j["r"][str(frm)]
                g["counted"] = 0
            reveal(lk, g)
            finish(lk, j, g)
        elif why in (1, 3) and g.get("why") == 2 and g.get("win") is False and g["s"] == "reveal" and not g.get("verified") and not g.get("counted"):
            # A withdrawal or put-away crossed this ship's accept-then-resign (review
            # 0.3.1-7 #2). The other ship gave up its own win and never sends REVEAL:
            # both ships stood down, no result, so nothing waits on "Checking both fields".
            g["mutual"] = 1
            terminal(g, "done")
        elif why != 6 and g.get("win") is not None:
            # Fleet results and either resignation outcome already chose a side.
            # Other late END reasons must not replace that terminal decision.
            return
        elif why == 2 and g["s"] in ACTIVE and g["s"] != "invited":
            # (END 2 in "invited", from a 0.3.1 inviter that resigned before anyone
            # joined, falls through to "called": no result, review 0.3.1-6 #3.)
            g["why"] = 2
            g["win"], g["s"] = True, "reveal"
            reveal(lk, g)
            if not g.get("c"):
                # The opponent resigned before committing: there were no answers
                # to verify. Our own committed field still goes to the opponent.
                g["verified"] = 1
                finish(lk, j, g)
        elif why == 6:
            # "Your answers didn't match" carries no evidence (review 0.3.1-4 #4), and
            # this ship's own answers are never proof of the other field (review
            # 0.3.1-5 #1): a winner could lie in every answer, then send this instead
            # of its REVEAL. A verified or counted finish stands. Before that, only a
            # real resignation keeps its result; anything else ends with no result.
            # Either way the page says the other ship couldn't check this field.
            if j["r"].get(str(frm)) == [0, 0]:
                del j["r"][str(frm)]
            if g["s"] == "done" or g.get("counted"):
                g["doubt"] = 1
            elif g["s"] in ACTIVE:
                g["doubt"] = 1
                if g.get("why") == 2 and g.get("win") is not None:
                    g["verified"] = 1
                    finish(lk, j, g)
                if g["s"] in ACTIVE:
                    terminal(g, "cheat")
        elif g["s"] in ACTIVE:
            # The inviter withdrew it (review 0.3.1-7 #3), unless the invitation is
            # near its 3-day put-away: then the inviter's own sweep may have sent
            # this END, and the page says "Duel put away" (review 0.3.1-8 #3).
            if why == 3 and g["s"] == "invited" and maint_call("age", lk, g) < WD:
                g["wd"] = 2
            terminal(g, {1: "declined", 3: "called", 4: "version", 5: "busy"}.get(why, "called"))
    elif kind == 9:
        n, cell, r, state = b[2:6]
        g["nl"] = bool(state & 128)
        state &= 127
        if n > 71 or state > 4:
            return
        # Moves are append-only (review 0.3.1-4 #2, #3). A SYNC never rewinds this
        # transcript, never rewrites a stored answer and never makes up one of our
        # shots: only this ship fires its shots, and only the peer's ANSWER to a shot
        # this ship is waiting on gives its result. The peer's last move has to be
        # the one recorded at that number; a different one contradicts the game both
        # ships committed to, so an active game ends there with no result.
        if n and n <= g["n"]:
            i = 2 * n - 2
            if (ord(g["h"][i]) - 65, ord(g["h"][i + 1]) - 97) != (cell, r):
                if g["s"] == "active":
                    terminal(g, "cheat")
                    end(lk, g, 6)
                    return False, None
                return
        # If the peer lacks our last shot/answer, replay it with a new envelope.
        # Equal n + awaiting answer also repairs a pending shot lost before receipt.
        if n < g["n"] or (n == g["n"] and g.get("p") is not None):
            repeat(lk, g)
            if g["s"] in ("reveal", "done"):
                reveal(lk, g)
        elif n > g["n"]:
            # Our own pending shot, answered but the ANSWER lost: the shot is ours.
            if n == g["n"] + 1 and g["s"] == "active" and g.get("p") == cell and mine(lk, g, n):
                return False, (6, ident + bytes((n, cell, r)) + bytes(6))
            sync(lk, g)
        elif g["s"] in ("reveal", "done") and state == 3:
            # Replay one bounded terminal group, never echo every REVEAL.
            repeat(lk, g)
            reveal(lk, g)
    return light, None
