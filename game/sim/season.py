#!/usr/bin/env python3
"""Fast-forward a 42-day season with 7 simulated players.

  python3 sim/season.py                 # one season: narrative + stats + determinism check
  python3 sim/season.py --seasons 300   # many seasons with different voyage keys: stats only

Writes sim/out/narrative.txt, sim/out/stats.json, build/season_story.bin, build/season_log.bin +
build/season_expect.txt for the MicroPython check (tests/mp_check.py).

  --spoilers   print the full summaries and write ending and card ids into
               sim/out/stats.json and sim/out/multi_season.json. Without it (the committed
               copies) endings are named by deck position ("ending 3") and cards by
               number ("card 117"), so the files can be browsed without spoiling the story.
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from lv import ops as O                     # noqa: E402
from lv import record as R                  # noqa: E402
from lv.chlog import ChoiceLog              # noqa: E402
from lv.engine import Engine, A_GIFT, A_ADVICE, A_TASK, A_REST  # noqa: E402
from lv.pack import load as load_pack       # noqa: E402
from lv.state import State, N               # noqa: E402
from sim.render import Renderer             # noqa: E402

FLEET_KEY = b"test-fleet-key-not-secret"

# Activity: chance of opening the page on a given day.
PROFILES = [
    {"name": "keen", "p": 0.90},
    {"name": "regular", "p": 0.60},
    {"name": "sporadic", "p": 0.35},
    {"name": "regular, out of range days 15-21", "p": 0.75, "offline": (15, 21)},
    {"name": "casual", "p": 0.50},
    {"name": "never plays", "p": 0.0},
    {"name": "never plays", "p": 0.0},
]


def offline(ship, day):
    w = PROFILES[ship].get("offline")
    return bool(w) and w[0] <= day <= w[1]


class Players:
    """Simulated people. Uses CPython's random, which is fine: players are outside
    the deterministic core. Their output is a fixed list of records."""

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.seq = [0] * N

    def act(self, day, st, pack):
        recs = []
        for s in range(N):
            if st.cond[s] == O.COND_HOME or self.r.random() >= PROFILES[s]["p"]:
                continue
            # Out of range for more than a day: the record says "3 days late".
            delay = 3 if offline(s, day) and offline(s, day - 1) else 1

            def rec(kind, a, b=0, c=0):
                self.seq[s] += 1
                recs.append(R.encode(FLEET_KEY, kind, s, delay, self.seq[s], day, a, b, c))

            # Daily instruction
            if st.morale[s] < 40 and self.r.random() < 0.5:
                rec(R.ACTION, A_REST)
            else:
                pick = self.r.random()
                mates = [j for j in range(N) if j != s and st.cond[j] != O.COND_HOME]
                if pick < 0.4 and mates:
                    rec(R.ACTION, A_GIFT, 0, self.r.choice(mates))
                elif pick < 0.6:
                    rec(R.ACTION, A_ADVICE, self.r.randrange(3), self.r.randrange(2))
                else:
                    rec(R.ACTION, A_TASK, self.r.randrange(3))
            # Votes, dilemmas, rescues
            for it in st.pend:
                ctype, idx = it[0], it[1]
                nopt = pack.cards[idx].nopt
                if ctype == O.DECISION and self.r.random() < 0.8:
                    rec(R.VOTE, idx, self.r.randrange(nopt))
                elif ctype == O.RESCUE and self.r.random() < 0.7:
                    rec(R.VOTE, idx, 0)
                elif ctype == O.DILEMMA and it[4] == s and self.r.random() < 0.9:
                    rec(R.DILEMMA, idx, self.r.randrange(nopt))
            if self.r.random() < 0.15:
                rec(R.NOTE, self.r.randrange(3), self.r.choice([j for j in range(N) if j != s]))
        return recs


def reference_season(pack, seed=1, voyage_key=None):
    """One omniscient run: every record is known the moment it's authored.
    Returns (final state, all records in authored order, per-day digests)."""
    if voyage_key is not None:
        pack.voyage_key = voyage_key
    log = ChoiceLog(FLEET_KEY)
    st = State(pack)
    eng = Engine(pack, st, log)
    players = Players(seed)
    authored = []      # (day, rec)
    digests = []
    story = bytearray()
    # Day 0: players can act before the first tick (setup visit).
    for d in range(0, pack.season + 1):
        if d > 0:
            eng.tick()
            story += st.out
            digests.append(st.hexdigest())
        if d < pack.season:
            for r in players.act(d, st, pack):
                log.merge(r)
                authored.append((d, r))
    st.story = story  # the whole season's entries, for the narrative and stats
    return st, authored, digests, log


class Ship:
    """One ship that only knows what has reached it so far, replaying from its
    weekly snapshot when a late record lands in its past."""

    SNAP_EVERY = 7

    def __init__(self, idx, pack):
        self.idx = idx
        self.p = pack
        self.log = ChoiceLog(FLEET_KEY)
        self.st = State(pack)
        self.snaps = {0: self.st.dump()}
        self.replays = 0
        self.replayed_days = 0
        self.max_depth = 0

    def tick_to(self, day):
        while self.st.day < day:
            Engine(self.p, self.st, self.log).tick()
            if self.st.day % self.SNAP_EVERY == 0:
                self.snaps[self.st.day] = self.st.dump()

    def receive(self, recs):
        earliest = None
        for r in recs:
            res = self.log.merge(r)
            if res > 0:
                e = R.eff_day(r)
                if e <= self.st.day and (earliest is None or e < earliest):
                    earliest = e
        if earliest is not None:
            now = self.st.day
            base = max(k for k in self.snaps if k < earliest)
            for k in [k for k in self.snaps if k > base]:
                del self.snaps[k]
            self.st = State.load(self.snaps[base])
            self.replays += 1
            self.replayed_days += now - base
            self.max_depth = max(self.max_depth, now - earliest + 1)
            self.tick_to(now)


def deliver(pack, authored, scenario, seed=7, upto=None, cls=None):
    """Replay a fixed set of authored records to 7 ships under a delivery scenario.
    Returns the ships. With upto, stop after that day's deliveries (the mock Pico
    server uses this to show what one ship knows on a given day)."""
    rnd = random.Random(seed)
    ships = [(cls or Ship)(i, pack) for i in range(N)]
    inbox = {}  # day -> list of (ship, rec)
    for d, r in authored:
        author = R.ship(r)
        for t in range(N):
            if t == author:
                lag = 0
            elif scenario == "instant":
                lag = 0
            elif scenario == "gossip":
                lag = rnd.randrange(3)
            elif scenario == "reverse":
                lag = rnd.randrange(4)
            elif scenario == "bursty":
                lag = (5 - d % 5) if t == 2 or author == 2 else rnd.randrange(2)
            else:
                raise ValueError(scenario)
            a = d + lag
            if t != author:
                while offline(author, a) or offline(t, a):
                    a += 1
            inbox.setdefault(a, []).append((t, r))
            if scenario == "reverse" and rnd.random() < 0.2:
                inbox.setdefault(a + 1, []).append((t, r))  # duplicate delivery
    last = pack.season if upto is None else upto
    for d in range(0, last + 1):
        for s in ships:
            s.now = d
            s.tick_to(d)
        todays = inbox.pop(d, [])
        if scenario == "reverse":
            todays.reverse()
        elif scenario != "instant":
            rnd.shuffle(todays)
        per = [[] for _ in range(N)]
        for t, r in todays:
            per[t].append(r)
        for t in range(N):
            if per[t]:
                ships[t].receive(per[t])
    if upto is not None:
        return ships
    # After the season every ship eventually hears everything.
    rest = [(t, r) for d in sorted(inbox) for t, r in inbox[d]]
    for t in range(N):
        ships[t].receive([r for tt, r in rest if tt == t])
        ships[t].tick_to(pack.season)
    return ships


def stats_for(pack, st, text):
    fired = {}
    out = st.story
    counts = {}
    dec = {"closed": 0, "no_ballots": 0, "tie": 0}
    dil = {"owner": 0, "astronaut": 0}
    res = {"answered": 0, "default": 0}
    appear = [0] * N
    for i in range(0, len(out), 8):
        e = out[i:i + 8]
        code = e[1]
        counts[code] = counts.get(code, 0) + 1
        if code in (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN, O.O_END):
            cid = text["cards"][e[2]]["id"]
            fired[cid] = fired.get(cid, 0) + 1
        if code in (O.O_EVENT, O.O_DEC_OPEN, O.O_DIL_OPEN, O.O_RES_OPEN):
            for x in (e[3], e[4]):
                if x < N:
                    appear[x] += 1
        if code == O.O_DEC_CLOSE:
            dec["closed"] += 1
            dec["no_ballots"] += e[5] == 1
            dec["tie"] += e[5] == 2
        if code == O.O_DIL_CLOSE:
            dil["astronaut" if e[5] else "owner"] += 1
        if code == O.O_RES_CLOSE:
            res["default" if e[5] else "answered"] += 1
    flags = []
    return {
        "ending": text["cards"][st.ending]["id"] if st.ending != 255 else None,
        "cards_fired": fired,
        "decisions": dec, "dilemmas": dil, "rescues": res,
        "story_appearances": dict(zip(text["crew"], appear)),
        "entries": len(out) // 8,
        "out_bytes": len(out),
        "state_bytes": len(st.dump()),
        "resources_end": dict(zip(O.RESOURCES, list(st.res))),
        "crew_condition_end": dict(zip(text["crew"], [O.CONDITIONS[c] for c in st.cond])),
    }


def ending_label(text, cid):
    """Spoiler-free name for an ending: its deck position ("ending 3"), never its id."""
    if cid is None:
        return None
    ends = [c["id"] for c in text["cards"] if c["id"].startswith("end_")]
    return "ending %d" % (ends.index(cid) + 1) if cid in ends else "ending ?"


def card_label(text, cid):
    """Spoiler-free name for a card: its deck position ("card 117"), never its id."""
    return "card %d" % [c["id"] for c in text["cards"]].index(cid)


def redact_stats(stats, text):
    """stats.json without --spoilers: no ending id and no card ids (sim/out is committed,
    and card ids name the mystery). Counts survive; names become deck positions."""
    stats = dict(stats)
    stats["ending"] = ending_label(text, stats["ending"])
    stats["cards_fired"] = {card_label(text, k): v for k, v in stats["cards_fired"].items()}
    return stats


def redact_report(report, text):
    """multi_season.json without --spoilers: endings by deck position, cards by number."""
    report = dict(report)
    report["endings"] = {ending_label(text, k): v for k, v in report["endings"].items()}
    report["seasons_where_card_fired"] = {card_label(text, k): v
                                          for k, v in report["seasons_where_card_fired"].items()}
    report["cards_never_fired"] = [card_label(text, k) for k in report["cards_never_fired"]]
    report["unfair_seasons"] = [{"season": u["season"], "missing_groups": len(u["missing"])}
                                for u in report["unfair_seasons"]]
    return report


def fair_play(st, text):
    """Core clue groups (lvc `clue core [group]`) with no card fired before the first
    reveal card (lvc `reveal`). Empty means the season played fair."""
    rv = [st.fired[i] for i in text.get("reveal", []) if st.fired[i]]
    if not rv:
        return ["(no reveal)"] if text.get("reveal") else []
    day = min(rv)
    return ["/".join(text["cards"][i]["id"] for i in g) for g in text.get("core", [])
            if not any(0 < st.fired[i] < day for i in g)]


def main(argv):
    pack_path = os.path.join(ROOT, "build", "pack.bin")
    text = json.load(open(os.path.join(ROOT, "build", "text.json"), encoding="utf-8"))
    outdir = os.path.join(HERE, "out")
    os.makedirs(outdir, exist_ok=True)
    seasons = int(argv[argv.index("--seasons") + 1]) if "--seasons" in argv else 0
    spoilers = "--spoilers" in argv  # otherwise summaries never print ending or card ids

    if seasons:
        endings, fired_any, t0 = {}, {}, time.time()
        dil = {"owner": 0, "astronaut": 0}
        dec = {"closed": 0, "no_ballots": 0}
        unfair = []
        for i in range(seasons):
            pack = load_pack(pack_path)
            key = bytes([(i >> 8) & 255, i & 255]) + b"season"
            st, _, _, _ = reference_season(pack, seed=1000 + i, voyage_key=key)
            s = stats_for(pack, st, text)
            endings[s["ending"]] = endings.get(s["ending"], 0) + 1
            for k in s["cards_fired"]:
                fired_any[k] = fired_any.get(k, 0) + 1
            for k in dil:
                dil[k] += s["dilemmas"][k]
            dec["closed"] += s["decisions"]["closed"]
            dec["no_ballots"] += s["decisions"]["no_ballots"]
            missing = fair_play(st, text)
            if missing:
                unfair.append({"season": i, "missing": missing})
        dt = time.time() - t0
        never = [c["id"] for c in text["cards"] if c["id"] not in fired_any]
        report = {"seasons": seasons, "seconds": round(dt, 2), "endings": endings,
                  "core_clues_before_reveal": seasons - len(unfair), "unfair_seasons": unfair,
                  "seasons_where_card_fired": dict(sorted(fired_any.items())),
                  "cards_never_fired": never, "dilemmas": dil, "decisions": dec}
        # Ending and card ids are spoilers; they reach the file only with --spoilers.
        json.dump(report if spoilers else redact_report(report, text),
                  open(os.path.join(outdir, "multi_season.json"), "w"), indent=1)
        if spoilers:
            print(json.dumps(report, indent=1))
        else:
            # Spoiler-free: endings by deck position, no card ids (use --spoilers).
            ends = [c["id"] for c in text["cards"] if c["id"] in endings or c["id"].startswith("end_")]
            print("seasons: %d in %.1f s" % (seasons, dt))
            print("core clues before the reveal: %d/%d seasons" % (seasons - len(unfair), seasons))
            print("endings: " + ", ".join("ending %d %.1f%%" % (k + 1, 100.0 * endings.get(e, 0) / seasons)
                                        for k, e in enumerate(ends)))
            print("cards never fired: %d" % len(never))
        if unfair:
            print("FAIR PLAY FAILED in %d season(s): see sim/out/multi_season.json" % len(unfair))
            return 1
        return 0

    pack = load_pack(pack_path)
    t0 = time.time()
    st, authored, digests, log = reference_season(pack, seed=1)
    t_ref = time.time() - t0

    # Narrative
    rd = Renderer(text)
    lines = []
    lastday = -1
    for day, s in rd.lines(st.story):
        if day != lastday:
            lines.append("")
            lines.append("FLIGHT DAY %02d" % day)
            lastday = day
        lines.append("  " + s)
    open(os.path.join(outdir, "narrative.txt"), "w", encoding="utf-8").write("\n".join(lines).strip() + "\n")
    rlines, lastday = [], -1
    for day, s in Renderer(text).reader(st.story):
        if day != lastday:
            rlines += ["", "FLIGHT DAY %02d" % day]
            lastday = day
        rlines.append("  " + s)
    open(os.path.join(outdir, "reader.txt"), "w", encoding="utf-8").write("\n".join(rlines).strip() + "\n")
    epi = rd.epilogue(st.story, st)
    open(os.path.join(outdir, "epilogue.txt"), "w", encoding="utf-8").write(
        "".join("%s: %s\n" % (text["crew"][c], epi[c]) for c in sorted(epi))
        + ("%s: %s\n" % rd.coda(st.story) if rd.coda(st.story) else ""))

    # The raw story bytes, so tests/render_check.mjs can prove web/render.js says the same.
    with open(os.path.join(ROOT, "build", "season_story.bin"), "wb") as f:
        f.write(st.story)

    # MicroPython check inputs
    with open(os.path.join(ROOT, "build", "season_log.bin"), "wb") as f:
        for _, r in authored:
            f.write(r)
    with open(os.path.join(ROOT, "build", "season_expect.txt"), "w") as f:
        f.write("\n".join(digests) + "\n")

    # Determinism across delivery scenarios
    det = {}
    ref = st.digest()
    t1 = time.time()
    for scen in ("instant", "gossip", "reverse", "bursty"):
        ships = deliver(pack, authored, scen)
        ok = all(s.st.digest() == ref for s in ships)
        det[scen] = {"all_7_match": ok,
                     "replays": sum(s.replays for s in ships),
                     "replayed_days": sum(s.replayed_days for s in ships),
                     "deepest_rewrite_days": max(s.max_depth for s in ships)}
    t_det = time.time() - t1

    stats = stats_for(pack, st, text)
    per_player = {}
    for d, r in authored:
        nm = text["crew"][R.ship(r)]
        per_player[nm] = per_player.get(nm, 0) + 1
    stats.update({
        "reference_digest": st.hexdigest(),
        "records": len(authored),
        "records_per_player": per_player,
        "log_bytes": 13 * len(authored),
        "late_records": sum(1 for _, r in authored if R.delay(r) == 3),
        "determinism": det,
        "seconds_reference_season": round(t_ref, 3),
        "seconds_determinism_runs": round(t_det, 2),
        "pack_bytes": pack.size,
    })
    json.dump(stats if spoilers else redact_stats(stats, text),
              open(os.path.join(outdir, "stats.json"), "w"), indent=1)
    if spoilers:
        print(json.dumps(stats, indent=1))
    else:
        print("reference season: digest %s, %d entries, %d records; details in sim/out/stats.json"
              % (stats["reference_digest"], stats["entries"], stats["records"]))
    bad = [k for k, v in det.items() if not v["all_7_match"]]
    if bad:
        print("DETERMINISM FAILED:", bad)
        return 1
    print("determinism: all 7 ships match the reference in every scenario")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
