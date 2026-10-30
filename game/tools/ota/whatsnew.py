#!/usr/bin/env python3
"""What's new in each release: the few plain lines a player sees in Settings (web/ota.js:
with the update notice, and in Version history). The lines for every release live in
game/tools/ota/whatsnew.json ({version: [line, ...]}); tools/build_release.py takes a
release's lines from there (or --whats-new FILE) and writes them into release.json
("whats_new") and its firmware/index.json entry ("notes", read by the phone online).
game/web/build.py bakes the whole table into the page (OTA_WN), which ships signed in every
release: offline, the phone shows the installed version's lines from it. Never in
version.json or the signed manifest: the ship reads those while it updates, with no heap
to spare, so the ship itself never holds notes (build_release.py checks the page has them).

  python3 game/tools/ota/whatsnew.py --check                 every entry in whatsnew.json
  python3 game/tools/ota/whatsnew.py --index firmware/index.json
        sets "notes" on each index entry that whatsnew.json has (index.json isn't signed, so
        older entries can be given notes without touching their signed releases)

The rules (check()): 1 to NOTES lines, each a non-empty string of at most NOTE_LEN
characters, plain text (no control characters, no < or >), TOTAL bytes at most in all.
The phone shows them as text only and caps them again at the same limits (web/ota.js
otaClean: 3 lines, NOTE_LEN characters, written in by web/build.py)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "whatsnew.json"
NOTES, NOTE_LEN, TOTAL = 3, 120, 400


def check(lines):
    """None if `lines` are good what's-new lines, else why not."""
    if not isinstance(lines, list) or not 1 <= len(lines) <= NOTES:
        return "want a list of 1 to %d lines" % NOTES
    for s in lines:
        if not isinstance(s, str) or not s.strip() or s != s.strip():
            return "a line is empty, not text, or has spaces at an end: %r" % (s,)
        if len(s) > NOTE_LEN:
            return "a line is over %d characters (%d): %r" % (NOTE_LEN, len(s), s)
        if any(ord(c) < 32 or c in "<>\x7f" for c in s):
            return "a line has a control character or < >: %r" % (s,)
    n = len(json.dumps(lines, ensure_ascii=False).encode())
    if n > TOTAL:
        return "%d bytes in all, over %d" % (n, TOTAL)
    return None


def table(path=DATA):
    d = json.loads(Path(path).read_text())
    return {k: v for k, v in d.items() if not k.startswith("_")}


def lines_for(version, path=DATA):
    """The release's lines from whatsnew.json, or None if it has none. Exits on bad ones."""
    v = table(path).get(version)
    if v is None:
        return None
    why = check(v)
    if why:
        raise SystemExit("whatsnew.json %s: %s" % (version, why))
    return v


def read_file(p):
    """--whats-new FILE: a JSON list, or plain text with one line per note."""
    t = Path(p).read_text(encoding="utf-8")
    if t.lstrip().startswith("["):
        v = json.loads(t)
    else:
        v = [x.strip() for x in t.splitlines() if x.strip()]
    why = check(v)
    if why:
        raise SystemExit("%s: %s" % (p, why))
    return v


def fill_index(ip, path=DATA):
    ip = Path(ip)
    idx = json.loads(ip.read_text())
    t, n = table(path), 0
    for r in idx.get("releases", []):
        v = t.get(r.get("version"))
        if v is not None:
            why = check(v)
            if why:
                raise SystemExit("whatsnew.json %s: %s" % (r["version"], why))
            if r.get("notes") != v:
                r["notes"] = v
                n += 1
    ip.write_text(json.dumps(idx, indent=2) + "\n")
    return n


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--index")
    a = ap.parse_args(argv)
    bad = [(k, check(v)) for k, v in table().items() if check(v)]
    for k, why in bad:
        print("whatsnew.json %s: %s" % (k, why), file=sys.stderr)
    if bad:
        raise SystemExit(1)
    if a.index:
        print("%s: notes set on %d entr%s" % (a.index, *(lambda n: (n, "y" if n == 1 else "ies"))(fill_index(a.index))))
    elif a.check:
        print("whatsnew.json: %d releases, all good" % len(table()))


if __name__ == "__main__":
    main()
