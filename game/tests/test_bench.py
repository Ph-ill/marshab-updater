# tools/bench.py without hardware: the report parser on canned selftest output, the port
# list, code and flag handling, the expected flight day, --dry-run, and (with a MicroPython
# unix port) whole runs against a fake board directory: the game firmware's unix build
# (LV_FROZEN_MP) must give OVERALL PASS with the LED test, keep ship.json fields it wasn't
# given and write crew codes the game accepts; stock MicroPython must FAIL naming the .uf2.
#   MICROPYTHON=... LV_FROZEN_MP=... python3 tests/test_bench.py
import datetime as DT
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

GAME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(GAME, "tools"))
sys.path.insert(0, GAME)
import bench  # noqa: E402
from lv import codes as lvcodes  # noqa: E402

n = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    n[0] += 1


# ---- the port list (mpremote connect list)
ports = bench.parse_ports("""/dev/ttyS0 None 0000:0000 None None
/dev/ttyACM0 e66141040396 2e8a:0005 MicroPython Board in FS mode
/dev/ttyUSB0 0001 10c4:ea60 Silicon Labs CP2102
COM5 e6614 2e8a:0005 MicroPython Board in FS mode
""")
check("ports: Picos only", [p for p, _ in ports] == ["/dev/ttyACM0", "COM5"], ports)

# ---- the selftest parser
CANNED = """MPY: soft reboot
SELFTEST lvship 0.1.0-lv-test on rp2, MicroPython 3.4.0
SELFTEST wifi: hotspot LV-2 active True, ip 192.168.4.1
SELFTEST firmware: frozen lv-core 0.1.0 (core f1b383588e79), overrides: []
day: flight day 9 (phone)
SELFTEST day: flight day 9 (phone), launch date 2026-10-15, time known True
SELFTEST ble: active True, advert 0201
SELFTEST led test: watch the board's LED now: 3 slow blinks (1 s on, 1 s off)
SELFTEST led: notifier ON (led_notify True), time known True, waiting False
SELFTEST server: phone game listening on port 80
SELFTEST t=10s STAT ship=2 recs=3 digest=aa ble=idle peers=1 ok=1 fail=0 sent=1 got=2 new=2 gifts_in=0 led=test/6 heap_used=70000 heap_free=100 day=9/phone
SELFTEST t=20s STAT ship=2 recs=3 digest=aa ble=idle peers=1 ok=2 fail=0 sent=1 got=2 new=2 gifts_in=1 led=gift/10 heap_used=71000 heap_free=100 day=9/phone
SELFTEST dns: every name -> 192.168.4.1 on port 53
SELFTEST peers seen: 1 (ship 3)
SELFTEST led: notifier ON, waiting False, pin writes 10, now gift
SELFTEST day: flight day 9 (phone) at the end
SELFTEST heap: used 70500, peak 71234, free now 1, lowest free 1
SELFTEST ble active             PASS
SELFTEST peer heard             PASS
SELFTEST in sync with a peer    CHECK
SELFTEST heap used < 80 KB      PASS
SELFTEST led off unless asked   PASS
SELFTEST wifi hotspot up        PASS
SELFTEST server listening       PASS
SELFTEST dns listening          PASS
SELFTEST led test played        PASS
SELFTEST RESULT CHECK (see docs/BENCH_TEST.md)
"""
st = bench.parse_selftest(CANNED)
check("parse: checks", st["checks"] == {"ble active": True, "peer heard": True, "in sync with a peer": False,
                                        "heap used < 80 KB": True, "led off unless asked": True,
                                        "wifi hotspot up": True, "server listening": True, "dns listening": True,
                                        "led test played": True}, st["checks"])
check("parse: result", st["result"].startswith("CHECK"))
check("parse: heap", st["heap_peak"] == 71234 and st["heap_used"] == 70500)
check("parse: stats", [(s["t"], s["led"], s["day"], s["src"]) for s in st["stats"]] ==
      [(10, "test/6", 9, "phone"), (20, "gift/10", 9, "phone")], st["stats"])
check("parse: day lines", st["days"][0] == (9, "phone"), st["days"])
check("parse: wifi/server/dns", "LV-2" in st["wifi"] and "port 80" in st["server"] and "every name" in st["dns"])
check("parse: led end line", st["led"].startswith("notifier ON, waiting False, pin writes 10"), st["led"])
check("parse: ignores noise", bench.parse_selftest("hello\nSELFTESTX y PASS\n")["checks"] == {})

