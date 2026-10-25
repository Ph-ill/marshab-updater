#!/usr/bin/env python3
"""One command per board for the bench: check the firmware, install the test build, set
the ship up, run the serial self-test and print a PASS/FAIL report (docs/BENCH_TEST.md).

  pip install mpremote                       (once)
  python3 game/tools/bench.py --ship 1 --launch 2026-10-15 --led on --led-test

Per board, in order:
  1. finds the Pico W on USB (or --port), reads its firmware: it must be the game firmware
     lv-core 0.1.0 core f1b383588e79. Stock MicroPython or another core stops here and
     names the .uf2 to flash (--uf2 FILE flashes it: the board reboots into BOOTSEL and the
     file is copied onto the RPI-RP2 drive);
  2. installs 0.1.0-lv-test from firmware/releases/ (the same files, deletes and sha256
     checks as the updater page; files already right are skipped), then reads every file's
     sha256 back from the board;
  3. sets /data/ship.json from the flags given and nothing else (other keys, a bench
     "day", day_start, fleet_key... are kept), and crew codes into /data/crew.json (the
     updater's format; names not given keep their code);
  4. runs selftest.run(...) with Wi-Fi, the phone server and the captive DNS as main.py runs
     them, and the time from this computer (as a phone brings it; --no-clock to skip);
     --rollover N moves the flight-day start a minute or two ahead to watch FD N-1 become
     FD N (BENCH_TEST.md section 11), then puts the settings back;
  5. prints one PASS/FAIL/INFO line per check and saves everything to a log file
     (build/bench-logs/) to send back. Exit code 1 if anything failed;
  6. resets the board so it starts the game.
Before the selftest the board is hard-reset into the REPL (machine.reset with /data/maint),
so the CYW43 radio chip starts clean whatever ran on the board before (--no-fresh-boot
skips it). Every mpremote call has a real deadline: a board that goes silent is killed off
and reported as FAIL (unplug it, plug it back in, run again), never a bench that waits forever.

--ships 1,2,3 does several boards in a row (plug each in when asked). --dry-run shows the
plan without a board. --fake-board DIR runs it all against the unix port (tests).
Passwords and crew codes are never printed or logged.
"""
import argparse
import base64
import datetime as DT
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

GAME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(GAME)
RELEASE = os.path.join(REPO, "firmware", "releases", "0.1.0-lv-test", "release.json")
CREW = ["Phill", "Jacques", "Kim", "Jai", "Michelle", "Diego", "Dorian", "Marco"]  # = content/roster.lv
HEAP_CAP = 80000
PICO_VID = "2e8a"
MARK = "BENCHJSON"


# ---------------------------------------------------------------- talking to the board
TIMEOUT_MARK = "bench: TIMEOUT"
REPLUG = ("unplug the board, plug it back in (a power cycle resets its radio chip) and run "
          "bench.py again for this ship")


def run_with_deadline(p, timeout, echo=False):
    """Read a child's output until it exits or `timeout` seconds pass, whichever is first.
    Lines are read on a thread, so the deadline holds even if the child prints nothing at
    all. On the deadline the child is killed. Returns (returncode, output); a timed-out
    run returns 124 (as timeout(1)) and its output ends with a TIMEOUT_MARK line."""
    import queue
    import threading
    q = queue.Queue()

    def reader():
        try:
            for line in p.stdout:
                q.put(line)
        finally:
            q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    out = []
    t0 = time.time()
    last = t0
    deadline = t0 + timeout
    timed_out = False
    while True:
        left = deadline - time.time()
        if left <= 0:
            timed_out = True
            break
        try:
            line = q.get(timeout=min(left, 0.5))
        except queue.Empty:
            continue
        if line is None:
            break
        last = time.time()
        out.append(line)
        if echo:
            sys.stdout.write("  | " + line)
            sys.stdout.flush()
    if timed_out:
        try:
            p.kill()
        except OSError:
            pass
        msg = ("%s after %d s (the board said nothing for the last %d s). Its radio or USB link "
               "is probably stuck: %s.\n" % (TIMEOUT_MARK, timeout, int(time.time() - last), REPLUG))
        out.append(msg)
        if echo:
            sys.stdout.write("  | " + msg)
            sys.stdout.flush()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
    try:
        p.stdout.close()
    except Exception:
        pass
    return (124 if timed_out else p.returncode), "".join(out)


def timed_out(out):
    return TIMEOUT_MARK in (out or "")

