#!/usr/bin/env python3
"""Compile the engagement content (content/engage/*.json) for the ships and the phones.

  python3 tools/lve.py            -> build/engage.bin (Pico: numbers only) and
                                     build/engage.json(.gz) (phone: the words)

Separate from tools/lvc.py on purpose: the story pack and the engagement layer are
edited by different people and change at different times. lv/engage.py reads
engage.bin; web/engage.js reads engage.json. Nothing here changes the story pack.

engage.bin layout (all bytes):
  (engage.json also carries {resolver card: cliffhanger card}, read from build/pack.bin)

  "LVE1", ntiers, pct[ntiers], count[ntiers], pity_days,
  job_pct, njobs, per job: (h0, h1, nout, weight[nout]),
  ngifts, flags[ngifts] (bit0 = can give, bit1 = can ask), ask_days
"""
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PRONOUN = re.compile(r"\b(he|she|him|her|his|hers|himself|herself)\b", re.I)


class Err(Exception):
    pass


def load(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def texts(obj, where=""):
    # Every player-facing string, for the pronoun check.
    if isinstance(obj, str):
        yield where, obj
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from texts(v, "%s[%d]" % (where, i))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not k.startswith("_") and k not in ("id", "tier", "art", "rule"):
                yield from texts(v, "%s.%s" % (where, k))


def build(content):
    d = os.path.join(content, "engage")
    drops, jobs, gifts, coll = (load(d, n) for n in ("drops.json", "jobs.json", "gifts.json", "collections.json"))
    errs, warns = [], []
    arts = [a["id"] for a in coll["artifacts"]]
    # -- drops
    tiers = drops["tiers"]
    if sum(t["pct"] for t in tiers) != 100:
        errs.append("drops.json: tier pct must add up to 100")
    tid = [t["id"] for t in tiers]
    by_tier = [[] for _ in tiers]
    for i, it in enumerate(drops["items"]):
        if it["tier"] not in tid:
            errs.append("drops.json item %d: unknown tier %r" % (i, it["tier"]))
            continue
        if it.get("art") and it["art"] not in arts:
            errs.append("drops.json item %d: unknown artifact %r" % (i, it["art"]))
        by_tier[tid.index(it["tier"])].append({"k": it["kind"], "t": it["t"], **({"art": it["art"]} if it.get("art") else {})})
    for t, items in zip(tiers, by_tier):
        if not items:
            errs.append("drops.json: tier %r has no items" % t["id"])
        elif len(items) > 255:
            errs.append("drops.json: tier %r has more than 255 items" % t["id"])
    # -- jobs
    if not 0 <= jobs["pct"] <= 100:
        errs.append("jobs.json: pct must be 0-100")
    jb = []
    for j in jobs["jobs"]:
        h0, h1 = j["h"]
        if not (6 <= h0 < h1 <= 21):
            errs.append("jobs.json %s: finish window must sit inside 06-21 (quiet hours are 22-07)" % j["id"])
        if not 1 <= len(j["out"]) <= 8:
            errs.append("jobs.json %s: 1-8 outcomes" % j["id"])
        for o in j["out"]:
            if not 1 <= o["w"] <= 255:
                errs.append("jobs.json %s: weight 1-255" % j["id"])
            if o.get("art") and o["art"] not in arts:
                errs.append("jobs.json %s: unknown artifact %r" % (j["id"], o["art"]))
        jb.append(j)
    # -- gifts
    items = gifts["items"]
    if not 1 <= len(items) <= 64:
        errs.append("gifts.json: 1-64 items (the record carries the index in 6 bits)")
    if not any(i["ask"] for i in items):
        warns.append("gifts.json: nothing can be asked for")
    # -- collections
    for p in coll["patches"]:
        if p["rule"][0] not in ("day", "votes", "rescues", "gifts", "hooks", "opened", "artifacts", "story", "streak"):
            errs.append("collections.json %s: unknown rule %r" % (p["id"], p["rule"][0]))
    for a in arts:
        if not any(it.get("art") == a for it in drops["items"]) and not any(o.get("art") == a for j in jb for o in j["out"]):
            warns.append("collections.json: artifact %r can never be found" % a)
    for src, obj in (("drops", drops), ("jobs", jobs), ("gifts", gifts), ("collections", coll)):
        for w, s in texts(obj, src):
            m = PRONOUN.search(s)
            if m:
                errs.append("%s: gendered pronoun %r (crew can be anyone)" % (w, m.group(0)))
    if errs:
        raise Err("\n".join(errs))
    b = bytearray(b"LVE1")
    b.append(len(tiers))
    b += bytes(t["pct"] for t in tiers)
    b += bytes(len(x) for x in by_tier)
    b.append(drops.get("pity_days", 0))
    b.append(jobs["pct"])
    b.append(len(jb))
    for j in jb:
        b += bytes((j["h"][0], j["h"][1], len(j["out"])))
        b += bytes(o["w"] for o in j["out"])
    b.append(len(items))
    b += bytes((1 if i["give"] else 0) | (2 if i["ask"] else 0) for i in items)
    b.append(gifts.get("ask_days", 3))
    phone = {
        "tiers": [t["label"] for t in tiers],
        "drops": by_tier,
        "jobs": [{"l": j["label"], "t": j["t"], "out": [{"t": o["t"], **({"art": o["art"]} if o.get("art") else {})} for o in j["out"]]} for j in jb],
        "gifts": {"items": [[i["n"], i["give"], i["ask"]] for i in items], "sys": gifts["sys"], "ask_days": gifts.get("ask_days", 3)},
        "patches": [{"id": p["id"], "n": p["n"], "t": p["t"], "r": p["rule"]} for p in coll["patches"]],
        "badges": [[x["n"], x["id"]] for x in coll["badges"]],
        "arts": [{"id": a["id"], "n": a["n"], "t": a["t"]} for a in coll["artifacts"]],
        "file": {k: v for k, v in coll["file"].items() if not k.startswith("_")},
    }
    return bytes(b), phone, warns


def resolvers(pack_path):
    """{resolver card: hook card} from build/pack.bin: due cards (F_DUE) whose conditions
    include 'fired <a cliffhanger card>'. The phone uses it to pair this morning's
    resolution with last night's cliffhanger. Read from the compiled pack, so lvc.py and
    the .lv format don't change."""
    sys.path.insert(0, ROOT)
    from lv import ops as O
    from lv.pack import load
    try:
        p = load(pack_path)
    except OSError:
        return {}
    hooks = {c.idx for c in p.cards if c.flags & O.F_HOOK}
    out = {}
    for c in p.cards:
        if not c.flags & O.F_DUE:
            continue
        q = c.conds
        for i in range(p.data[q]):
            op, a = p.data[q + 1 + 4 * i], p.data[q + 2 + 4 * i]
            if op == O.C_FIRED and a in hooks:
                out[c.idx] = a
    return out


def main(argv):
    content = os.path.join(ROOT, "content")
    out = os.path.join(ROOT, "build")
    if "--content" in argv:
        content = argv[argv.index("--content") + 1]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    try:
        binr, phone, warns = build(content)
    except Err as e:
        for line in str(e).splitlines():
            print("error:", line)
        return 1
    phone["res"] = {str(k): v for k, v in sorted(resolvers(os.path.join(out, "pack.bin")).items())}
    for w in warns:
        print("warning:", w)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "engage.bin"), "wb").write(binr)
    js = json.dumps(phone, ensure_ascii=False, separators=(",", ":")).encode()
    open(os.path.join(out, "engage.json"), "wb").write(js)
    gz = gzip.compress(js, 9, mtime=0)
    open(os.path.join(out, "engage.json.gz"), "wb").write(gz)
    print("ok: engage.bin %d B, engage.json %d B, gzip %d B" % (len(binr), len(js), len(gz)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
