# The flight day from the calendar: one flight day per real day, rolling over at 06:00
# local time, from a fleet-wide launch date (/data/ship.json "launch_date": "YYYY-MM-DD";
# flight day 1 starts at 06:00 that day). Without a launch date the board keeps the bench
# behaviour: the flight day is ship.json "day" and nothing advances it.
#
# Where the time comes from, best first:
#   phone   lv/clock.py: every page request carries the phone's clock and time zone
#   saved   /data/clock.json, written when the day changes, when a phone first brings the
#           time after a boot, and at most hourly while the time is known (flash wear: about
#           one small write an hour). After a reboot with no phone yet, the saved time runs on
#           from where it was (behind by however long the board was off).
#   peer    a ship that doesn't know the time from a phone moves one day ahead when a peer
#           of the same fleet (same fleet key: lv/ble.py ignores every other fleet's
#           adverts) advertises exactly today + 1. Never more than one day at a time, never
#           when a phone has told this ship the time: one phone with a wrong clock can push
#           its own ship anywhere, but each other ship only follows it one day.
# The flight day never moves backwards (a phone with a slow clock, a reboot, a time zone
# change). Changing the launch date or the day start forgets the saved day.
#
# Only the day comes from the clock; the story depends only on the records and the day
# (lv/engine.py), so every ship that reaches a day tells it the same.
#
# Time zones: the board uses the offset the last phone sent (X-Phone-TZ). Across a daylight
# saving change with no phone, the rollover is an hour early or late that one morning; the
# next phone corrects the clock, and the day is never taken back.
START = 360                  # minutes after local midnight a flight day begins (06:00)
SAVE_MS = 3600000            # save the time at most hourly while a phone keeps it known


def days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic Gregorian date."""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def parse_date(s):
    """'YYYY-MM-DD' -> days since 1970, or None."""
    try:
        s = str(s).strip()
        if len(s) != 10 or s[4] != "-" or s[7] != "-":
            return None
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    except (TypeError, ValueError):
        return None
    if not (2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    z = days_from_civil(y, m, d)
    if days_from_civil(y + (m == 12), m % 12 + 1, 1) <= z:    # 31 Feb and so on
        return None
    return z


def parse_hm(v, default=START):
    """'HH:MM' (or minutes) -> minutes after midnight 0..1439."""
    try:
        if isinstance(v, int):
            m = v
        else:
            h, mm = str(v).split(":")
            m = int(h) * 60 + int(mm)
    except (TypeError, ValueError):
        return default
    return m if 0 <= m < 1440 else default


def flight_day(lm, launch, season, start=START):
    """The flight day at local minute lm (minutes since 1970 in local time): 0 before
    launch, 1 from `start` on the launch date, at most `season` (it stays there)."""
    d = (lm - start) // 1440 - launch + 1
    return 0 if d < 1 else season if d > season else d


class Calendar:
    def __init__(self, cfg, clock, season, data="/data", say=print):
        self.clock = clock
        self.season = season
        self.say = say
        self.date = str(cfg.get("launch_date") or "")
        self.launch = parse_date(self.date)
        self.start = parse_hm(cfg.get("day_start", START))
        self.key = "%s@%d" % (self.date, self.start)
        self.path = (data + "/clock.json") if data else None
        self.day = 0
        self.src = "none"            # where today's day came from: phone, saved, peer
        self.saved_lm = None         # saved local minute, at uptime saved_up
        self.saved_up = 0
        self.saved_at = None         # uptime of the last save while the time was known
        if self.path:
            try:
                import json
                with open(self.path) as f:
                    j = json.load(f)
                if j.get("key") == self.key:
                    self.day = min(max(0, int(j["day"])), season)
                    lm = int(j["lm"])
                    if lm >= 0:
                        self.saved_lm, self.saved_up = lm, clock.uptime()
                    self.src = "saved"
            except Exception:        # missing, broken, or another launch: start over
                pass

    def local_minutes(self):
        m = self.clock.local_minutes()
        if m is not None:
            return m
        if self.saved_lm is None:
            return None
        return self.saved_lm + (self.clock.uptime() - self.saved_up) // 60000

    def until(self):
        """Minutes until flight day 1 starts (0 once it has), or None if the time is unknown."""
        lm = self.local_minutes()
        if lm is None or self.launch is None:
            return None
        return max(0, self.launch * 1440 + self.start - lm)

    def poll(self, peers=()):
        """Today's flight day, never less than before. `peers`: the flight days our own
        fleet's ships advertise (only used while no phone has told us the time)."""
        if self.launch is None:
            return self.day
        d, src = self.day, self.src
        lm = self.local_minutes()
        known = self.clock.known()
        if lm is not None:
            c = flight_day(lm, self.launch, self.season, self.start)
            if c > d:
                d, src = c, ("phone" if known else "saved")
        if not known:
            for p in peers:
                if p == d + 1 and p <= self.season:
                    d, src = p, "peer"
                    break
        up = self.clock.uptime()
        if d != self.day:
            self.day, self.src = d, src
            self.save(up)
        elif known and (self.saved_at is None or up - self.saved_at >= SAVE_MS):
            self.save(up)
        return self.day

    def advance(self, ship):
        """Move `ship` (lvship.Ship) to today's flight day if it has come: play the new days
        out, put the day in the BLE advert, bump v so polling phones fetch it. Lives here,
        not in lvship, so a board without a launch date doesn't hold the code."""
        peers = ()
        if ship.ble is not None and not self.clock.known():
            from lv.sync import PROTO
            peers = [p.info["day"] for p in ship.ble.peers.values()
                     if p.info and p.info["proto"] == PROTO]
        d = self.poll(peers)
        if d <= ship.day:
            return False
        ship.day = d
        ship.node.day = d
        if ship.st is not None:
            ship.tick_to(d)
        ship.v += 1
        ship.say("day: flight day %d (%s)" % (d, self.src))
        return True

    def save(self, up):
        lm = self.local_minutes()
        if self.clock.known():
            self.saved_at = up
        if lm is not None:
            self.saved_lm, self.saved_up = lm, up
        if not self.path:
            return
        try:
            import json
            with open(self.path, "w") as f:
                f.write(json.dumps({"key": self.key, "day": self.day, "lm": lm if lm is not None else -1,
                                    "tz": self.clock.tz}))
        except OSError as e:
            self.say("calendar: save failed %s" % e)