class Mpremote:
    """The board over USB serial with mpremote. Board paths are relative to / (its cwd)."""

    def __init__(self, port, mpremote="mpremote", log=print):
        self.port = port
        self.cmd = mpremote.split()
        self.log = log

    def _run(self, args, timeout, echo=False):
        """Run one mpremote command. The deadline is real: a reader thread collects the
        output while this thread waits on the clock, so a board that goes silent (a radio
        chip that never answers, a wedged USB link) can't hold the bench forever. On the
        deadline mpremote is killed and the output ends with a TIMEOUT line (TIMEOUT_MARK)
        that the report turns into a FAIL telling you to unplug and replug the board."""
        p = subprocess.Popen(self.cmd + ["connect", self.port] + args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        return run_with_deadline(p, timeout, echo)

    def exec(self, code, timeout=60, echo=False):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
        try:
            return self._run(["run", f.name], timeout, echo)
        finally:
            os.unlink(f.name)

    def put(self, pairs, timeout=300):
        args = []
        for local, remote in pairs:
            args += ["fs", "cp", local, ":" + remote, "+"]
        return self._run(args[:-1], timeout) if args else (0, "")

    def reset(self):
        return self._run(["reset"], 20)

    def fresh_boot(self, wait_s=25):
        """Hard-reset the board (machine.reset: the RP2040 AND the CYW43 radio chip start
        over) into the REPL, not the game: /data/maint makes main.py skip the game once.
        mpremote's own soft reset keeps the radio chip as the last program left it, and a
        radio left in a bad state by an older program made bluetooth.BLE().active(True)
        wait forever (ship 2, 2026-10-25). Returns True when the board answers again."""
        serial = port_serial(self.port, self.cmd)
        self._run(["exec", "open('/data/maint','w').close()"], 15)
        self._run(["reset"], 15)
        t0 = time.time()
        while time.time() - t0 < wait_s:
            time.sleep(1.5)
            if serial:      # the port can come back under another name after a reset
                p = port_for_serial(serial, self.cmd)
                if p:
                    self.port = p
            rc, out = self._run(["exec", "print('fresh-ok')"], 8)
            if rc == 0 and "fresh-ok" in out:
                self._run(["exec", "import os\ntry: os.remove('/data/maint')\nexcept OSError: pass"], 8)
                return True
        return False

    def bootloader(self):
        return self._run(["bootloader"], 10)


class FakeBoard:
    """A directory standing in for the board's flash, run by the unix port of MicroPython
    (the game firmware's unix build, so the frozen core is there), with stand-ins for the
    radio modules. For tests/test_bench.py; nothing here touches hardware."""

    def __init__(self, root, micropython, log=print):
        self.root = root
        self.mp = micropython.split()
        self.log = log
        self.port = "fake:" + root
        os.makedirs(root, exist_ok=True)

    def exec(self, code, timeout=60, echo=False):
        pre = ("import sys\nsys.path[:0] = [%r, %r]\nimport fakeboard\nfakeboard.install()\n" %
               (os.path.join(GAME, "tests", "fakeboard"), os.path.join(GAME, "tests", "fakeble")))
        path = os.path.join(self.root, "_bench.py")
        with open(path, "w") as f:
            f.write(pre + code)
        try:
            p = subprocess.run(self.mp + ["-X", "heapsize=256k", "_bench.py"], cwd=self.root, capture_output=True,
                               text=True, errors="replace", timeout=timeout)
            out = p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            out, p = (e.stdout or b"").decode() + "%s after %d s: %s\n" % (TIMEOUT_MARK, timeout, REPLUG), None
        finally:
            os.unlink(path)
        if echo:
            for line in out.splitlines():
                print("  | " + line)
        return (p.returncode if p else 124), out

    def put(self, pairs, timeout=300):
        for local, remote in pairs:
            dst = os.path.join(self.root, remote)
            os.makedirs(os.path.dirname(dst) or self.root, exist_ok=True)
            shutil.copyfile(local, dst)
        return 0, ""

    def reset(self):
        return 0, ""

    def fresh_boot(self, wait_s=25):
        return True          # (no radio chip to restart)

    def bootloader(self):
        return 1, "fake board has no bootloader"


def find_ports(mpremote="mpremote"):
    """[(port, description)] of Raspberry Pi USB serial devices (MicroPython on a Pico)."""
    try:
        out = subprocess.run(mpremote.split() + ["connect", "list"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SystemExit("bench: can't run mpremote (%s). Install it: pip install mpremote" % e)
    return parse_ports(out)


def _list(cmd):
    try:
        return subprocess.run(list(cmd) + ["connect", "list"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def port_serial(port, cmd=("mpremote",)):
    """The USB serial number of the Pico on `port` (from mpremote connect list), or None."""
    for line in _list(cmd).splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == port and f[2].lower().startswith(PICO_VID + ":"):
            return f[1]
    return None


def port_for_serial(serial, cmd=("mpremote",)):
    for line in _list(cmd).splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == serial and f[2].lower().startswith(PICO_VID + ":"):
            return f[0]
    return None


def parse_ports(text):
    ports = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3 and f[2].lower().startswith(PICO_VID + ":"):
            ports.append((f[0], " ".join(f[3:])))
    return ports


def board_json(out):
    for line in out.splitlines():
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    raise RuntimeError("no answer from the board:\n" + out[-800:])


# ---------------------------------------------------------------- board-side snippets
PROBE = r'''
import sys, os, json
r = {"mpy": "%d.%d.%d" % tuple(sys.implementation.version[:3]),
     "machine": getattr(sys.implementation, "_machine", "") or os.uname().machine}
try:
    import lvfrozen
    r["frozen"] = {"id": lvfrozen.ID, "version": lvfrozen.VERSION, "core": lvfrozen.CORE}
except Exception:
    r["frozen"] = None
try:
    r["lvx"] = sorted(os.listdir("lvx"))
except OSError:
    r["lvx"] = []
try:
    os.stat("lv")
    r["lv_dir"] = True
except OSError:
    r["lv_dir"] = False
print("BENCHJSON" + json.dumps(r))
'''

HASHES = r'''
import json, hashlib, binascii
out = {}
for p in PATHS:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while True:
                b = f.read(1024)
                if not b:
                    break
                h.update(b)
        out[p] = binascii.hexlify(h.digest()).decode()
    except OSError:
        out[p] = None
print("BENCHJSON" + json.dumps(out))
'''

REMOVE = r'''
import os
def rm(p):
    try:
        st = os.stat(p)
    except OSError:
        return 0
    if st[0] & 0x4000:
        n = 0
        for x in os.listdir(p):
            n += rm(p + "/" + x)
        os.rmdir(p)
        return n + 1
    os.remove(p)
    return 1
n = 0
for p in PATHS:
    n += rm(p)
for d in DIRS:
    try:
        os.mkdir(d)
    except OSError:
        pass
print("BENCHJSON%d" % n)
'''

SETTINGS = r'''
import json, os
try:
    os.mkdir("data")
except OSError:
    pass
try:
    with open("data/ship.json") as f:
        c = json.load(f)
except Exception:
    c = {}
was = dict(c)
c.update(SET)
for k in DROP:
    c.pop(k, None)
if SET or DROP:
    with open("data/ship.json", "w") as f:
        json.dump(c, f)
crew = None
try:
    with open("data/crew.json") as f:
        crew = json.load(f)
except Exception:
    pass
if CODES:
    # the updater's format (lv/codes.py): sha256(salt || crew byte || 4 digits); the salt
    # stays, so names not given keep their code
    import binascii, hashlib
    if not crew or len(crew.get("salt") or "") != 32 or len(crew.get("codes") or []) != 8:
        try:
            r = os.urandom(16)
        except Exception:
            import random
            r = bytes([random.getrandbits(8) for _ in range(16)])
        crew = {"schema": 1, "salt": binascii.hexlify(r).decode(), "codes": [None] * 8}
    salt = binascii.unhexlify(crew["salt"])
    for i in CODES:
        k = CODES[i]
        crew["codes"][i] = binascii.hexlify(hashlib.sha256(salt + bytes([i]) + k.encode()).digest()).decode() if k else None
    with open("data/crew.json", "w") as f:
        json.dump(crew, f)
CODES = None
def safe(c):
    c = dict(c)
    for k in ("hotspot_password", "fleet_key"):
        if c.get(k):
            c[k] = "(set, %d characters)" % len(c[k])
    return c
print("BENCHJSON" + json.dumps({"was": safe(was), "now": safe(c),
                                "crew": [bool(x) for x in crew["codes"]] if crew else None}))
'''

SELFTEST = r'''
import selftest
selftest.run(%(seconds)d, epoch=%(epoch)s, tz=%(tz)d, wifi=True, led=%(led)s, led_test=%(led_test)s%(extra)s)
'''


def snippet(code, **names):
    return "".join("%s = %r\n" % (k, v) for k, v in names.items()) + code


# ---------------------------------------------------------------- the report
def parse_selftest(text):
    """What the SELFTEST lines say: {checks, result, heap_peak, heap_used, firmware, days,
    stats, led, wifi, server, dns, peers}. Lines from other prints are ignored."""
    r = {"checks": {}, "result": None, "stats": [], "days": []}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("SELFTEST "):
            continue
        body = line[9:]
        m = re.match(r"(.+?)\s+(PASS|CHECK)$", body)
        if m and not body.startswith(("RESULT", "t=")):
            r["checks"][m.group(1).strip()] = m.group(2) == "PASS"
            continue
        if body.startswith("RESULT"):
            r["result"] = body[6:].strip()
        elif body.startswith("heap:"):
            m = re.search(r"used (\d+), peak (\d+)", body)
            if m:
                r["heap_used"], r["heap_peak"] = int(m.group(1)), int(m.group(2))
        elif body.startswith("firmware:"):
            r["firmware"] = body[9:].strip()
        elif body.startswith("day:"):
            m = re.search(r"flight day (\d+) \((\w+)\)", body)
            if m:
                r["days"].append((int(m.group(1)), m.group(2)))
        elif body.startswith("t="):
            m = re.match(r"t=(\d+)s STAT .*?led=(\S+) .*?heap_used=(\d+) .*?day=(\d+)/(\w+)", body)
            if m:
                r["stats"].append({"t": int(m.group(1)), "led": m.group(2), "heap_used": int(m.group(3)),
                                   "day": int(m.group(4)), "src": m.group(5)})
        elif body.startswith("led:"):
            r["led"] = body[4:].strip()
        elif body.startswith("wifi:"):
            r["wifi"] = body[5:].strip()
        elif body.startswith("server:"):
            r["server"] = body[7:].strip()
        elif body.startswith("dns:"):
            r["dns"] = body[4:].strip()
        elif body.startswith("peers seen:"):
            r["peers"] = body[11:].strip()
        elif body.startswith("log:"):
            r["log"] = body[4:].strip()
    return r


class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, state, detail=""):
        self.rows.append((name, state, detail))
        return state

    def ok(self):
        return all(s != "FAIL" for _, s, _ in self.rows) and bool(self.rows)

    def text(self):
        w = max([len(n) for n, _, _ in self.rows] + [10])
        return "\n".join("%-*s  %-4s  %s" % (w, n, s, d) for n, s, d in self.rows)


def selftest_checks(rep, st, want_day=None, rollover=None, expect_peers=False, led=None, led_seen=None,
                    led_test=False):
    """Turn parse_selftest() output into report rows."""
    c = st["checks"]
    if st["result"] is None:
        rep.add("selftest ran", "FAIL", "no SELFTEST RESULT line (see the log)")
        return
    rep.add("selftest ran", "PASS", st["result"])
    peak = st.get("heap_peak")
    rep.add("heap used < 80 KB", "PASS" if peak and peak < HEAP_CAP else "FAIL",
            "peak %s B of %d" % (peak, HEAP_CAP))
    rep.add("BLE up", "PASS" if c.get("ble active") else "FAIL", "advertising and scanning")
    for name, key in (("Wi-Fi hotspot up", "wifi hotspot up"), ("phone server listening", "server listening"),
                      ("captive DNS up", "dns listening")):
        if key in c:
            rep.add(name, "PASS" if c[key] else "FAIL",
                    st.get({"wifi hotspot up": "wifi", "server listening": "server", "dns listening": "dns"}[key], ""))
        else:
            rep.add(name, "FAIL", "not reported")
    last = st["stats"][-1] if st["stats"] else None
    if last is None:
        rep.add("flight day", "FAIL", "no STAT line")
    else:
        got = "day=%d/%s" % (last["day"], last["src"])
        if rollover:
            seq = [s["day"] for s in st["stats"]]
            ok = rollover - 1 in seq and seq[-1] == rollover and seq.index(rollover) > seq.index(rollover - 1)
            rep.add("rollover FD %d -> %d" % (rollover - 1, rollover), "PASS" if ok else "FAIL",
                    "STAT days " + " ".join(str(d) for d in seq))
        elif want_day is not None:
            rep.add("flight day", "PASS" if last["day"] == want_day[0] and last["src"] == want_day[1] else "FAIL",
                    "%s (expected day=%d/%s)" % (got, want_day[0], want_day[1]))
        else:
            rep.add("flight day", "INFO", got)
    lp = "led off unless asked"
    if lp in c:
        rep.add("LED path", "PASS" if c[lp] else "FAIL", st.get("led", ""))
    if led_test:
        played = c.get("led test played")
        if not played:
            rep.add("LED blink test", "FAIL", "the pattern didn't run (pin writes too few)")
        elif led_seen is None:
            rep.add("LED blink test", "INFO", "played; only your eyes can tell: 3 slow blinks?")
        else:
            rep.add("LED blink test", "PASS" if led_seen else "FAIL",
                    "you saw the 3 blinks" if led_seen else "you did NOT see the blinks")
    rep.add("peers", ("PASS" if c.get("in sync with a peer") else "FAIL") if expect_peers else "INFO",
            st.get("peers", "none"))


# ---------------------------------------------------------------- the steps
def local_now():
    now = DT.datetime.now().astimezone()
    return now, int(now.utcoffset().total_seconds() // 60)


def expected_day(cfg, now, tz):
    """(day, source) the board should show with the time known, from ship.json values."""
    sys.path.insert(0, os.path.join(GAME, "board"))
    import lvcal
    launch = cfg.get("launch_date")
    if not launch:
        return max(0, int(cfg.get("day", 1) or 0)), "manual"
    z = lvcal.parse_date(launch)
    if z is None:
        return max(0, int(cfg.get("day", 1) or 0)), "manual"
    lm = int(now.timestamp()) // 60 + tz
    return lvcal.flight_day(lm, z, 42, lvcal.parse_hm(cfg.get("day_start", "06:00"))), "phone"


def parse_codes(args):
    out = {}
    if args.codes:
        parts = args.codes.split(",")
        if len(parts) != 8:
            raise SystemExit("bench: --codes needs 8 comma-separated entries in roster order (%s); "
                             "blank = keep" % ", ".join(CREW))
        for i, c in enumerate(parts):
            if c.strip():
                out[i] = c.strip()
    for item in args.code or []:
        name, _, code = item.partition("=")
        names = [n.lower() for n in CREW]
        if name.strip().lower() not in names:
            raise SystemExit("bench: --code NAME=1234, NAME one of %s" % ", ".join(CREW))
        out[names.index(name.strip().lower())] = code.strip()
    for i, code in out.items():
        if code and not re.match(r"^\d{4}$", code):
            raise SystemExit("bench: %s's code must be 4 digits" % CREW[i])
    return out


def settings_from(args, ship):
    """(set, drop) for ship.json from the flags. Only what was given."""
    s, d = {}, []
    if ship is not None:
        s["ship_id"] = ship
    if args.launch is not None:
        if args.launch == "":
            d.append("launch_date")
        else:
            sys.path.insert(0, os.path.join(GAME, "board"))
            import lvcal
            if lvcal.parse_date(args.launch) is None:
                raise SystemExit("bench: --launch wants a real date YYYY-MM-DD")
            s["launch_date"] = args.launch
    if args.day is not None:
        s["day"] = args.day
        if args.launch is None:
            d.append("launch_date")       # a manual day: no calendar
    if args.led is not None:
        s["led_notify"] = args.led == "on"
    pw = args.password if args.password is not None else os.environ.get("LV_HOTSPOT_PASSWORD")
    if pw is not None:
        if not 8 <= len(pw) <= 63:
            raise SystemExit("bench: the hotspot password needs 8-63 characters")
        s["hotspot_password"] = pw
        s["hotspot_open"] = False
    if args.day_start is not None:
        if args.day_start in ("", "06:00"):
            d.append("day_start")
        else:
            s["day_start"] = args.day_start
    return s, d


def flash_uf2(board, uf2, say):
    """machine.bootloader(), then copy the .uf2 onto the RPI-RP2 drive when it shows up."""
    say("flash: rebooting the board into BOOTSEL")
    board.bootloader()
    cands = ["/media/*/RPI-RP2", "/run/media/*/RPI-RP2", "/Volumes/RPI-RP2", "/media/RPI-RP2"]
    import glob
    for _ in range(60):
        for pat in cands:
            for d in glob.glob(pat):
                say("flash: copying %s to %s" % (os.path.basename(uf2), d))
                shutil.copy(uf2, d)
                time.sleep(8)
                return True
        if os.name == "nt":
            for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
                if os.path.exists(letter + ":/INFO_UF2.TXT"):
                    shutil.copy(uf2, letter + ":/")
                    time.sleep(8)
                    return True
        time.sleep(1)
    say("flash: no RPI-RP2 drive appeared in 60 s: drag %s onto it by hand" % os.path.basename(uf2))
    return False


def bench_one(args, ship, board, logf, ask=input):
    rep = Report()

    def say(msg=""):
        print(msg)
        logf.write(msg + "\n")
        logf.flush()

    def run(code, timeout=60, echo=False, what=""):
        rc, out = board.exec(code, timeout, echo)
        logf.write("---- %s (rc %s)\n%s\n" % (what, rc, out))
        logf.flush()
        return rc, out

    release = json.load(open(args.release))
    need = release.get("frozen") or {}
    uf2 = "lv-core-%s-%s-RPI_PICO_W.uf2" % (need.get("version"), need.get("requires"))
    say("== ship %s on %s, release %s (core %s)" % (ship, board.port, release["version"], need.get("requires")))

    # 1. firmware
    try:
        rc, out = run(PROBE, 30, what="probe")
        fw = board_json(out)
    except Exception as e:
        rep.add("board answers", "FAIL", str(e).splitlines()[0])
        return rep
    logf.write("probe: %s\n" % json.dumps(fw))
    say("board: MicroPython %s on %s; frozen %s; lvx %s; /lv %s" % (
        fw["mpy"], fw["machine"], fw["frozen"], fw["lvx"], fw["lv_dir"]))
    if "Pico W" not in fw["machine"] and "Pico 2 W" not in fw["machine"] and not args.fake_board:
        rep.add("board is a Pico W", "FAIL", fw["machine"])
        return rep
    have = fw["frozen"]
    if not have or have["id"] != need.get("id") or have["core"] != need.get("requires"):
        why = ("stock MicroPython (no game firmware)" if not have else
               "game firmware %s %s core %s" % (have["id"], have["version"], have["core"]))
        if args.uf2 and not args.dry_run:
            if flash_uf2(board, args.uf2, say):
                time.sleep(4)
                rc, out = run(PROBE, 30, what="probe after flash")
                try:
                    fw = board_json(out)
                    have = fw["frozen"]
                except Exception:
                    have = None
        if not have or have.get("core") != need.get("requires"):
            rep.add("firmware/core", "FAIL", "%s. Flash %s first: hold BOOTSEL, plug in, drag it onto the "
                    "RPI-RP2 drive (or --uf2 PATH/%s)" % (why, uf2, uf2))
            return rep
    rep.add("firmware/core", "PASS", "%s %s core %s" % (have["id"], have["version"], have["core"]))

    # 2. files
    files = release["files"]
    paths = [f["path"] for f in files]
    if not args.no_install:
        rc, out = run(snippet(HASHES, PATHS=paths), 60, what="hashes before")
        before = board_json(out)
        todo = [f for f in files if before.get(f["path"]) != f["sha256"]]
        todo.sort(key=lambda f: f["path"] == "version.json")      # version.json last, as the updater does
        say("install: %d of %d files to write, removing %s" % (len(todo), len(files), ", ".join(release["delete"])))
        dirs = sorted(set(os.path.dirname(f["path"]) for f in files if "/" in f["path"]))
        rc, out = run(snippet(REMOVE, PATHS=release.get("delete", []), DIRS=dirs), 60, what="remove")
        tmp = tempfile.mkdtemp(prefix="lv-bench-")
        try:
            pairs = []
            for f in todo:
                b = base64.b64decode(f["data"])
                if hashlib.sha256(b).hexdigest() != f["sha256"] or len(b) != f["size"]:
                    raise SystemExit("bench: %s in %s doesn't match its sha256" % (f["path"], args.release))
                p = os.path.join(tmp, f["path"].replace("/", "__"))
                with open(p, "wb") as o:
                    o.write(b)
                pairs.append((p, f["path"]))
            for i in range(0, len(pairs), 6):      # a few files per mpremote call
                rc, out = board.put(pairs[i:i + 6])
                logf.write("---- put %s (rc %s)\n%s\n" % ([r for _, r in pairs[i:i + 6]], rc, out))
                if rc:
                    rep.add("files installed", "FAIL", "copy failed: " + out.strip().splitlines()[-1:][0]
                            if out.strip() else "copy failed")
                    return rep
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    rc, out = run(snippet(HASHES, PATHS=paths), 60, what="hashes after")
    after = board_json(out)
    bad = [f["path"] for f in files if after.get(f["path"]) != f["sha256"]]
    rep.add("files hash-match", "FAIL" if bad else "PASS",
            ("differ: " + ", ".join(bad)) if bad else "%d files, sha256 as in %s" % (len(files), release["version"]))

    # 3. settings
    st_set, st_drop = settings_from(args, ship)
    codes = parse_codes(args)
    rc, out = run(snippet(SETTINGS, SET={}, DROP=[], CODES=None), 30, what="settings read")
    cur = board_json(out)
    restore = None
    now, tz = local_now()
    if args.rollover:
        n = args.rollover
        if not 2 <= n <= 42:
            raise SystemExit("bench: --rollover N wants 2-42")
        t = (now + DT.timedelta(seconds=75)).replace(second=0, microsecond=0) + DT.timedelta(minutes=1)
        if t.date() != now.date():
            raise SystemExit("bench: too close to midnight for --rollover; try after 00:05")
        launch = (now.date() - DT.timedelta(days=n - 1)).isoformat()
        restore = ({k: cur["now"][k] for k in ("launch_date", "day_start") if k in cur["now"]},
                   [k for k in ("launch_date", "day_start") if k not in cur["now"]])
        if "launch_date" in st_set:
            restore[0]["launch_date"] = st_set["launch_date"]
            if "launch_date" in restore[1]:
                restore[1].remove("launch_date")
        st_set.update({"launch_date": launch, "day_start": t.strftime("%H:%M")})
        st_drop = [k for k in st_drop if k not in ("launch_date", "day_start")]
        args.seconds = max(args.seconds, int((t - now).total_seconds()) + 40)
        say("rollover: launch_date %s, day_start %s for the test: FD %d now, FD %d at %s (selftest %d s)" % (
            launch, t.strftime("%H:%M"), n - 1, n, t.strftime("%H:%M"), args.seconds))
    rc, out = board.exec(snippet(SETTINGS, SET=st_set, DROP=st_drop, CODES=codes), 30)
    logf.write("---- settings write (rc %s; the codes themselves are not logged)\n%s\n" % (rc, out))
    res = board_json(out)
    cfg = res["now"]
    shown = dict(cfg)
    say("ship.json: " + json.dumps(shown, sort_keys=True))
    want_ok = all(cfg.get(k) == v for k, v in st_set.items() if k != "hotspot_password") and \
        all(k not in cfg for k in st_drop)
    rep.add("settings saved", "PASS" if want_ok else "FAIL",
            "set %s; kept the rest" % (", ".join(sorted(list(st_set) + ["-" + k for k in st_drop])) or "nothing"))
    if not res.get("crew") or not any(res["crew"]):
        rep.add("crew codes", "FAIL", "no codes in data/crew.json: nobody can sign in (--code Phill=1234 ...)")
    else:
        rep.add("crew codes", "PASS", "%sset for %s" % ("written; " if codes else "",
                                                       ", ".join(CREW[i] for i in range(8) if res["crew"][i])))
    if not cfg.get("hotspot_password") and not cfg.get("hotspot_open"):
        rep.add("hotspot password", "INFO", "none set: the AP uses the public placeholder (--password or "
                "LV_HOTSPOT_PASSWORD)")
    if cfg.get("hotspot_open") and not cfg.get("hotspot_password"):
        rep.add("hotspot open", "INFO", "ship.json has hotspot_open true (an older updater setting): the AP "
                "has no password; --password or LV_HOTSPOT_PASSWORD sets one and closes it")

    # 4. selftest
    if not args.no_selftest:
        if not args.no_fresh_boot:
            say("restart: hard reset first so the radio chip starts clean (a few seconds)...")
            if not board.fresh_boot():
                rep.add("board answers after reset", "FAIL", "no answer within 25 s: " + REPLUG)
                return rep
            logf.write("fresh boot: ok, port %s\n" % board.port)
        led = cfg.get("led_notify", False)
        extra = ""
        if args.fake_board:
            extra = ", data='data', dns_port=5353"
        code = SELFTEST % {"seconds": args.seconds, "epoch": "None" if args.no_clock else int(now.timestamp() * 1000),
                           "tz": tz, "led": bool(led), "led_test": bool(args.led_test), "extra": extra}
        if args.led_test:
            say("LED: watch the board's LED: 3 slow blinks (1 s on, 1 s off) in the first seconds. "
                "Through the current case: take the lid off, or look at the LED's spot from the side.")
        say("selftest: %d s (Wi-Fi, phone server, DNS, BLE%s)..." % (
            args.seconds, ", rollover" if args.rollover else ""))
        rc, out = run(code, args.seconds + 120, echo=not args.quiet, what="selftest")
        if timed_out(out):
            last = [ln for ln in out.splitlines() if ln.startswith("SELFTEST ")]
            rep.add("selftest ran", "FAIL", "TIMEOUT: the board stopped answering%s. %s" % (
                " after: " + last[-1][9:60] if last else "", REPLUG[0].upper() + REPLUG[1:]))
            return rep
        st = parse_selftest(out)
        seen = None
        if args.led_test and not args.no_ask:
            a = ask("Did you see 3 slow blinks on the LED? [y/n] ").strip().lower()
            seen = a.startswith("y")
            logf.write("led blink answer: %s\n" % a)
        want = None if args.no_clock else expected_day(cfg, DT.datetime.now().astimezone(), tz)
        if want is not None and want[1] == "manual" and not cfg.get("launch_date"):
            want = (want[0], "manual")
        selftest_checks(rep, st, want_day=want, rollover=args.rollover, expect_peers=args.peers,
                        led=led, led_seen=seen, led_test=args.led_test)
        if restore is not None:
            rc, out = run(snippet(SETTINGS, SET=restore[0], DROP=restore[1], CODES=None), 30, what="settings restore")
            say("rollover: settings put back: %s" % json.dumps(board_json(out)["now"], sort_keys=True))

    # 5. start the game
    if not args.no_reset:
        board.reset()
        say("reset: the board restarts into the game (hotspot %s%s)" % (cfg.get("ssid_prefix", "LV-"), cfg.get("ship_id", ship)))
    return rep


def redact_argv(argv):
    """The command line for the log, without crew codes or the hotspot password."""
    out, hide = [], False
    for a in argv:
        if hide:
            out.append(re.sub(r"\d", "#", a) if "=" in a or "," in a else "...")
            hide = False
        elif a in ("--code", "--codes", "--password"):
            out.append(a)
            hide = True
        elif a.startswith(("--code=", "--codes=", "--password=")):
            k, v = a.split("=", 1)
            out.append(k + "=" + (re.sub(r"\d", "#", v) if k != "--password" else "..."))
        else:
            out.append(a)
    return out


def main(argv=None, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--ship", type=int, help="ship number 1-8 (the hotspot is LV-<ship>)")
    ap.add_argument("--ships", help="several boards in a row, e.g. 1,2,3 (plug each in when asked)")
    ap.add_argument("--port", help="serial port (default: the one Pico W found)")
    ap.add_argument("--launch", help="launch date YYYY-MM-DD (FD 1 starts 06:00 that day); '' clears it")
    ap.add_argument("--day", type=int, help="manual bench flight day 1-42 (clears the launch date unless --launch)")
    ap.add_argument("--day-start", help="flight day start HH:MM (bench only; 06:00 or '' removes it)")
    ap.add_argument("--led", choices=["on", "off"], help="LED notifier (led_notify)")
    ap.add_argument("--led-test", action="store_true", help="play 3 slow blinks during the selftest and ask if you saw them")
    ap.add_argument("--code", action="append", help="crew code NAME=1234 (repeat); other names keep theirs")
    ap.add_argument("--codes", help="all 8 codes in roster order, comma-separated (blank keeps)")
    ap.add_argument("--password", help="hotspot password (8-63); or set LV_HOTSPOT_PASSWORD so it isn't in your shell history")
    ap.add_argument("--rollover", type=int, metavar="N", help="watch FD N-1 become FD N within ~2 min (BENCH_TEST.md 11)")
    ap.add_argument("--seconds", type=int, default=60, help="selftest length (default 60)")
    ap.add_argument("--peers", action="store_true", help="another board is on: peer sync is a check, not info")
    ap.add_argument("--no-clock", action="store_true", help="don't give the board this computer's time")
    ap.add_argument("--no-install", action="store_true", help="skip installing files (still checks their hashes)")
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--no-reset", action="store_true", help="leave the board at the REPL afterwards")
    ap.add_argument("--no-fresh-boot", action="store_true",
                    help="skip the hard reset before the selftest (by default the radio chip is restarted)")
    ap.add_argument("--no-ask", action="store_true", help="don't ask questions (LED test: report INFO)")
    ap.add_argument("--quiet", action="store_true", help="don't echo the selftest output")
    ap.add_argument("--uf2", help="the game firmware .uf2: flash it if the board has other firmware")
    ap.add_argument("--release", default=RELEASE, help="release.json to install (default 0.1.0-lv-test)")
    ap.add_argument("--log-dir", default=os.path.join(GAME, "build", "bench-logs"))
    ap.add_argument("--mpremote", default=os.environ.get("MPREMOTE", "mpremote"))
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    ap.add_argument("--fake-board", help=argparse.SUPPRESS)
    ap.add_argument("--micropython", default=os.environ.get("LV_FROZEN_MP", "micropython"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    ships = [int(x) for x in args.ships.split(",")] if args.ships else [args.ship]
    if ships == [None] and not args.dry_run:
        ap.error("--ship N (or --ships 1,2,3)")
    if args.day is not None and not 1 <= args.day <= 42:
        ap.error("--day 1-42")
    for s in ships:
        if s is not None and not 1 <= s <= 8:
            ap.error("ship numbers are 1-8")
    if args.dry_run:
        rel = json.load(open(args.release))
        st_set, st_drop = settings_from(args, ships[0])
        if "hotspot_password" in st_set:
            st_set["hotspot_password"] = "(given)"
        codes = parse_codes(args)
        print("dry run: release %s, %d files, core %s" % (rel["version"], len(rel["files"]), rel["frozen"]["requires"]))
        for s in ships:
            st_set["ship_id"] = s
            print("ship %s: check the firmware; remove %s; write files whose sha256 differs; ship.json set %s drop %s;"
                  " crew codes %s; selftest %d s%s%s; report; reset" % (
                      s, ", ".join(rel["delete"]), json.dumps(st_set, sort_keys=True), st_drop,
                      ("set for " + ", ".join(CREW[i] for i in sorted(codes))) if codes else "kept", args.seconds,
                      ", LED blink test" if args.led_test else "", ", rollover to FD %d" % args.rollover
                      if args.rollover else ""))
        return 0
    os.makedirs(args.log_dir, exist_ok=True)
    summary = []
    for k, ship in enumerate(ships):
        if len(ships) > 1:
            if k and not args.port and not args.fake_board:
                ask("\nUnplug that board, plug in the board for ship %d, then press Enter " % ship)
            elif not k and not args.fake_board:
                ask("Plug in the board for ship %d (only that one), then press Enter " % ship)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        logp = os.path.join(args.log_dir, "ship%s-%s.log" % (ship, stamp))
        with open(logp, "w") as logf:
            logf.write("bench.py %s\n" % " ".join(redact_argv(argv if argv is not None else sys.argv[1:])))
            if args.fake_board:
                board = FakeBoard(args.fake_board if len(ships) == 1 else os.path.join(args.fake_board, str(ship)),
                                  args.micropython)
            else:
                port = args.port
                if not port:
                    found = find_ports(args.mpremote)
                    if len(found) != 1:
                        msg = ("no Pico W on USB (a data cable? a board in BOOTSEL shows as the RPI-RP2 drive "
                               "instead: drag the .uf2 onto it)" if not found else
                               "%d Picos on USB (%s): unplug the others or pass --port" % (
                                   len(found), ", ".join(p for p, _ in found)))
                        print("bench: " + msg)
                        logf.write(msg + "\n")
                        summary.append((ship, False, logp))
                        continue
                    port = found[0][0]
                board = Mpremote(port, args.mpremote)
            rep = bench_one(args, ship, board, logf, ask)
            out = "\nREPORT ship %s (%s)\n%s\nOVERALL %s\nlog: %s" % (
                ship, time.strftime("%Y-%m-%d %H:%M %Z"), rep.text(), "PASS" if rep.ok() else "FAIL", logp)
            print(out)
            logf.write(out + "\n")
        summary.append((ship, rep.ok(), logp))
    if len(ships) > 1:
        print("\nSUMMARY")
        for s, ok, p in summary:
            print("ship %s  %s  %s" % (s, "PASS" if ok else "FAIL", p))
    return 0 if all(ok for _, ok, _ in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