rep = bench.Report()
bench.selftest_checks(rep, st, want_day=(9, "phone"), expect_peers=True, led_test=True, led_seen=True)
txt = rep.text()
for row in ("selftest ran", "heap used < 80 KB", "BLE up", "Wi-Fi hotspot up", "phone server listening", "captive DNS up",
            "flight day", "LED path", "LED blink test", "peers"):
    check("report row " + row, row in txt, txt)
check("report: CHECK in sync fails with --peers", not rep.ok(), txt)
rep = bench.Report()
st2 = bench.parse_selftest(CANNED.replace("in sync with a peer    CHECK", "in sync with a peer    PASS")
                           .replace("RESULT CHECK", "RESULT PASS"))
bench.selftest_checks(rep, st2, want_day=(9, "phone"), expect_peers=True, led_test=True, led_seen=True)
check("report: all PASS", rep.ok(), rep.text())
rep = bench.Report()
bench.selftest_checks(rep, st2, want_day=(10, "phone"), led_test=True, led_seen=True)
check("report: wrong day fails", not rep.ok() and "expected day=10/phone" in rep.text(), rep.text())
rep = bench.Report()
bench.selftest_checks(rep, bench.parse_selftest(CANNED.replace("peak 71234", "peak 81234")), want_day=(9, "phone"))
check("report: heap over the cap fails", not rep.ok() and "81234" in rep.text(), rep.text())
rep = bench.Report()
bench.selftest_checks(rep, st2, want_day=(9, "phone"), led_test=True, led_seen=False)
check("report: LED not seen fails", not rep.ok() and "did NOT see" in rep.text(), rep.text())
rep = bench.Report()
bench.selftest_checks(rep, bench.parse_selftest(CANNED.replace("server listening       PASS", "server listening       CHECK")))
check("report: server down fails", not rep.ok() and "phone server listening  FAIL" in rep.text(), rep.text())
rep = bench.Report()
bench.selftest_checks(rep, bench.parse_selftest("MPY: soft reboot\nTraceback\n"))
check("report: no RESULT fails", not rep.ok() and "selftest ran" in rep.text())

# ---- flags
A = bench.argparse.Namespace


def args(**kw):
    base = dict(codes=None, code=None, launch=None, day=None, led=None, password=None, day_start=None)
    base.update(kw)
    return A(**base)


check("codes: by name", bench.parse_codes(args(code=["phill=1234", "Kim=0007"])) == {0: "1234", 2: "0007"})
check("codes: roster", bench.parse_codes(args(codes="1111,,2222,,,,,9999")) == {0: "1111", 2: "2222", 7: "9999"})
for bad in (args(code=["Wes=1234"]), args(code=["Phill=12a4"]), args(codes="1,2")):
    try:
        bench.parse_codes(bad)
        check("codes rejects", False, bad)
    except SystemExit:
        n[0] += 1
os.environ.pop("LV_HOTSPOT_PASSWORD", None)
s, d = bench.settings_from(args(launch="2026-10-15", led="on"), 4)
check("settings: given only", s == {"ship_id": 4, "launch_date": "2026-10-15", "led_notify": True} and d == [], (s, d))
s, d = bench.settings_from(args(day=12, led="off"), 1)
check("settings: manual day clears the launch", s.get("day") == 12 and "launch_date" in d and s["led_notify"] is False,
      (s, d))
os.environ["LV_HOTSPOT_PASSWORD"] = "placeholder-pass"
s, d = bench.settings_from(args(), 2)
check("settings: password from the environment", s.get("hotspot_password") == "placeholder-pass")
del os.environ["LV_HOTSPOT_PASSWORD"]

check("log line hides codes", bench.redact_argv(["--ship", "1", "--code", "Phill=1234", "--codes=1,2", "--password", "pw",
                                                 "--password=pw"]) ==
      ["--ship", "1", "--code", "Phill=####", "--codes=#,#", "--password", "...", "--password=..."])

# ---- the expected day (Central time, 06:00 rollover)
tz = -300
now = DT.datetime(2026, 10, 23, 17, 0, tzinfo=DT.timezone(DT.timedelta(minutes=tz)))
check("day: FD 9", bench.expected_day({"launch_date": "2026-10-15"}, now, tz) == (9, "phone"))
early = DT.datetime(2026, 10, 23, 5, 59, tzinfo=DT.timezone(DT.timedelta(minutes=tz)))
check("day: before 06:00", bench.expected_day({"launch_date": "2026-10-15"}, early, tz) == (8, "phone"))
check("day: manual", bench.expected_day({"day": 5}, now, tz) == (5, "manual"))

