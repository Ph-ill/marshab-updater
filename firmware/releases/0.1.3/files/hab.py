import json
import secrets
import time

PROTOCOL = 1
PLAYER_TTL = 30
MAX_CREDIT_DELTA = 25
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECS = 30
MAX_PLAYERS = 4
CHARACTERS = {"astronaut", "robot", "frog"}


def _normalize_look(look):
    character = "astronaut"
    if isinstance(look, dict) and look.get("character") in CHARACTERS:
        character = look["character"]
    return {"character": character}


def _default_save():
    return {
        "v": 1,
        "habId": "hab_demo",
        "passportId": "ppt_demo",
        "owner": {"name": "Crew", "look": {"character": "astronaut"}},
        "credits": 320,
        "room": {
            "size": [8, 8],
            "placed": [
                {"uid": "p1", "itemId": "desk_starship", "cell": [5, 2], "rot": 0},
                {"uid": "p2", "itemId": "rug_regolith", "cell": [3, 4], "rot": 0},
            ],
        },
        "inventory": [],
        "carriedGift": None,
        "giftsReceived": [],
        "deliveredReceipts": [],
    }


def _default_ledger():
    return {}


class Hab:
    def __init__(self, storage, now_fn=None, config=None):
        self.storage = storage
        self.now_fn = now_fn or time.time
        self.config = {
            "habId": "hab_demo",
            "ownerName": "Crew",
            "pin": "0000",
            "ssid": "MarsHab-Crew",
        }
        if config:
            self.config.update(config)
        self.tokens = {}
        self.players = {}
        self.login_failures = []
        self.locked_until = 0

    def handle(self, method, path, body=None, token=None):
        if method == "GET" and path == "/api/hello":
            return 200, self.hello()
        if method == "POST" and path == "/api/login":
            return self.login(body or {})
        if method == "POST" and path == "/api/passport":
            return self.passport(body or {})
        if method == "GET" and path == "/api/state":
            return self.state(token)
        if method == "POST" and path == "/api/move":
            return self.move(token, body or {})
        if path == "/api/save" and method == "GET":
            return self.get_save(token)
        if path == "/api/save" and method == "POST":
            return self.post_save(token, body or {})
        if method == "POST" and path == "/api/gift/deliver":
            return self.gift_deliver(token, body or {})
        return 404, {"error": "not_found"}

    def hello(self):
        save = self.load_save()
        has_owner = bool(save.get("ownerPin") or self.config.get("pin"))
        return {
            "habId": self.config["habId"],
            "ownerName": save.get("owner", {}).get("name") or self.config["ownerName"],
            "protocol": PROTOCOL,
            "hasOwner": has_owner,
        }

    def login(self, body):
        now = self.now_fn()
        if now < self.locked_until:
            return 429, {"error": "locked"}
        pin = str(body.get("pin", ""))
        expected = str(self.load_save().get("ownerPin") or self.config.get("pin") or "0000")
        if pin != expected:
            self.login_failures = [ts for ts in self.login_failures if now - ts < LOGIN_LOCK_SECS]
            self.login_failures.append(now)
            if len(self.login_failures) >= LOGIN_MAX_FAILS:
                self.locked_until = now + LOGIN_LOCK_SECS
                self.login_failures = []
            return 401, {"error": "bad_pin"}
        self.login_failures = []
        token = self._mint_token("owner")
        self.tokens[token] = {"role": "owner", "playerId": "you", "issued": now}
        self._upsert_owner_player(token)
        return 200, {"token": token, "role": "owner"}

    def passport(self, body):
        now = self.now_fn()
        passport = body.get("passport")
        if not isinstance(passport, dict):
            return 400, {"error": "bad_passport"}
        if not passport.get("passportId") or not passport.get("name") or not isinstance(passport.get("look"), dict):
            return 400, {"error": "bad_passport"}
        self._expire_players()
        existing_id = self._find_player_by_passport(passport["passportId"])
        if existing_id is None and len(self.players) >= MAX_PLAYERS:
            return 429, {"error": "room_full"}
        player_id = existing_id or f"visitor-{passport['passportId']}"
        token = self._mint_token("visitor")
        self.tokens[token] = {"role": "visitor", "playerId": player_id, "issued": now, "passport": passport}
        existing_cell = self.players.get(player_id, {}).get("cell", {"x": 4, "y": 4})
        existing_facing = self.players.get(player_id, {}).get("facing", 0)
        self.players[player_id] = {
            "playerId": player_id,
            "passportId": passport["passportId"],
            "name": passport["name"],
            "look": _normalize_look(passport.get("look") or {}),
            "cell": existing_cell,
            "facing": existing_facing,
            "last": now,
            "role": "visitor",
            "token": token,
            "passport": passport,
        }
        return 200, {"token": token, "role": "visitor", "playerId": player_id}

    def state(self, token):
        auth = self._require_auth(token)
        if auth[0] is None:
            return auth[1], auth[2]
        role, player = auth
        now = self.now_fn()
        self._expire_players(now)
        if player is not None:
            player["last"] = now
        save = self.load_save()
        players = []
        for pl in self.players.values():
            players.append({
                "playerId": pl["playerId"],
                "name": pl["name"],
                "look": _normalize_look(pl.get("look") or {}),
                "cell": dict(pl.get("cell") or {"x": 4, "y": 4}),
                "facing": pl.get("facing", 0),
            })
        you = {"playerId": player["playerId"], "role": role}
        if role == "owner":
            you["credits"] = save.get("credits", 0)
        gifts = [
            {"id": g.get("uid"), "cell": g.get("cell"), "fromName": g.get("fromName"), "itemId": g.get("itemId")}
            for g in (save.get("giftsReceived") or [])
        ]
        return 200, {
            "room": {
                "layout": save.get("room", {}).get("placed", []),
                "meta": {"habId": self.config["habId"], "ownerName": save.get("owner", {}).get("name") or self.config["ownerName"]},
                "size": save.get("room", {}).get("size", [8, 8]),
            },
            "players": players,
            "gifts": gifts,
            "you": you,
        }

    def move(self, token, body):
        auth = self._require_auth(token)
        if auth[0] is None:
            return auth[1], auth[2]
        _, player = auth
        cell = body.get("cell")
        facing = body.get("facing", 0)
        if not isinstance(cell, dict) or not isinstance(cell.get("x"), int) or not isinstance(cell.get("y"), int):
            return 400, {"error": "bad_cell"}
        save = self.load_save()
        width, height = save.get("room", {}).get("size", [8, 8])
        if cell["x"] < 0 or cell["y"] < 0 or cell["x"] >= width or cell["y"] >= height:
            return 400, {"error": "out_of_bounds"}
        player["cell"] = {"x": cell["x"], "y": cell["y"]}
        player["facing"] = facing
        player["last"] = self.now_fn()
        return 200, {"ok": True}

    def get_save(self, token):
        auth = self._require_auth(token)
        if auth[0] is None:
            return auth[1], auth[2]
        role, _ = auth
        if role != "owner":
            return 403, {"error": "forbidden"}
        return 200, {"save": self.load_save()}

    def post_save(self, token, body):
        auth = self._require_auth(token)
        if auth[0] is None:
            return auth[1], auth[2]
        role, _ = auth
        if role != "owner":
            return 403, {"error": "forbidden"}
        proposed = body.get("save")
        if not isinstance(proposed, dict):
            return 400, {"error": "bad_save"}
        current = self.load_save()
        next_save = self._normalize_save(proposed)
        if not isinstance(next_save.get("v"), int) or not isinstance(next_save.get("room"), dict) or not isinstance(next_save.get("credits"), int):
            return 400, {"error": "bad_save"}
        if next_save["credits"] > current.get("credits", 0) + MAX_CREDIT_DELTA:
            next_save["credits"] = current.get("credits", 0) + MAX_CREDIT_DELTA
        next_save["giftsReceived"] = current.get("giftsReceived", []) if not isinstance(next_save.get("giftsReceived"), list) else next_save.get("giftsReceived", [])
        next_save["deliveredReceipts"] = current.get("deliveredReceipts", []) if not isinstance(next_save.get("deliveredReceipts"), list) else next_save.get("deliveredReceipts", [])
        self.persist_save(next_save)
        self._refresh_owner_player()
        return 200, {"ok": True, "save": next_save}

    def gift_deliver(self, token, body):
        auth = self._require_auth(token)
        if auth[0] is None:
            return auth[1], auth[2]
        role, player = auth
        if role != "visitor":
            return 403, {"error": "forbidden"}
        passport = player.get("passport") or {}
        carried = passport.get("carriedGift")
        if not isinstance(carried, dict):
            return 400, {"error": "no_carried_gift"}
        item_id = body.get("itemId")
        cell = body.get("cell")
        if item_id != carried.get("itemId"):
            return 400, {"error": "gift_mismatch"}
        if not isinstance(cell, list) or len(cell) != 2 or not all(isinstance(v, int) for v in cell):
            return 400, {"error": "bad_cell"}
        save = self.load_save()
        width, height = save.get("room", {}).get("size", [8, 8])
        if cell[0] < 0 or cell[1] < 0 or cell[0] >= width or cell[1] >= height:
            return 400, {"error": "out_of_bounds"}
        key = f"{passport.get('passportId')}|{carried.get('itemId')}|{carried.get('giftNonce')}"
        ledger = self.load_ledger()
        if key in ledger:
            return 200, {"receipt": ledger[key], "duplicate": True}
        now = int(self.now_fn())
        uid = f"g_{secrets.token_hex(4)}"
        placed = {"uid": uid, "itemId": carried.get("itemId"), "cell": cell, "rot": 0}
        received = {"uid": uid, "itemId": carried.get("itemId"), "cell": cell, "fromName": passport.get("name") or "someone", "ts": now}
        save = self._normalize_save(save)
        save["room"]["placed"].append(placed)
        save["giftsReceived"].append(received)
        receipt = {
            "giftNonce": carried.get("giftNonce"),
            "itemId": carried.get("itemId"),
            "hostHabId": self.config["habId"],
            "fromName": passport.get("name") or "",
            "ts": now,
        }
        ledger[key] = receipt
        self.persist_save(save)
        self.persist_ledger(ledger)
        return 200, {"receipt": receipt}

    def load_save(self):
        raw = self.storage.read("save.json")
        if not raw:
            save = _default_save()
            save["habId"] = self.config["habId"]
            save["owner"]["name"] = self.config["ownerName"]
            return save
        try:
            save = json.loads(raw.decode("utf-8"))
        except Exception:
            save = _default_save()
        return self._normalize_save(save)

    def persist_save(self, save):
        self.storage.write("save.json", json.dumps(save, separators=(",", ":")).encode("utf-8"))

    def load_ledger(self):
        raw = self.storage.read("ledger.json")
        if not raw:
            return _default_ledger()
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return _default_ledger()

    def persist_ledger(self, ledger):
        self.storage.write("ledger.json", json.dumps(ledger, separators=(",", ":")).encode("utf-8"))

    def _mint_token(self, role):
        return f"{role}-{secrets.token_hex(8)}"

    def _require_auth(self, token):
        if not token or token not in self.tokens:
            return None, 401, {"error": "unauthorized"}
        auth = self.tokens[token]
        player = self.players.get(auth["playerId"])
        if player is None and auth["role"] == "owner":
            self._upsert_owner_player(token)
            player = self.players.get(auth["playerId"])
        return auth["role"], player

    def _normalize_save(self, save):
        normalized = dict(save)
        normalized.setdefault("v", 1)
        normalized.setdefault("habId", self.config["habId"])
        owner = dict(normalized.get("owner") or {})
        owner.setdefault("name", self.config["ownerName"])
        owner["look"] = _normalize_look(owner.get("look") or {})
        normalized["owner"] = owner
        room = dict(normalized.get("room") or {})
        room.setdefault("size", [8, 8])
        room.setdefault("placed", [])
        normalized["room"] = room
        normalized.setdefault("inventory", [])
        normalized.setdefault("carriedGift", None)
        normalized.setdefault("giftsReceived", [])
        normalized.setdefault("deliveredReceipts", [])
        return normalized

    def _upsert_owner_player(self, token):
        now = self.now_fn()
        save = self.load_save()
        self.players["you"] = {
            "playerId": "you",
            "passportId": save.get("passportId"),
            "name": save.get("owner", {}).get("name") or self.config["ownerName"],
            "look": _normalize_look(save.get("owner", {}).get("look") or {}),
            "cell": self.players.get("you", {}).get("cell", {"x": 4, "y": 4}),
            "facing": self.players.get("you", {}).get("facing", 0),
            "last": now,
            "role": "owner",
            "token": token,
        }

    def _refresh_owner_player(self):
        for token, auth in self.tokens.items():
            if auth.get("role") == "owner":
                self._upsert_owner_player(token)
                break

    def _expire_players(self, now=None):
        now = self.now_fn() if now is None else now
        stale = []
        for player_id, player in self.players.items():
            if now - player.get("last", 0) > PLAYER_TTL:
                stale.append(player_id)
        for player_id in stale:
            self.players.pop(player_id, None)
            doomed = [tok for tok, auth in self.tokens.items() if auth.get("playerId") == player_id and auth.get("role") == "visitor"]
            for tok in doomed:
                self.tokens.pop(tok, None)

    def _find_player_by_passport(self, passport_id):
        for player_id, player in self.players.items():
            if player.get("passportId") == passport_id:
                return player_id
        return None
