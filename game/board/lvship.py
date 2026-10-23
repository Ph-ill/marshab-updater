# One ship (Pico W / Pico 2 W, MicroPython 1.29): the choice log, the story replay (every
# day's story kept for the phones), BLE sync with the other ships, and the taps phones make.
#
#   main.py       runs at boot: hotspot (lvwifi.py), then Ship(...).loop() and the web server
#   lvweb.py      the web server: captive portal, the phone page from flash, bench status
#   lvphone.py    the phone game's JSON API (what sim/mockserver.py serves on a PC)
#   selftest.py   selftest.run(...) from the REPL or mpremote (see docs/BENCH_TEST.md)
# Kept apart so the running ship carries only the code it uses.
#
# Settings come from /data/ship.json (written by the web updater or by hand) on top of
# DEFAULTS. Nothing secret lives in this file: the hotspot password is per board, and
# the fleet key below is the public test key the simulator uses.
import gc
import sys

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

from lv.pack import load
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
    "day": 1,                      # bench flight day, used when there's no launch_date
    "launch_date": "",             # "YYYY-MM-DD": flight day 1 starts 06:00 local that day (lvcal.py)
    "day_start": "06:00",          # when a flight day rolls over (bench tests move it)
    "story": True,                 # replay the story as records arrive
    "hotspot": True,               # SoftAP for phones (BLE coexists with it)
    "ssid_prefix": "LV-",
    "hotspot_password": "",        # 8-63 chars in /data/ship.json; else "CHANGE_ME" (public)
    "hotspot_open": False,
    "channel": 6,
    "country": "US",
    "http_port": 80,
    "captive_dns": True,           # answer every DNS name with the board (captive portal)
    "phone_game": "auto",          # serve the phone game: auto = on the game firmware only
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


def phone_game(cfg):
    """Serve the phone game (lvweb + lvphone)? "auto": only when the game firmware's frozen
    core is in use; on stock MicroPython the heap can't hold it (docs/BENCH_TEST.md)."""
    v = cfg.get("phone_game", "auto")
    if v != "auto":
        return bool(v)
    return game_fw()


def game_fw():
    """Is the game firmware's frozen core in use (not stock MicroPython)?"""
    try:
        import lv
        core, _ = lv.firmware()
        return core is not None and not core["shadowed"]
    except Exception:
        return False


def drop(name):
    """Forget a module loaded for a moment (lvledcfg) so its code leaves the heap."""
    try:
        del sys.modules[name]
    except KeyError:
        pass


def free():
    gc.collect()
    return gc.mem_free() if hasattr(gc, "mem_free") else -1


def used():
    gc.collect()
    return gc.mem_alloc() if hasattr(gc, "mem_alloc") else -1


def pack_for(root=""):
    # The story pack is content: always a file the updater can replace (pack.bin).
    return load(root + "pack.bin"), "file"