# ---- --dry-run touches nothing and says what it would do
out = io.StringIO()
old = sys.stdout
sys.stdout = out
try:
    rc = bench.main(["--dry-run", "--ships", "1,2", "--launch", "2026-10-15", "--led", "on", "--code", "Phill=1234"])
finally:
    sys.stdout = old
o = out.getvalue()
check("dry run", rc == 0 and "ship 1:" in o and "ship 2:" in o and "1234" not in o and "set for Phill" in o, o)

# ---- a real deadline on every mpremote call (2026-10-25: a silent board held bench forever,
# because the old loop only looked at the clock when a line arrived)
import time  # noqa: E402
SILENT = [sys.executable, "-c", "import sys,time; print('SELFTEST lvship start', flush=True); time.sleep(60)"]
t0 = time.time()
rc, o = bench.run_with_deadline(subprocess.Popen(SILENT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True), 2)
took = time.time() - t0
check("deadline: a silent child is stopped on time", took < 6, took)
check("deadline: rc 124", rc == 124, rc)
check("deadline: says TIMEOUT and to replug", bench.timed_out(o) and "unplug the board" in o and "SELFTEST lvship start" in o, o)
rc, o = bench.run_with_deadline(subprocess.Popen([sys.executable, "-c", "print('hi')"], stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, text=True), 20)
check("deadline: a quick child is untouched", rc == 0 and o == "hi\n" and not bench.timed_out(o), (rc, o))
rc, o = bench.run_with_deadline(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True), 1)
check("deadline: no output at all", rc == 124 and bench.timed_out(o), (rc, o))
# Mpremote itself, with a stand-in mpremote that hangs without a word
fake_mp = os.path.join(tempfile.mkdtemp(), "mpremote_hang.py")
with open(fake_mp, "w") as f:
    f.write("import time\ntime.sleep(60)\n")
t0 = time.time()
rc, o = bench.Mpremote("/dev/null-port", "%s %s" % (sys.executable, fake_mp)).exec("print(1)", timeout=2)
check("mpremote: silent board times out", time.time() - t0 < 6 and rc == 124 and bench.timed_out(o), (rc, o))

# ---- whole runs on a fake board (MicroPython unix ports)
MP = os.environ.get("MICROPYTHON") or shutil.which("micropython")
FW = os.environ.get("LV_FROZEN_MP")
logs = tempfile.mkdtemp()


