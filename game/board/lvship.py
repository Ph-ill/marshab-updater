# Bench runtime for one ship (Pico W / Pico 2 W, MicroPython 1.29): the choice log, the
# story replay, BLE sync with the other ships, the hotspot and a small status server.
# It is not the game's phone server yet; it is what the bench needs to prove that
# ships find each other, swap records and keep the story identical, with Wi-Fi up.
#
#   main.py       runs at boot: hotspot (lvwifi.py), then Ship(...).loop() and the server
#   selftest.py   selftest.run(...) from the REPL or mpremote (see docs/BENCH_TEST.md)
# Kept apart so the running ship carries only this module's code.
#
# Settings come from /data/ship.json (written by the web updater or by hand) on top of
# DEFAULTS. Nothing secret lives in this file: the hotspot password is per board, and
# the fleet key below is the public test key the simulator uses.
import gc

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

from lv.pack import load, Pack
from lv.chlog import ChoiceLog
from lv.state import State, N
from lv.engine import Engine
from lv import record as R
from lv import sync as S
from lv.clock import Clock, ticks_ms, ticks_diff
from lv.led import Notifier

try:
    sleep_ms = asyncio.sleep_ms
except AttributeError:     # CPython (the tests)
    def sleep_ms(ms):
        return asyncio.sleep(ms / 1000)

VERSION = "0.1.0-lv-test"

DEFAULTS = {
    "ship_id": 1,                  # 1-8 (ship 1 = crew 0)
    "ship_name": "",
    "fleet_key": "test-fleet-key-not-secret",
    "day": 1,                      # bench flight day (no phone clock on the bench)
    "story": True,                 # replay the story as records arrive
    "hotspot": True,               # SoftAP for phones (BLE coexists with it)
    "ssid_prefix": "LV-",
    "hotspot_password": "",        # 8-63 chars in /data/ship.json; else "CHANGE_ME" (public)
    "hotspot_open": False,
    "channel": 6,
    "country": "US",
    "http_port": 80,
    "led_notify": False,           # the LED notifier stays off unless this says true
    "stat_every_s": 60,
    "ble": {},                     # overrides for lv/ble.DEFAULTS (scan duty, intervals...)
}


def load_config(path="/data/ship.json"):
    c = dict(DEFAULTS)
    try:
        import json
        with open(path) as f:
            c.update(json.load(f))
    except Exception:              # a missing or broken file never stops the board
        pass
    try:
        c["ship_id"] = min(8, max(1, int(c["ship_id"])))
    except (TypeError, ValueError):
        c["ship_id"] = 1
    return c


def free():
    gc.collect()
    return gc.mem_free() if hasattr(gc, "mem_free") else -1


def used():
    gc.collect()
    return gc.mem_alloc() if hasattr(gc, "mem_alloc") else -1


def pack_for(root=""):
    # The game firmware (tools/build_firmware.sh) freezes the pack into flash as lvdata.PACK:
    # read in place, it costs no heap. It is used only when it was built with this exact
    # lvship (a newer lvship copied over the frozen firmware brings its own pack.bin).
    try:
        import lvdata
        if lvdata.VERSION == VERSION:
            return Pack(lvdata.PACK), "frozen"
    except ImportError:
        pass
    return load(root + "pack.bin"), "file"


