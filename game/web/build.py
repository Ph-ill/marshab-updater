#!/usr/bin/env python3
"""Build the phone page: inline web/render.js (and engage.js/.css, batt.js/.css, ota.js/.css, a2hs.js/.css) into web/app.html, strip comments and
indentation, gzip it. Writes build/app.html and build/app.html.gz (what the Pico serves),
plus build/app.webmanifest.gz and build/icon.png.gz for the home screen.

  python3 web/build.py
"""
import gzip
import os
import re
import sys

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
    # iOS launch screens (web/launch.py draws them; main.py serves /ls/<W>x<H>.png).
    sys.path.insert(0, HERE)
    import launch
    html = html.replace("<!--LAUNCH-->\n", launch.links())
    # Engagement screens and their styles (web/engage.js, web/engage.css), if present.
    # The ship's battery (web/batt.js, .css) and over-the-air updates (web/ota.js, .css)
    # the same way.
    for name, mark in (("engage.js", "/*ENGAGE_JS*/"), ("engage.css", "/*ENGAGE_CSS*/"),
                       ("batt.js", "/*BATT_JS*/"), ("batt.css", "/*BATT_CSS*/"),
                       ("ota.js", "/*OTA_JS*/"), ("ota.css", "/*OTA_CSS*/"),
                       ("a2hs.js", "/*A2HS_JS*/"), ("a2hs.css", "/*A2HS_CSS*/"),
                       ("settings.js", "/*SET_JS*/"), ("settings.css", "/*SET_CSS*/"),
                       ("fullscreen.js", "/*FS_JS*/"), ("fullscreen.css", "/*FS_CSS*/"),
                       ("funnel.js", "/*FUN_JS*/"), ("funnel.css", "/*FUN_CSS*/")):
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
    home_screen()


# What a phone fetches to put the game on its home screen (web/a2hs.js): the manifest and
# one 192 px icon (web/icon.png, drawn by web/icon.py), gzipped like everything the board
# serves. The name, short name too, is "The Long Voyage" (Phill's choice), not a ship's:
# every ship answers on the same address, so one icon opens whichever ship's Wi-Fi you're
# on. It's a little wide for one line under an iPhone icon (docs/OTA.md section 6). The
# background is dark, like the launch screens (web/launch.py): it's what a launcher shows
# while the page starts. start_url carries ?src=icon, the marker web/funnel.js takes as
# "opened from the icon" (Android's shortcut opens a plain Chrome tab; iOS runs standalone).
MANIFEST = {"name": "The Long Voyage", "short_name": "The Long Voyage", "id": "/", "start_url": "/?src=icon",
            "scope": "/", "display": "standalone", "orientation": "portrait",
            "background_color": "#1C1B19", "theme_color": "#F2ECDF",
            "icons": [{"src": "/icon.png", "sizes": "192x192", "type": "image/png", "purpose": "any"}]}


def home_screen():
    import json
    m = json.dumps(MANIFEST, separators=(",", ":")).encode()
    icon = open(os.path.join(HERE, "icon.png"), "rb").read()
    for name, raw in (("app.webmanifest", m), ("icon.png", icon)):
        gz = gzip.compress(raw, 9, mtime=0)
        open(os.path.join(BUILD, name + ".gz"), "wb").write(gz)
        print("%s %d B, gzip %d B" % (name, len(raw), len(gz)))


if __name__ == "__main__":
    main()
