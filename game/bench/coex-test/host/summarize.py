#!/usr/bin/env python3
"""Pass/fail summary.  python3 summarize.py probe_X.csv stats_X.jsonl [coex_log_B.csv]
The optional third file is board B's /coex_log.csv (copy it off with: mpremote cp :/coex_log.csv coex_log_B.csv)."""
import csv, json, sys, statistics

def pct(a, p):
    a = sorted(a)
    return round(a[min(len(a) - 1, int(len(a) * p))]) if a else None

probe = list(csv.DictReader(open(sys.argv[1])))
stats = [json.loads(l) for l in open(sys.argv[2]) if l.strip()]
rtt = [float(r["rtt_ms"]) for r in probe if r["ok"] == "1"]
ok_rate = len(rtt) / max(1, len(probe))
fails, run, worst = 0, 0, 0
for r in probe:
    run = run + 1 if r["ok"] == "0" else 0
    worst = max(worst, run)
first, last = stats[0], stats[-1]
hours = (last["uptime_s"] - first["uptime_s"]) / 3600 if last["boot"] == first["boot"] else None
mem = [s["mem_free"] for s in stats if s.get("mem_free")]
half = len(mem) // 2
mem_trend = (statistics.mean(mem[half:]) - statistics.mean(mem[:half])) if half >= 3 else 0
exp_rot = None
checks = []
def chk(name, cond, val):
    checks.append((name, "PASS" if cond else "FAIL", val))

chk("no unplanned reboot (boot counter unchanged)", last["boot"] == first["boot"], f'{first["boot"]} -> {last["boot"]}')
chk("HTTP /ping success >= 99.5 %", ok_rate >= 0.995, f"{ok_rate*100:.2f} % of {len(probe)}")
chk("HTTP p95 RTT <= 300 ms", (pct(rtt, .95) or 1e9) <= 300, f"p50 {pct(rtt,.5)} p95 {pct(rtt,.95)} p99 {pct(rtt,.99)} max {round(max(rtt)) if rtt else None}")
chk("longest outage <= 5 probes (10 s)", worst <= 5, f"{worst} consecutive failures")
chk("server-side request errors < 0.5 %", last["http_err"] <= 0.005 * max(1, last["http_req"]), f'{last["http_err"]} / {last["http_req"]}')
checks.append(("Wi-Fi leaves (phase 2/4: any leave of the laptop = a drop)", "INFO", f'joins {last["sta_joins"]} leaves {last["sta_leaves"]} now {last["stations"]}; check /log'))
chk("peer heard: max gap <= 60 s", last["peer_gap_max"] <= 60, f'{last["peer_gap_max"]} s')
if last["peer_seen"]:
    heard = last["peer_seen"] / max(1, last["peer_seen"] + last["peer_seq_missed"])
    chk("peer advert rotations heard >= 50 %", heard >= 0.5, f"{heard*100:.1f} % ({last['peer_seen']} heard, {last['peer_seq_missed']} missed)")
chk("no BLE stalls", last["stall_peer"] == 0 and last["stall_silent"] == 0, f'peer {last["stall_peer"]} silent {last["stall_silent"]}')
chk("no scan/advert API errors", last["scan_err"] == 0 and last["adv_err"] == 0, f'scan {last["scan_err"]} adv {last["adv_err"]}')
chk("free heap not trending down by > 4 KB", mem_trend > -4096, f"min {last['mem_min']} trend {mem_trend:+.0f} B")
if len(sys.argv) > 3:
    b = list(csv.DictReader(open(sys.argv[3])))
    bl = b[-1]
    t, o = int(bl["gatt_try"]), int(bl["gatt_ok"])
    chk("board B: no reboot", b[0]["boot"] == bl["boot"], f'{b[0]["boot"]} -> {bl["boot"]}')
    chk("board B: GATT transfers >= 95 % ok", t == 0 or o / t >= 0.95, f"{o}/{t}, worst {bl['gatt_ms_max']} ms")
    chk("board B: no BLE stalls", bl["stall_peer"] == "0" and bl["stall_silent"] == "0", f'peer {bl["stall_peer"]} silent {bl["stall_silent"]}')
print(f"duration on one boot: {hours:.1f} h" if hours else "board rebooted during run")
for n, r, v in checks:
    print(f"{r:4}  {n:62}  {v}")
print("OVERALL", "PASS" if all(r != "FAIL" for _, r, _ in checks) else "FAIL")
