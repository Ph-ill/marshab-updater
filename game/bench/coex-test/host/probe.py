#!/usr/bin/env python3
"""Laptop-side probe. Join the board's AP (COEX-0), then run:  python3 probe.py --minutes 1440
Every 2 s: GET /ping (RTT). Every 60 s: GET /api/stats (board counters). Writes probe_<ts>.csv and stats_<ts>.jsonl."""
import argparse, json, time, urllib.request, csv, datetime

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="192.168.4.1")
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--every", type=float, default=2.0)
a = ap.parse_args()
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
f = open(f"probe_{stamp}.csv", "w", newline="")
w = csv.writer(f)
w.writerow(["t_local", "ok", "rtt_ms", "error"])
js = open(f"stats_{stamp}.jsonl", "w")
end = time.time() + a.minutes * 60
next_stats = 0
while time.time() < end:
    t = time.time()
    try:
        with urllib.request.urlopen(f"http://{a.host}/ping", timeout=5) as r:
            r.read()
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), 1, round((time.time() - t) * 1000, 1), ""])
    except Exception as e:
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), 0, "", type(e).__name__])
    if t >= next_stats:
        next_stats = t + 60
        try:
            with urllib.request.urlopen(f"http://{a.host}/api/stats", timeout=5) as r:
                d = json.loads(r.read())
            d["t_local"] = datetime.datetime.now().isoformat(timespec="seconds")
            js.write(json.dumps(d) + "\n")
            js.flush()
        except Exception:
            pass
    f.flush()
    time.sleep(max(0, a.every - (time.time() - t)))
print("done", f.name, js.name)
