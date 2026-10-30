# Invitation, reveal and recovery rules, not retained while scoring a shot.
from lvduel import (ACTIVE, belongs, commit, emit, end, finish, fleet, fresh,
                    gid, hexlify, history, keep, lvship, mine, now, rejected,
                    repeat, result, reveal, room, sync, terminal, unhexlify, layout_call)


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
        # Keep one completed game per opponent, for the reveal screen and rematch.
        j["g"] = [x for x in j["g"] if x["to"] != frm or x["s"] in ACTIVE]
        room(j)
        g = fresh(lk, frm, ident, frm, "invited")
        g["c"] = hexlify(b[3:11]).decode()
        j["g"].append(g)
        light = True
    elif g is None:
        tick = lvship.ticks_ms()
        previous = getattr(lk, "duel_unknown", None)
        elapsed = lvship.ticks_diff(tick, previous) if previous is not None else 3600000
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
        g["t"] = now(lk)
    elif kind == 7:
        if g["s"] not in ("reveal", "done", "cheat"):
            sync(lk, g)
        else:
            layout, salt = b[2:5], b[5:11]
            ok = False
            try:
                ok = hexlify(commit(ident, layout, salt)).decode() == g.get("c")
                ok = layout_call("replay", layout, g["h"], g["i"] == lk.node.ship) and ok
            except ValueError:
                ok = False
            if not ok:
                # Undo a previously counted result if a contradictory reveal follows it.
                if g.get("counted"):
                    j["r"][str(frm)][0 if g["win"] else 1] -= 1
                    g["counted"] = 0
                terminal(g, "cheat")
                end(lk, g, 6)
            else:
                g["verified"] = 1
                g["their"] = hexlify(layout).decode()
                if not g.get("sent"):
                    reveal(lk, g)
                finish(lk, j, g)
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
        elif why != 6 and g.get("win") is not None:
            # Fleet results and either resignation outcome already chose a side.
            # Other late END reasons must not replace that terminal decision.
            return
        elif why == 2 and g["s"] in ACTIVE:
            g["why"] = 2
            g["win"], g["s"] = True, "reveal"
            reveal(lk, g)
            if not g.get("c"):
                # The opponent resigned before committing: there were no answers
                # to verify. Our own committed field still goes to the opponent.
                g["verified"] = 1
                finish(lk, j, g)
        elif why == 6:
            if g.get("counted"):
                j["r"][str(frm)][0 if g["win"] else 1] -= 1
                g["counted"] = 0
            terminal(g, "cheat")
        elif g["s"] in ACTIVE:
            terminal(g, {1: "declined", 3: "called", 4: "version", 5: "busy"}.get(why, "called"))
    elif kind == 9:
        n, cell, r, state = b[2:6]
        g["nl"] = bool(state & 128)
        state &= 127
        if n > 71 or state > 4:
            return
        # Stop-and-wait means normally at most one completed answer is missing.
        # If both views say 'my turn', keep the lower ship's view. The higher
        # ship can rewind its existing transcript, or recover its one lost answer.
        conflict = (state == 1 and g["s"] == "active" and g.get("p") is None and
                    mine(lk, g, g["n"] + 1) and not mine(lk, g, n + 1))
        if conflict and lk.node.ship > frm:
            if n <= g["n"]:
                g["h"] = g["h"][:2 * n]
                g["n"] = n
                if n:
                    if (ord(g["h"][-2]) - 65, ord(g["h"][-1]) - 97) != (cell, r):
                        g["h"] = g["h"][:-2] + chr(65 + cell) + chr(97 + r) if cell < 36 and r in (0, 1, 2, 3, 4) else g["h"]
                    g["last"] = [5 if mine(lk, g, n) else 6,
                                 hexlify(ident + bytes((n, cell)) + (b"" if mine(lk, g, n) else bytes((r,)))).decode()]
                return False, None
            if n == g["n"] + 1 and mine(lk, g, n) and cell < 36:
                g["p"] = cell
                g["last"] = [5, hexlify(ident + bytes((n, cell))).decode()]
                return False, (6, ident + bytes((n, cell, r)) + bytes(6))
        elif conflict:
            sync(lk, g)
            return False, None
        # If the peer lacks our last shot/answer, replay it with a new envelope.
        # Equal n + awaiting answer also repairs a pending shot lost before receipt.
        if n < g["n"] or (n == g["n"] and g.get("p") is not None):
            repeat(lk, g)
            if g["s"] in ("reveal", "done"):
                reveal(lk, g)
        elif n > g["n"]:
            if n == g["n"] + 1 and g.get("p") == cell and mine(lk, g, n):
                return False, (6, ident + bytes((n, cell, r)) + bytes(6))
            sync(lk, g)
        elif g["s"] in ("reveal", "done") and state == 3:
            # Replay one bounded terminal group, never echo every REVEAL.
            repeat(lk, g)
            reveal(lk, g)
    return light, None
