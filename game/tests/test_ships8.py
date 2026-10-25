#!/usr/bin/env python3
"""Every ship id boots with a launch date (regression for the 2026-10-25 bench, where ship
2 never got past lvship.Ship(...)). For ship_id 1..8, launch_date today (2026-10-25,
flight day 1 from 06:00 US Central), the clock unknown / brought by a phone / saved in
clock.json, the LED notifier off / on / forced, and ship.json in the current format and in
the older updater format (schema, ship_name, role, hotspot_open, updated_at): Ship(...)
must return promptly (radio on, the fake BLE stack), land on the right flight day, run its
loop and the LED path for a moment, and the old keys must not change what it does.
Runs on CPython and on the MicroPython unix ports (64- and 32-bit):
  python3 tests/test_ships8.py            (from game/)
  micropython -X heapsize=512k tests/test_ships8.py"""
import gc
import json
import os
import sys
import time

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except AttributeError:          # MicroPython: no os.path
    HERE = "tests"
ROOT = HERE.rsplit("/", 1)[0] if "/" in HERE else "."
sys.path[:0] = [ROOT, ROOT + "/board", HERE + "/fakeble", HERE + "/fakeboard"]
try:
    os.chdir(ROOT)
except OSError:
    pass

import fakeboard                 # noqa: E402  (machine.Pin("LED") for the notifier)
fakeboard.install()

import bluetooth                 # noqa: E402  (tests/fakeble)
import lvship                    # noqa: E402
import lvdays                    # noqa: E402

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

TODAY = "2026-10-25"
PHONE_MS = 1792936800000         # 2026-10-25 09:00 CDT (14:00 UTC): flight day 1
TZ = -300
SLOW_MS = 3000                   # Ship(...) takes ~0.2 s on a Pico W; far less here

n = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    n[0] += 1


def now_ms():
    return int(time.time() * 1000)


def rm_tree(d):
    try:
        names = os.listdir(d)
    except OSError:
        return
    for f in names:
        p = d + "/" + f
        try:
            os.remove(p)
        except OSError:
            rm_tree(p)
    try:
        os.rmdir(d)
    except OSError:
        pass


TMP = "build/ships8"
rm_tree(TMP)
for d in ("build", TMP):
    try:
        os.mkdir(d)
    except OSError:
        pass

OLD_KEYS = {"schema": 2, "ship_name": "Starship-01", "role": "B", "hotspot_open": True,
            "updated_at": "2026-10-23T00:11:15.363Z"}

for sid in range(1, 9):
    for clock in ("unknown", "phone", "saved"):
        for led in (False, True, "force"):
            for old in (False, True):
                data = "%s/s%d" % (TMP, sid)
                rm_tree(data)
                os.mkdir(data)
                cfg = {"launch_date": TODAY, "led_notify": led, "ship_id": sid}
                if old:
                    c = dict(OLD_KEYS)
                    c.update(cfg)
                    cfg = c
                with open(data + "/ship.json", "w") as f:
                    json.dump(cfg, f)
                with open(data + "/crew.json", "w") as f:       # a code for Phill only
                    json.dump({"schema": 1, "salt": "00" * 8, "codes": ["x" * 16] + [None] * 7}, f)
                if clock == "saved":                             # a board that saw a phone before
                    with open(data + "/clock.json", "w") as f:
                        json.dump({"key": TODAY + "@360", "day": 1, "lm": PHONE_MS // 60000 + TZ, "tz": TZ}, f)
                tag = "ship %d clock %s led %s %s" % (sid, clock, led, "old ship.json" if old else "ship.json")
                c = lvship.load_config(data + "/ship.json")
                check(tag + ": ship_id", c["ship_id"] == sid, c)
                check(tag + ": launch date", c["launch_date"] == TODAY, c)
                bluetooth.WORLD = bluetooth.World()      # a fresh air for each boot
                gc.collect()
                t0 = now_ms()
                ship = lvship.Ship(c, root="build/", data=data, say=lambda s: None,
                                   days=lvdays.Days(data + "/days.bin"))
                took = now_ms() - t0
                check(tag + ": Ship() returns promptly", took < SLOW_MS, took)
                check(tag + ": ship id", ship.me == sid - 1)
                check(tag + ": calendar", ship.cal is not None and ship.cal.launch is not None)
                if clock == "phone":
                    check(tag + ": day 0 before the phone", ship.day == 0, ship.day)
                    ship.clock.learn(PHONE_MS, TZ)
                    ship.day_check()
                want = 0 if clock == "unknown" else 1
                check(tag + ": flight day", ship.day == want and ship.st.day == want, (ship.day, ship.st.day))
                if led and ship.led_on(True):
                    ship._led("test")
                asyncio.run(ship.loop(stop_after_ms=120, stat_every_ms=60))
                s = ship.status()
                check(tag + ": status", s["ship"] == sid and s["day"] == want, s)
                check(tag + ": old keys don't change the game", ship.cfg.get("hotspot_open") is (True if old else False))
                ship = None
                gc.collect()
rm_tree(TMP)
print("test_ships8: %d checks ok (ships 1-8 with a launch date, %s)" % (n[0], sys.implementation.name))
