"""Draw the iOS launch screens (web/launch/<W>x<H>.png): what a home-screen icon shows while
the game starts, and for as long as it can't reach the ship. Dark, in the game's style: the
icon's trajectory chart (Earth, the arc, the ship, Mars), THE LONG VOYAGE, and "Connect to
your ship's Wi-Fi to play". No story text. iOS only uses one whose size matches the screen
exactly, so there is one per current iPhone portrait size (SIZES; app.html links them with
media queries). 4-colour palette PNGs (2 bits a pixel), about 7 KB each. Needs Pillow and IBM Plex Mono (or
DejaVu Sans Mono); the PNGs are committed, so a build doesn't redraw them.

    python3 web/launch.py        # writes web/launch/*.png and prints the sizes
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# (width, height, scale) in pixels; the media query is the size in points and the ratio. Newest
# first: 16/17 Pro Max, 14/15 Pro Max and Plus, 16/17 Pro and 17, 14/15/16, 12/13 Pro Max and
# 14 Plus, 12/13/14 and 16e, SE and 6-8. web/build.py imports this (without Pillow).
SIZES = ((1320, 2868, 3), (1290, 2796, 3), (1206, 2622, 3), (1179, 2556, 3), (1284, 2778, 3),
         (1170, 2532, 3), (750, 1334, 2))
BG, INK, RUST = (0x1C, 0x1B, 0x19), (0xEC, 0xE5, 0xD6), (0xD9, 0x67, 0x3C)
MID = (0x84, 0x80, 0x78)                # the anti-aliased edges
FONTS = ("/usr/share/fonts/truetype/sand-box/google/IBM Plex Mono/IBMPlexMono-%s.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono%s.ttf")


def font(bold, px):
    from PIL import ImageFont
    for f in FONTS:
        p = f % (("Bold" if bold else "Regular") if "Plex" in f else ("-Bold" if bold else ""))
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    raise SystemExit("no monospace font found")


def draw(w, h, k):
    """k: pixels per point. Laid out in points, centred a little above the middle."""
    from PIL import Image, ImageDraw
    ss = 2                                   # draw at 2x, then shrink: smooth edges
    im = Image.new("RGB", (w * ss, h * ss), BG)
    d = ImageDraw.Draw(im)
    u = k * ss                               # pixels per point at draw size
    cx, top = w * ss / 2, h * ss * 0.36
    # The chart, 160 pt wide (icon.py's drawing: a 124 pt arc over a dashed rule).
    rx, ry, cy = 62 * u, 66 * u, top + 66 * u
    d.arc((cx - rx, cy - ry, cx + rx, cy + ry), 180, 360, fill=INK, width=round(3 * u))
    x = cx - 76 * u
    while x < cx + 76 * u:
        d.rectangle((x, cy - 1 * u, min(x + 8 * u, cx + 76 * u), cy + 1 * u), fill=INK)
        x += 14 * u
    for (px, py), r, c in (((cx - rx, cy), 12, INK), ((cx + rx, cy), 15, RUST)):
        d.ellipse((px - r * u, py - r * u, px + r * u, py + r * u), fill=c)
    t = math.radians(122)
    sx, sy = cx + rx * math.cos(t), cy - ry * math.sin(t)
    d.ellipse((sx - 10 * u, sy - 10 * u, sx + 10 * u, sy + 10 * u), fill=BG)
    d.ellipse((sx - 7 * u, sy - 7 * u, sx + 7 * u, sy + 7 * u), fill=RUST)
    # The name, then what to do.
    y = cy + 56 * u
    for text, f, c, gap in (("THE LONG VOYAGE", font(True, round(22 * u)), INK, 40),
                            ("Connect to your ship's", font(False, round(16 * u)), INK, 24),
                            ("Wi-Fi to play", font(False, round(16 * u)), INK, 0)):
        tw = d.textlength(text, font=f)
        d.text((cx - tw / 2, y), text, font=f, fill=c)
        y += gap * u
    im = im.resize((w, h), Image.LANCZOS)
    pal = Image.new("P", (1, 1))         # 4 colours: edges fall on MID, never on rust
    pal.putpalette(BG + INK + RUST + MID)
    return im.quantize(palette=pal, dither=Image.Dither.NONE)


def links():
    """The <link> tags for app.html (web/build.py): portrait only, one exact size each."""
    return "".join('<link rel="apple-touch-startup-image" media="(device-width:%dpx) and (device-height:%dpx)'
                   ' and (-webkit-device-pixel-ratio:%d) and (orientation:portrait)" href="/ls/%dx%d.png">\n'
                   % (w // k, h // k, k, w, h) for w, h, k in SIZES)


def main():
    out = os.path.join(HERE, "launch")
    os.makedirs(out, exist_ok=True)
    tot = 0
    for w, h, k in SIZES:
        p = os.path.join(out, "%dx%d.png" % (w, h))
        draw(w, h, k).save(p, optimize=True, bits=2)
        n = os.path.getsize(p)
        tot += n
        print("%s %d B" % (os.path.relpath(p, HERE), n))
    print("launch screens: %d files, %d B" % (len(SIZES), tot))


if __name__ == "__main__":
    main()
