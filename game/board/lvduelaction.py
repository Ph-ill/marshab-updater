# Phone actions, loaded only for a POST, not while receiving radio moves.
def api(web, req):
    import json
    import lvship
    sh = web.ship
    if web.get_phone().who(req) is None:
        return 401, {"err": "signed out"}
    if sh.clock.learn_headers(req.header):
        sh.day_check()
    if req.method != "POST":
        return 404, {"err": "no such thing"}
    try:
        b = json.loads(req.body or b"{}")
        if not isinstance(b, dict):
            raise ValueError
    except ValueError:
        return 400, {"err": "bad request"}
    if sh.live is None:
        return 409, {"err": "Ship-to-ship is off."}
    import lvduel
    try:
        return action(sh.live, b, lvduel.__dict__)
    finally:
        lvship.drop("lvduel")


def action(lk, b, rules):
    ACTIVE = rules["ACTIVE"]
    box = rules["box"]
    sweep = rules["sweep"]
    store = rules["store"]
    integer = rules["integer"]
    room = rules["room"]
    fresh = rules["fresh"]
    os = rules["os"]
    encode = rules["encode"]
    hexlify = rules["hexlify"]
    now = rules["now"]
    emit = rules["emit"]
    gid = rules["gid"]
    commit = rules["commit"]
    sync = rules["sync"]
    history = rules["history"]
    pending = rules["pending"]
    mine = rules["mine"]
    terminal = rules["terminal"]
    end = rules["end"]
    reveal = rules["reveal"]
    finish = rules["finish"]
    DAY = rules["DAY"]

    j = box(lk)
    if sweep(lk, j):
        store(lk, j)
    a, to = b.get("action"), b.get("to")
    if not integer(to, 0, 7) or to == lk.node.ship:
        return 400, {"err": "Pick a crewmate."}
    if len(lk.out) >= 24 and a not in ("resign", "call", "new", "discard"):
        return 429, {"err": "Your previous moves are on their way."}
    peer = lk.ble.peers.get(to)
    if a == "new" and peer is not None and peer.info and not peer.info.get("cap"):
        return 409, {"err": "This ship needs ship-to-ship enabled and the duel update."}
    g = next((x for x in j["g"] if x["to"] == to and x["s"] in ACTIVE), None)
    if a == "new":
        if g or sum(x["s"] in ACTIVE for x in j["g"]) >= 3:
            return 409, {"err": "A duel is already going, or three duels are open."}
        j["g"] = [x for x in j["g"] if x["to"] != to]
        room(j)
        g = fresh(lk, to, os.urandom(2), lk.node.ship, "draft")
        j["g"].append(g)
    elif g is None:
        return 409, {"err": "No duel is open."}
    elif a == "discard":
        if g["s"] != "draft":
            return 409, {"err": "Your fleet is locked."}
        j["g"].remove(g)
    elif a in ("lock", "invite", "accept"):
        if g.get("l") and g["s"] in ("wait", "active") and any(z[0] in (3, 4) for z in g.get("q", [])):
            store(lk, j)
            return 200, {"ok": True}
        if g["s"] not in ("draft", "invited") or g.get("l") or (a == "accept" and g["s"] != "invited") or (a == "invite" and g["s"] != "draft"):
            return 409, {"err": "Your fleet is locked."}
        try:
            layout = encode(b.get("layout"))
        except (ValueError, TypeError):
            return 400, {"err": "Bad layout. Ships cannot overlap or touch sides."}
        salt = os.urandom(6)
        g["l"], g["salt"] = hexlify(layout).decode(), hexlify(salt).decode()
        kind = 4 if g["s"] == "invited" else 3
        g["s"] = "active" if kind == 4 else "wait"
        g["t"] = now(lk)
        emit(lk, g, kind, bytes((1,)) + gid(g) + commit(gid(g), layout, salt))
        sync(lk, g)
    elif a == "fire":
        cell = b.get("cell")
        if not integer(cell, 0, 35) or cell in [z[1] for z in history(g) if mine(lk, g, z[0])] or cell == g.get("p"):
            return 400, {"err": "Bad cell or already fired."}
        if pending(lk, g):
            return 429, {"err": "Your previous move is on its way."}
        if g["s"] != "active" or g.get("p") is not None or not mine(lk, g, g["n"] + 1):
            return 409, {"err": "It is not your turn."}
        g["p"] = cell
        g["t"] = now(lk)
        emit(lk, g, 5, gid(g) + bytes((g["n"] + 1, cell)))
    elif a == "decline":
        if g["s"] != "invited":
            return 409, {"err": "No invitation is waiting."}
        terminal(g, "declined")
        end(lk, g, 1)
    elif a == "resign":
        if g["s"] not in ("wait", "invited", "active"):
            return 409, {"err": "No duel is playing."}
        terminal(g, "called")  # discard obsolete moves before the terminal exchange
        g["s"], g["win"] = "reveal", False
        g["why"] = 2
        end(lk, g, 2)
        reveal(lk, g)
        if not g.get("c"):
            g["verified"] = 1
            finish(lk, j, g)
    elif a == "call":
        t = now(lk)
        if t is None or g.get("t") is None or t - g["t"] < 3 * DAY or (g["s"] == "active" and mine(lk, g, g["n"] + 1) and g.get("p") is None):
            return 409, {"err": "Wait three days for the next move."}
        terminal(g, "called")
        end(lk, g, 3)
    else:
        return 400, {"err": "Bad duel action."}
    store(lk, j)
    return 200, {"ok": True}