def bench_run(root, mp, *extra):
    p = subprocess.run([sys.executable, os.path.join(GAME, "tools", "bench.py"), "--fake-board", root,
                        "--micropython", mp, "--no-ask", "--log-dir", logs, "--quiet"] + list(extra),
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


if MP:
    root = tempfile.mkdtemp()
    rc, o = bench_run(root, MP, "--ship", "2")
    check("stock: exit 1", rc == 1, o)
    check("stock: names the .uf2", "stock MicroPython" in o and "lv-core-0.1.0-f1b383588e79-RPI_PICO_W.uf2" in o, o)
    check("stock: nothing installed", not os.path.exists(os.path.join(root, "version.json")), os.listdir(root))
else:
    print("test_bench: no MicroPython: skipped the stock-firmware run")

if FW:
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "data"))
    with open(os.path.join(root, "data", "ship.json"), "w") as f:
        json.dump({"http_port": 18081, "fleet_key": "fleet-placeholder", "day": 4, "story": True}, f)
    rc, o = bench_run(root, FW, "--ship", "3", "--launch", "2026-10-15", "--led", "on", "--led-test",
                      "--code", "Phill=1234", "--code", "Kim=4321", "--seconds", "12")
    check("fw: OVERALL PASS", rc == 0 and "OVERALL PASS" in o, o)
    for row in ("firmware/core           PASS", "files hash-match        PASS", "heap used < 80 KB       PASS",
                "BLE up                  PASS", "Wi-Fi hotspot up        PASS", "phone server listening  PASS",
                "captive DNS up          PASS", "flight day              PASS", "LED path                PASS",
                "LED blink test          INFO"):
        check("fw row " + row.split()[0], row in o, o)
    check("fw: codes not printed", "1234" not in o and "4321" not in o)
    check("fw: fleet key not printed", "fleet-placeholder" not in o)
    cfg = json.load(open(os.path.join(root, "data", "ship.json")))
    check("fw: no clobber", cfg == {"http_port": 18081, "fleet_key": "fleet-placeholder", "day": 4, "story": True,
                                    "ship_id": 3, "launch_date": "2026-10-15", "led_notify": True}, cfg)
    crew = json.load(open(os.path.join(root, "data", "crew.json")))
    book = lvcodes.CodeBook(crew)
    check("fw: codes work", book.check(0, "1234", 0)[0] == lvcodes.OK and book.check(2, "4321", 0)[0] == lvcodes.OK
          and not book.is_set(1))
    logs_now = os.listdir(logs)
    check("fw: log saved", any(x.startswith("ship3-") for x in logs_now), logs_now)
    log = open(os.path.join(logs, sorted(x for x in logs_now if x.startswith("ship3-"))[-1])).read()
    check("fw: log has no codes", "1234" not in log and "4321" not in log)
    # again: nothing to write, one more code, the others kept (same salt), the LED switched off
    rc, o = bench_run(root, FW, "--ship", "3", "--led", "off", "--code", "Jai=5555", "--seconds", "5")
    check("fw again: PASS", rc == 0, o)
    check("fw again: no files written", "install: nothing to write" in o or "0 of" in o, o)
    crew2 = json.load(open(os.path.join(root, "data", "crew.json")))
    book = lvcodes.CodeBook(crew2)
    check("fw again: same salt, codes kept", crew2["salt"] == crew["salt"] and book.check(0, "1234", 0)[0] == lvcodes.OK
          and book.check(3, "5555", 0)[0] == lvcodes.OK)
    cfg = json.load(open(os.path.join(root, "data", "ship.json")))
    check("fw again: launch kept, LED off", cfg["launch_date"] == "2026-10-15" and cfg["led_notify"] is False, cfg)
    check("fw again: LED dark", "led off unless asked" not in o or "LED path                PASS" in o, o)
    # A board that goes silent in the selftest (ship 2's radio chip, 2026-10-25): the
    # bench must stop on its own with a FAIL that says to unplug and replug the board.
    Real = bench.FakeBoard

    class HangBoard(Real):
        def exec(self, code, timeout=60, echo=False):
            if "selftest.run" in code:
                return bench.run_with_deadline(subprocess.Popen(SILENT, stdout=subprocess.PIPE,
                                                                stderr=subprocess.STDOUT, text=True), 2)
            return Real.exec(self, code, timeout, echo)

    bench.FakeBoard = HangBoard
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        t0 = time.time()
        rc = bench.main(["--fake-board", root, "--micropython", FW, "--no-ask", "--log-dir", logs, "--quiet",
                         "--ship", "2", "--launch", "2026-10-25", "--led", "on"])
    finally:
        sys.stdout = old
        bench.FakeBoard = Real
    o = out.getvalue()
    check("hang: bench finishes", time.time() - t0 < 120 and rc == 1, (rc, o))
    check("hang: FAIL says replug", re.search(r"selftest ran\s+FAIL\s+TIMEOUT", o) and "Unplug the board" in o
          and "OVERALL FAIL" in o, o)
    # an old-updater ship.json (schema, ship_name, role, hotspot_open: what ttyACM7 had) keeps
    # working, and the open hotspot is pointed out
    with open(os.path.join(root, "data", "ship.json"), "w") as f:
        json.dump({"schema": 2, "ship_id": 1, "ship_name": "Starship-01", "role": "B", "hotspot_open": True,
                   "updated_at": "2026-10-23T00:11:15.363Z", "http_port": 18081}, f)
    rc, o = bench_run(root, FW, "--ship", "3", "--launch", "2026-10-25", "--led", "on", "--seconds", "5")
    check("old ship.json: PASS", rc == 0 and "OVERALL PASS" in o, o)
    check("old ship.json: open hotspot noted", re.search(r"hotspot open\s+INFO", o), o)
    cfg = json.load(open(os.path.join(root, "data", "ship.json")))
    check("old ship.json: ship 3 set, rest kept", cfg["ship_id"] == 3 and cfg["role"] == "B" and
          cfg["launch_date"] == "2026-10-25", cfg)
else:
    print("test_bench: no LV_FROZEN_MP: skipped the fake-board runs")
shutil.rmtree(logs, ignore_errors=True)
print("test_bench: %d checks ok" % n[0])
