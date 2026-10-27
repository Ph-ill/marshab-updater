#!/usr/bin/env python3
"""Build the phone page: inline web/render.js (and engage.js/.css, batt.js/.css) into web/app.html, strip comments and
indentation, gzip it. Writes build/app.html and build/app.html.gz (what the Pico serves).

  python3 web/build.py
"""
import gzip
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
BUDGET = 128 * 1024


def squeeze(src):
    out = []
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        out.append(s)
    return "\n".join(out)


def main():
    html = open(os.path.join(HERE, "app.html"), encoding="utf-8").read()
    js = open(os.path.join(HERE, "render.js"), encoding="utf-8").read()
    js = re.sub(r"^export\s+", "", js, flags=re.M)
    html = html.replace("/*RENDER_JS*/", js)
    # Engagement screens and their styles (web/engage.js, web/engage.css), if present.
    # The ship's battery (web/batt.js, .css) and over-the-air updates (web/ota.js, .css)
    # the same way.
    for name, mark in (("engage.js", "/*ENGAGE_JS*/"), ("engage.css", "/*ENGAGE_CSS*/"),
                       ("batt.js", "/*BATT_JS*/"), ("batt.css", "/*BATT_CSS*/"),
                       ("ota.js", "/*OTA_JS*/"), ("ota.css", "/*OTA_CSS*/")):
        path = os.path.join(HERE, name)
        src = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if name.endswith(".css"):
            src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        html = html.replace(mark, src)
    html = squeeze(html)
    os.makedirs(BUILD, exist_ok=True)
    raw = html.encode("utf-8")
    open(os.path.join(BUILD, "app.html"), "wb").write(raw)
    gz = gzip.compress(raw, 9, mtime=0)
    open(os.path.join(BUILD, "app.html.gz"), "wb").write(gz)
    print("app.html %d B, gzip %d B (%.1f%% of the %d KB budget)" % (len(raw), len(gz), 100 * len(gz) / BUDGET, BUDGET // 1024))
    assert len(gz) < BUDGET


if __name__ == "__main__":
    main()
