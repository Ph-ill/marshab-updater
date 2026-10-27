# Over-the-air updates at boot: swap a staged update in, run it on trial, and put the old
# files back if it doesn't come up. boot.py imports this only when ota/state.json exists,
# so an ordinary boot never loads it. It is never replaced over the air (lvota.bad_path):
# a broken update can't break the code that undoes it. Change it over USB only.
#
# ota/state.json {"phase", "v", "prev", "boots", "put", "had", "gone"}:
#   ready   lvota.apply() wrote it: the files are in ota/new/, checked. Record which
#           targets exist now ("had"), then -> swap.
#   swap    move each target to ota/old/<path>, ota/new/f<I>.ok to <path>; move each
#           "delete" path to ota/old/<path>. Every step looks before it moves, so a power
#           cut part-way through just carries on at the next boot. Then -> trial.
#   trial   count the boot. A third boot without main.py calling lvota.good() means the
#           update failed twice: -> undo. Otherwise arm a deadline (TRIAL_MS): if the game
#           hasn't called good() by then (it crashed, hung in Python, or stopped at the
#           REPL), restart, which counts as the next boot.
#   undo    put every file back from ota/old/ (a file the update added is removed, so a
#           module frozen into the firmware is used again), write ota/last.json
#           {"result": "rolled back"}, clean up. Also resumable.
# data/ is never touched: lvota refuses update paths under it.
# A boot that main.py skips on purpose (data/maint, data/safe: the bench) isn't counted
# and has no deadline. A hang inside C code (the scheduler never runs) isn't caught until
# the board is power-cycled; then that boot counts.
import os
import json

STATE = "ota/state.json"
LAST = "ota/last.json"
NEW = "ota/new"
OLD = "ota/old"
TRIAL_MS = 120000
MAX_BOOTS = 2
timer = None
say = print


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def _mkdirs_for(p):
    a = ""
    for part in p.split("/")[:-1]:
        a = a + "/" + part if a else part
        try:
            os.mkdir(a)
        except OSError:
            pass


def _rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                _rm(p + "/" + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except OSError:
        pass


def _mv(a, b):
    _mkdirs_for(b)
    os.rename(a, b)


def _save(s):
    with open(STATE + ".tmp", "w") as f:
        json.dump(s, f)
    try:
        os.rename(STATE + ".tmp", STATE)     # littlefs: replaces it in one step
    except OSError:                          # a filesystem that won't rename over a file
        os.remove(STATE)
        os.rename(STATE + ".tmp", STATE)


def _load():
    for p in (STATE, STATE + ".tmp"):    # (only .tmp: cut between a remove and a rename)
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _done(result, s):
    j = {"result": result, "v": s.get("v"), "prev": s.get("prev"), "boots": s.get("boots", 0)}
    with open(LAST, "w") as f:
        json.dump(j, f)
    _rm(OLD)
    _rm(NEW)
    for p in (STATE, STATE + ".tmp"):
        try:
            os.remove(p)
        except OSError:
            pass
    say("ota: %s %s (was %s)" % (result, s.get("v"), s.get("prev")))


def prepare(s):
    with open(NEW + "/env") as f:
        m = json.loads(json.load(f)["m"])
    put = [x[0] for x in m["files"]]
    s["put"] = put
    s["had"] = [p for p in put if _exists(p)]
    s["gone"] = [p for p in (m.get("delete") or ()) if _exists(p) and p not in put]
    s["phase"] = "swap"
    _save(s)


def swap(s):
    had = s["had"]
    for i, p in enumerate(s["put"]):
        src = "%s/f%d.ok" % (NEW, i + 1)
        if not _exists(src):
            continue                         # moved in before a power cut
        if p in had and _exists(p) and not _exists(OLD + "/" + p):
            _mv(p, OLD + "/" + p)
        elif _exists(p):
            _rm(p)
        _mv(src, p)
    for p in s["gone"]:
        if _exists(p) and not _exists(OLD + "/" + p):
            _mv(p, OLD + "/" + p)
    s["phase"] = "trial"
    s["boots"] = 0
    _save(s)
    say("ota: %s swapped in, on trial" % s.get("v"))


def undo(s):
    if s.get("phase") != "undo":
        s["phase"] = "undo"
        _save(s)
    had = s.get("had") or []
    for p in s.get("put") or ():
        o = OLD + "/" + p
        if p in had:
            if _exists(o):
                _rm(p)
                _mv(o, p)
        else:
            _rm(p)
    for p in s.get("gone") or ():
        o = OLD + "/" + p
        if _exists(o) and not _exists(p):
            _mv(o, p)
    _done("rolled back", s)


def _deadline(t=None):
    s = _load()
    if s and s.get("phase") == "trial":
        say("ota: the update didn't report in, restarting")
        import machine
        machine.reset()


def arm(ms=TRIAL_MS):
    global timer
    try:
        from machine import Timer
        timer = Timer(-1)                    # a virtual timer: the rp2 port's only kind
        timer.init(mode=Timer.ONE_SHOT, period=ms, callback=_deadline)
    except Exception as e:      # no Timer (CPython, a unix port): the tests call _deadline
        say("ota: no deadline timer (%r)" % (e,))


def run():
    """boot.py: -> the phase the boot continues in (None: nothing pending)."""
    s = _load()
    if not s:
        return None
    ph = s.get("phase")
    try:
        if ph == "ready":
            prepare(s)
            ph = "swap"
        if ph == "swap":
            swap(s)
            ph = "trial"
        if ph == "undo":
            undo(s)
            return "undo"
        if ph == "trial":
            if _exists("data/maint") or _exists("data/safe"):
                return "trial"               # the bench: not a real boot
            s["boots"] = s.get("boots", 0) + 1
            if s["boots"] > MAX_BOOTS:
                say("ota: %s failed to start %d times" % (s.get("v"), MAX_BOOTS))
                undo(s)
                return "undo"
            _save(s)
            arm()
            return "trial"
    except Exception as e:
        # Something is badly off (a missing staged file, a broken state file): put back
        # whatever can be put back rather than boot a half-swapped set.
        say("ota: %r, rolling back" % (e,))
        try:
            undo(s)
        except Exception as e2:
            say("ota: rollback failed too: %r" % (e2,))
            _rm(STATE)
        return "undo"
    return ph