class Ship:
    SNAP_EVERY = 7
    SNAPS = 3          # weekly snapshots kept (743 B each); older rewinds start from day 0

    def __init__(self, cfg, root="", data="/data", ble=None, say=print, radio=True, days=None):
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
        self.days = days           # lvdays.Days: each day's story kept for the phones (or None)
        self.v = 0                 # bumped whenever what a phone sees may have changed
        self.replays = 0
        self.gifts_in = []         # (from ship, item, day) of gifts to this ship
        self.gifts_out = 0
        self.http_hits = 0
        self.mem_peak = 0
        self.clock = Clock()
        self.led = Notifier(self.clock, False)    # dark; lvled.Led replaces it when switched on
        self.web = None            # lvweb.Server, if the phone game runs (its busy count)
        if cfg["led_notify"]:
            self.led_on(True)
        self.ready = False
        self.cal = None            # lvcal.Calendar with a launch date, else the manual day
        if cfg.get("launch_date"):
            import lvcal
            self.cal = lvcal.Calendar(cfg, self.clock, self.pack.season, data, say)
            if self.cal.launch is None:
                say("calendar: launch_date %r not understood (YYYY-MM-DD): manual day %d" % (
                    cfg["launch_date"], self.day))
                self.cal = None
            else:
                self.day = self.cal.poll()
        self._load_log()
        self.node = S.Node(self.log, self.me, self.fk, self.day, self._new)
        for r in self.log.values():
            self._gift_seen(r)
        if cfg["story"]:
            self.st = State(self.pack)
            self.tick_to(self.day)
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

    # ---- the LED notifier (lvled.py, loaded only when it is switched on)
    def led_on(self, on):
        """Switch the LED notifier on or off while running (ship.json led_notify at boot,
        the phone's Ship light switch, the selftest). Returns whether it is on. Game
        firmware only: on stock MicroPython its code would push the heap past the 80 KB
        cap (BENCH_TEST.md), so it stays dark there ("led_notify": "force" overrides)."""
        if on and not game_fw() and self.cfg.get("led_notify") != "force":
            self.say("led: the notifier needs the game firmware (no heap for it on stock MicroPython)")
            on = False
        if not (on or self.led.enabled):
            return False
        import lvledcfg
        try:
            return lvledcfg.switch(self, on)
        finally:
            drop("lvledcfg")

    def _led(self, what):
        if self.led.enabled:                  # (lv/led.py's dark Notifier never is)
            self.led.note(what)

    # ---- the flight day
    def day_check(self):
        """With a launch date: move to today's flight day if it has come (lvcal.py). Called
        on every phone request (after its clock is learned) and every 10 s by loop()."""
        return self.cal is not None and self.cal.advance(self)

    # ---- story
    def tick_to(self, day):
        while self.st.day < day:
            Engine(self.pack, self.st, self.log).tick()
            d = self.st.day
            if self.days is not None:
                self.days.put(d, bytes(self.st.out), self.day)
            if d % self.SNAP_EVERY == 0:
                self.snaps[d] = self.st.dump()
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
        self.v += 1
        self._rewind(earliest)

    def _rewind(self, earliest):
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

    def tap(self, crew, kind, a, b=0, c=0):
        """A phone tap: crew (0-7, whoever signed in here) signs a record for today. The
        sequence number follows that crew member's highest one in the log. Returns it."""
        seq = self.log.seq_vector()[crew] + 1
        rec = R.encode(self.fk, kind, crew, 1, seq, max(1, self.day), a & 255, b & 255, c & 255)
        if self.node.add(rec):
            self._keep([rec])
            self.v += 1
            self._rewind(R.eff_day(rec))
        return rec
    def _gift_seen(self, r):
        if R.kind(r) == R.GIFT and r[6] == self.me and R.ship(r) != self.me:
            self.gifts_in.append((R.ship(r), r[5], R.day(r)))
            if len(self.gifts_in) > 8:
                self.gifts_in.pop(0)
            if self.ready:          # one that arrives now, not the old ones in the log at boot
                self._led("gift")
                self.say("gift: from ship %d, item %d, day %d" % (R.ship(r) + 1, r[5], R.day(r)))

    def gift(self, to_ship, item=0):
        """Author a gift from this ship's crew member to ship to_ship (1-8): the same
        record the phone's gift button makes. Returns the record."""
        to = int(to_ship) - 1
        if not (0 <= to < N) or to == self.me:
            raise ValueError("pick another ship, 1-8")
        n = len(self.log)
        rec = self.tap(self.me, R.GIFT, item, to, R.GIFT_GIVE)
        if len(self.log) != n:
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
                     "time_known": self.clock.known(),
                     "why": getattr(self.led, "state", "off")},
             "heap_used": u, "heap_free": free(), "heap_peak": self.mem_peak, "http": self.http_hits,
             "v": self.v, "day_src": self.cal.src if self.cal else "manual"}
        s["ble"] = self.ble.status(now) if self.ble else None
        return s

    def stat_line(self):
        s = self.status()
        b = s["ble"] or {"state": "off", "peers": [], "n": {}}
        n = b["n"]
        peers = " ".join(["%d%s" % (p["ship"], "=" if p["same"] else "*") for p in b["peers"]]) or "-"
        return ("STAT ship=%d recs=%d digest=%s ble=%s peers=%s ok=%s fail=%s sent=%s got=%s new=%s "
                "gifts_in=%d led=%s/%d heap_used=%d heap_free=%d day=%d/%s" % (
                    s["ship"], s["records"], s["digest"], b["state"], peers, n.get("ok"), n.get("fail"),
                    n.get("sent"), n.get("got"), n.get("new"), s["gifts_in"],
                    s["led"]["why"], self.led.writes, s["heap_used"], s["heap_free"], self.day, s["day_src"]))

    async def loop(self, stop_after_ms=None, stat_every_ms=None, until=None):
        t0 = ticks_ms()
        every = stat_every_ms or self.cfg["stat_every_s"] * 1000
        nxt = every
        nday = 0
        while True:
            now = ticks_diff(ticks_ms(), t0)
            if self.ble:
                self.ble.poll(now)
            if now >= nday:
                nday = now + 10000
                self.day_check()
            wait = self.led.poll((self.ble is not None and self.ble.busy()) or
                                 (self.web is not None and self.web.busy > 0))
            if now >= nxt:
                nxt = now + every
                self.say(self.stat_line())
            if stop_after_ms is not None and now >= stop_after_ms:
                return
            if until is not None and until():
                return
            await sleep_ms(min(50, wait))