class Ship:
    SNAP_EVERY = 7
    SNAPS = 3          # weekly snapshots kept (743 B each); older rewinds start from day 0

    def __init__(self, cfg, root="", data="/data", ble=None, say=print, radio=True):
        self.cfg = cfg
        self.say = say
        self.me = cfg["ship_id"] - 1
        self.fk = bytes(cfg["fleet_key"], "utf-8")
        self.pack, self.pack_src = pack_for(root)
        self.day = min(max(0, int(cfg["day"])), self.pack.season)
        self.log = ChoiceLog(self.fk)
        self.data = data
        self.st = None
        self.snaps = {}
        self.replays = 0
        self.gifts_in = []         # (from ship, item, day) of gifts to this ship
        self.gifts_out = 0
        self.http_hits = 0
        self.mem_peak = 0
        self.clock = Clock()
        self.led = Notifier(self.clock, cfg["led_notify"])
        self.ready = False
        self._load_log()
        self.node = S.Node(self.log, self.me, self.fk, self.day, self._new)
        for r in self.log.values():
            self._gift_seen(r)
        if cfg["story"]:
            self.st = State(self.pack)
            self.tick_to(self.day)
        self.led.set_waiting(bool(self.gifts_in))
        self.ready = True
        self.ble = None
        if radio:
            from lv.ble import BleSync
            self.ble = BleSync(self.node, ble, cfg["ble"], say)

    # ---- the log on flash: records appended as they arrive (replacements too;
    # merging the file back in order keeps the winner)
    def _load_log(self):
        if not self.data:
            return
        try:
            with open(self.data + "/log.bin", "rb") as f:
                while True:
                    b = f.read(R.LEN * 16)
                    if not b:
                        break
                    for i in range(0, len(b) - R.LEN + 1, R.LEN):
                        self.log.merge(b[i:i + R.LEN])
        except OSError:
            pass

    def _keep(self, recs):
        if not self.data:
            return
        try:
            with open(self.data + "/log.bin", "ab") as f:
                for r in recs:
                    f.write(r)
        except OSError as e:
            self.say("log: write failed %s" % e)

    # ---- story
    def tick_to(self, day):
        while self.st.day < day:
            Engine(self.pack, self.st, self.log).tick()
            if self.st.day % self.SNAP_EVERY == 0:
                self.snaps[self.st.day] = self.st.dump()
                if len(self.snaps) > self.SNAPS:
                    del self.snaps[min(self.snaps)]

    def _new(self, recs):
        # Records that just arrived over BLE (lv.sync.Node.on_new).
        self._keep(recs)
        earliest = None
        for r in recs:
            self._gift_seen(r)
            e = R.eff_day(r)
            if earliest is None or e < earliest:
                earliest = e
        if self.st is not None and earliest is not None and earliest <= self.st.day:
            # A late record lands in a day already told: rewind to the snapshot before it.
            now = self.st.day
            older = [k for k in self.snaps if k < earliest]
            base = max(older) if older else 0
            for k in [k for k in self.snaps if k > base]:
                del self.snaps[k]
            self.st = State.load(self.snaps[base]) if base else State(self.pack)
            self.replays += 1
            self.tick_to(now)

    def _gift_seen(self, r):
        if R.kind(r) == R.GIFT and r[6] == self.me and R.ship(r) != self.me:
            self.gifts_in.append((R.ship(r), r[5], R.day(r)))
            if len(self.gifts_in) > 8:
                self.gifts_in.pop(0)
            self.led.set_waiting(True)
            if self.ready:
                self.say("gift: from ship %d, item %d, day %d" % (R.ship(r) + 1, r[5], R.day(r)))

    def gift(self, to_ship, item=0):
        """Author a gift from this ship's crew member to ship to_ship (1-8): the same
        record the phone's gift button makes. Returns the record."""
        to = int(to_ship) - 1
        if not (0 <= to < N) or to == self.me:
            raise ValueError("pick another ship, 1-8")
        seq = self.log.seq_vector()[self.me] + 1
        rec = R.encode(self.fk, R.GIFT, self.me, 1, seq, max(1, self.day), item & 255, to, R.GIFT_GIVE)
        if self.node.add(rec):
            self._keep([rec])
            self.gifts_out += 1
        return rec

    # ---- status
    def status(self):
        now = self.clock.uptime()
        u = used()
        if u > self.mem_peak:
            self.mem_peak = u
        s = {"ship": self.me + 1, "version": VERSION, "day": self.day, "records": len(self.log),
             "digest": self.node.digest().hex(), "story": self.st.hexdigest() if self.st else None,
             "replays": self.replays, "gifts_in": len(self.gifts_in), "gifts_out": self.gifts_out,
             "led": {"enabled": self.led.enabled, "waiting": self.led.waiting, "writes": self.led.writes,
                     "time_known": self.clock.known()},
             "heap_used": u, "heap_free": free(), "heap_peak": self.mem_peak, "http": self.http_hits}
        s["ble"] = self.ble.status(now) if self.ble else None
        return s

    def stat_line(self):
        s = self.status()
        b = s["ble"] or {"state": "off", "peers": [], "n": {}}
        n = b["n"]
        peers = " ".join(["%d%s" % (p["ship"], "=" if p["same"] else "*") for p in b["peers"]]) or "-"
        return ("STAT ship=%d recs=%d digest=%s ble=%s peers=%s ok=%s fail=%s sent=%s got=%s new=%s "
                "gifts_in=%d led=%s heap_used=%d heap_free=%d" % (
                    s["ship"], s["records"], s["digest"], b["state"], peers, n.get("ok"), n.get("fail"),
                    n.get("sent"), n.get("got"), n.get("new"), s["gifts_in"],
                    "on" if self.led.enabled else "off", s["heap_used"], s["heap_free"]))

    # ---- HTTP: a small status server (the game's phone server is separate work)
    async def http(self, reader, writer):
        try:
            line = await reader.readline()
            hdr = {}
            for _ in range(24):
                h = await reader.readline()
                if not h or h in (b"\r\n", b"\n"):
                    break
                i = h.find(b":")
                if i > 0:
                    hdr[str(h[:i].strip().lower(), "utf-8")] = str(h[i + 1:].strip(), "utf-8")
            self.clock.learn_headers(hdr.get)
            self.http_hits += 1
            parts = str(line, "utf-8").split(" ")
            path = parts[1] if len(parts) > 1 else "/"
            code, body, ctype = 200, None, "application/json"
            if path.startswith("/api/gift"):
                q = path.split("to=")
                try:
                    r = self.gift(int(q[1].split("&")[0]) if len(q) > 1 else 0)
                    body = '{"gift":"%s"}' % r.hex()
                except (ValueError, IndexError) as e:
                    code, body = 400, '{"error":"%s"}' % e
            elif path.startswith("/api/sync"):
                import json
                body = json.dumps(self.status())
            elif path == "/" or path.startswith("/status"):
                ctype, body = "text/plain", self.stat_line() + "\n"
            else:
                code, body = 302, ""
            body = bytes(body, "utf-8")
            writer.write(bytes("HTTP/1.0 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n%s\r\n" % (
                code, ctype, len(body), "Location: /\r\n" if code == 302 else ""), "utf-8"))
            writer.write(body)
            await writer.drain()
        except Exception as e:      # one bad request never takes the server down
            self.say("http: %s" % e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def loop(self, stop_after_ms=None, stat_every_ms=None, until=None):
        t0 = ticks_ms()
        every = stat_every_ms or self.cfg["stat_every_s"] * 1000
        nxt = every
        while True:
            now = ticks_diff(ticks_ms(), t0)
            if self.ble:
                self.ble.poll(now)
            wait = self.led.poll(self.ble.busy() if self.ble else False)
            if now >= nxt:
                nxt = now + every
                self.say(self.stat_line())
            if stop_after_ms is not None and now >= stop_after_ms:
                return
            if until is not None and until():
                return
            await sleep_ms(min(50, wait))
