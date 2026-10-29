# Over-the-air updates

A ship can update its game software from a phone, without a USB cable or a file you
download yourself. The phone looks for a newer signed release on GitHub whenever it can
reach the internet. It keeps the release, and when it's on the ship's Wi-Fi it offers
to install it: a notice on the home screen (**Install** / **Later**), and
**Settings › Ship software** (the gear at the top right; docs/SETTINGS.md, which also covers Change your code and Test light), which shows what's installed, what's available, when it last
checked, and a **Check for updates** button. Installing sends the release to the ship
in small pieces. The ship checks the signature and every file, switches over at
restart, and goes back by itself if the new version doesn't start.

Your settings and the game (`data/`) are never touched.

Anything marked **[NEEDS A REAL PHONE]** has only been reasoned about or tried in desktop
Chrome. Section 7 lists the tests still to do. Section 6 covers putting the game on
your phone's home screen, which is how the release cache lasts best on an iPhone.

## 1. The parts

| Part | Where | What it does |
|---|---|---|
| Update check, notice, screen, upload | `web/ota.js`, `web/ota.css` (built into `app.html`) | runs on the phone |
| Upload, checks, staging | `board/lvota.py` | `/api/ota*` on the ship |
| Upload pieces (0.3.0) | `board/lvotap.py`, `board/lvotaq.py` | `POST /api/ota/put`: small, loaded per request |
| Signature check | `board/lvsig.py` | Ed25519 verify in pure MicroPython |
| Switch-over and rollback | `board/lvboot.py`, `board/boot.py` | runs at power-up, before `main.py` |
| Reporting in | `board/main.py` | calls `lvota.good()` 30 s after the game is up |
| Signing | `tools/ota/sign_release.py`, `tools/ota/ed25519.py` | on the release machine |
| Release check | `tools/validate_firmware.py` (repo root) | verifies the envelope like a ship would |

Only releases for a frozen core (game firmware lv-core 0.2.0 and later) can go over the
air. A ship needs one install over USB of a build with `boot.py`, `lvboot`, `lvota` and
`lvsig` (this branch's `tools/board_build.sh`) before it can take updates. After that,
updates never replace `boot.py` or `lvboot`: the rollback can't be broken by the update
it has to undo.

## 2. Where the phone gets releases

`https://raw.githubusercontent.com/<repo>/main/firmware/index.json`, then the entry's
`release.json`. These come from the updater's own repo, which already holds every release.
`raw.githubusercontent.com` sends `Access-Control-Allow-Origin: *`, so the page (served
from `http://192.168.4.1`) can read them with a plain `fetch` GET. Anything that needs a
CORS preflight is refused (403), so the page sends no custom headers. GitHub release
assets and `api.github.com` don't work from the page: assets redirect to a host without
CORS, and the API is rate-limited per IP.

A release is offered only when:

- the index entry has `"ota": <key id>`, which `sign_release.py` sets;
- the release is the one on the ship's own channel (`channels[ch]`);
- it's built for the core the ship runs (`frozen` equals the ship's core hash);
- it's newer than the installed version, compared the way `src/releases.js` compares versions.

`test` and `bench` builds follow their own channels, so a stable ship never sees them.

**A test ship on a test branch.** The phone reads `main` unless the ship says otherwise:
`"ota_src": "<branch>"` in that ship's `/data/ship.json` (by hand, or with mpremote) makes
`/api/ota` report `src`, and the page then fetches `index.json` and the release from
`https://raw.githubusercontent.com/<repo>/<branch>/firmware/...` instead. Push a signed
test release and its index entry to that branch (never `main`) and only the ship pointed
at it sees it; every other ship, and this one with the key removed, stays on `main`. It
is a branch name only (letters, digits, `. _ - /`, at most 64, no `..`), never a URL, so
a ship can't point a phone at another site, and what's fetched still has to be signed by
a key in `KEYS`. When `src` changes, the phone forgets the release it had cached and
checks again. `data/` is otherwise untouched: `lvota.status()` reads that one key.

The phone checks at most every 6 hours, or every 2 minutes after a failed check. It also
checks when the page comes back to the foreground (`visibilitychange`), when the browser
says it's online again (`online`), and when you tap **Check for updates**. Every fetch
times out after 8 s. A failed check sets "no internet" on the Ship software screen and
nothing else: no notice and no error banner.

The release (about 55–75 KB of base64) is kept in `localStorage` for the ship's origin
(`http://192.168.4.1`), so it's still there after the phone leaves the network and comes
back. If storage is full or turned off, the phone keeps nothing and simply checks again
next time.

## 3. The signature

- **Key.** Ed25519. The private key lives only on the release machine, outside the repo
  (`~/.secrets/lv_ota_signing_key`, mode 600, PKCS#8 PEM). The ships carry the public key
  in `board/lvota.py` `KEYS`, under its id (the first 8 hex of sha256(public key)).
  `sign_release.py --keygen PATH` makes a new key and prints only the public half.
- **Manifest.**
  `{"schema":1,"project":"LongVoyage","version","channel","core","files":[[path,size,sha256],...],"delete":[...]}`.
  `sign_release.py` builds it from `release.json`. It leaves `boot.py` and `lvboot` out,
  refuses anything in `data/` or `ota/`, and never deletes a protected path.
- **Envelope.** `{"m": manifest text, "sig": base64, "kid"}`. The signed message is
  `b"LV-OTA-1\n" + sha256(manifest text)`.
- **Ship-side check, before anything is staged.** The ship takes the envelope first.
  It reads the key id, verifies the signature, then checks the manifest. It refuses:
  - a different project or schema;
  - another core;
  - another channel;
  - the same or an older version (no downgrades or replays);
  - more than 40 files;
  - a file over 256 KB;
  - a bad path: absolute, `..`, dotfiles, `data/`, `ota/`, `boot.py` or `lvboot.*`;
  - not enough flash (it keeps 16 KB spare).

  Each file is then checked against its sha256 as its last piece lands. The ship accepts
  no file the manifest doesn't name.
- **Why not HMAC.** A shared secret would have to be on every ship. Anyone who read one
  board's flash could sign updates for all of them. With Ed25519 the ships hold only a
  public key.

**Cost on the ship** (MicroPython, `lvsig.py` compiled with `mpy-cross -O3`):

| Measure | Value | How |
|---|---|---|
| Module size | 4960 B | — |
| Heap while verifying | 6544 B at peak, 5200 B after | unix port, frozen build |
| Verify time, unix port (x86-64) | 12.35 ms | — |
| Verify time, CPython | 1.75 ms | — |
| Verify time, RP2040 at 125 MHz | **[NOT MEASURED YET]**, estimated 1–2.5 s | — |

The verify uses a 1-bit Shamir double scalar multiply. It's slower than a 2-bit table
(8.1 ms but a 10.2 KB peak) but needs less RAM. SHA-512 reads its round constants from a
hex string and keeps a 16-word rolling schedule, rather than holding an 80-entry table. The
verify loop calls `lvweb.probe` every 64 bits, so the heap gate sees its peak.

**Heap gate** (`tests/phone_heap.py`, frozen build, two phones playing during a BLE sync):

| Run | Board peak | Limit |
|---|---|---|
| Without `--ota` | 50560 B | 80000 B |
| With a third phone uploading a signed update (`--ota`, 7 files, 72.6 KB in 1 KB pieces) | 64832 B | 80000 B |
| With `--led --bat --ota` | 64192 B | 80000 B |

The peak is during the verify: `lvota` itself (about 7.5 KB) plus `lvsig` at work (about
6.5 KB). Both are dropped from memory as soon as the request is done.

**0.3.0: the busiest season with Hail.** With all eight crew playing every day
(`sim/season.py --everyone`, ~20 KB of log in the frozen core's RAM) and Hail on, 0.2.7
peaked at ~84.5 KB, not at the verify but during the upload's pieces: all of `lvota`
(~8 KB) loaded for each piece, the manifest parsed from `ota/new/env` each time, three
requests in flight. 0.3.0 splits the upload out:

- `lvotap` (~2.7 KB loaded) takes a piece. It finds the file's size and checksum in
  `ota/new/ix`, one fixed-width line per file written when the envelope checks out, not
  in the manifest. A 0.2.7 staging without `ix` gets one written on the first piece.
- `lvotaq` (~0.5 KB), loaded before `lvotap` and dropped after, makes a file piece wait
  (up to 3 s) until no other request is in flight, and the envelope's last piece wait (up
  to 60 s) for a quiet radio, as before.
- At the envelope's signature check `lvota` is dropped and only `lvsig` (~4 KB) is loaded.

Measured (frozen lv32, `phone_heap.py ... --led --bat --ota --live --everyone`, eight
runs): 76.0–79.1 KB board peak, so about 1 KB to spare at worst; the test enforces the
80,000 B cap again. Without Hail ~75–76 KB. These savings apply to updates *installed by*
0.3.0 or later: a 0.2.7 ship takes 0.3.0 with its own 0.2.7 `lvota`.

**If an upload still runs out of heap.** The ship's server catches a `MemoryError` in a
request, closes that connection and collects. The phone retries a failed piece five
times with a growing pause, then shows the error; tapping Install again carries on from
what's staged (`staged.have`). A file whose bytes all landed but whose check never ran
shows one byte short, so its last piece is sent again and checked then. A ship that
crashes twice in a row starts in safe mode (`board/lvsafe.py`): no story, no log in RAM,
just sign-in and `/api/ota*`. `tests/phone_heap.py --safe` measures a whole upload there
while another phone looks around: ~52 KB board peak, ~28 KB to spare.

## 4. On the ship

`/api/ota` (GET, open to anyone on the hotspot) returns
`{ota, v, ch, core, chunk, free, last, phase, staged, src}`. Every POST needs a signed-in crew
member's `X-Crew-Token`, otherwise it gets 401.

1. **`POST /api/ota/put?f=0&n=<envelope bytes>&o=<offset>`, then
   `?f=<file number>&o=<offset>`.** The ship takes pieces of up to `chunk` bytes (1024),
   written to `ota/new/env` and `ota/new/f<i>`.
   - A piece at the wrong offset gets 409 `{have}`, so the phone resumes from there.
     `staged.have` in the status does the same after a reload.
   - Too many bytes gets 400.
   - The envelope is checked as soon as it's complete. If it's bad, the ship answers 403
     and throws the staging away.
2. **`POST /api/ota/apply`.** Only once every file is in and checked. The ship writes
   `ota/state.json` with `phase: "ready"`, answers `{restart_ms}` and restarts a second later.
3. **`boot.py` → `lvboot.run()` at power-up.**
   - **ready → swap.** Records which files will be replaced, which are new and which will
     be deleted. Moves the current copies to `ota/old/` and puts the new files in place.
   - **swap → trial.** Counts this boot and arms a 120 s one-shot timer that restarts the
     board if the game never reports in.
   - **Soft resets don't count.** `boot.py` runs again on every soft reset too: Ctrl-D,
     and every `mpremote` command, `bench.py` and the web updater, which soft-reset the
     board before they talk to it. Those aren't the update failing, so a soft reset of a
     ship already on trial is neither counted nor given a new deadline (`lvboot.run()`
     returns `"soft"`), and plugging the ship into a computer in the minute after an update
     can't roll a good update back. `machine.reset_cause()` can't tell them apart (a soft
     reset leaves it as it was, `WDT_RESET` after `machine.reset()`), so `lvboot` uses the
     chip's uptime: `boot.py` runs about 25 ms after a real start, and a soft reset over
     USB comes after the board has enumerated (530 ms at the earliest, measured on ship 5),
     so more than `SOFT_MS` (400 ms) means soft. Real starts still count: power-up, the
     deadline and the apply (`machine.reset()`), the watchdog, the RUN pin, a crash that
     resets the chip. The swap itself, and the undo, still run on any reset, so the
     power-cut safety (6.) is unchanged. A soft reset on trial is harmless the other way
     too: `main.py` still calls `good()` 30 s after the game is up.
4. **`main.py`, 30 s after the game is up**, once it has answered a phone with a 2xx or
   (0.2.7, no phone needed) its own check passes, retried every 5 s. The check
   (`serves()`) needs the hotspot up (`ap.active()`) and, when the core can read it back,
   under this ship's own name (`ssid_prefix` + ship number, compared as text; a readback
   that raises or comes back empty is accepted, one naming another ship is not), and the
   server's accept task still running. Then it pushes raw `GET /`, `GET /api/crew`,
   `GET /api/ota` and an unsigned `POST /api/ota/put` through the server's own request
   handler (`web.handle`: the request parser, the busy/`MAX_CONN` accounting and the error
   handling a phone's request goes through). The GETs must answer 2xx and the POST 401
   (the write side still refuses anyone without a crew token; `put` stages nothing, so
   even a broken one changes nothing). Any error the handler says on the way fails it.
   The page streams in chunks and lets other requests in as it goes; only what these
   requests added comes off the hit counts, so a phone's own request in the meantime still
   counts. With the phone game wanted (the hotspot on, `phone_game` true, or "auto" on a
   firmware with a core) but no web server up, the update isn't kept. After `SELF_MS`
   (3 min) of failing checks `main.py` restarts the ship itself, a counted boot (on
   ota-hwfix's `lvboot` a soft-reset trial has no 120 s timer of its own).
   Then it calls `lvota.good()`. That writes `ota/last.json` `{result: "installed"}`,
   removes the state file (lvboot's `.tmp` first) and only then `ota/new` and `ota/old`.
   A power cut before the state file goes: still on trial, every old copy there. After:
   the update is kept and `lvboot` has nothing to do; what's left of `ota/old` is only
   flash in use, cleared when the next update is staged (`put` of the envelope at offset
   0, and `apply()`, both only with no state file). `fault.json` is set aside as
   `fault.last.json` (the new set starts with a clean count; the notes stay readable).
   **A trial that boots dark** ("off", see `board/lvsafe.py`) never reports in, so it is
   rolled back at its 3rd boot, about 4 min after the swap. Off is rare: only a
   `ship.json` with no usable ship number (1-8) on a ship with crew codes and nothing to
   put back. `crew.json` never makes a ship go off (the game says "No code set up"). Any
   `ship.json` that names its ship plays, as 0.2.6 played it (a missing, empty or odd
   hotspot password falls back to `CHANGE_ME`, as in 0.2.6). The reason is in
   `data/fault.json` `"boot"`, which survives the rollback. The old software then plays
   the same file as a fake ship 1 on the default hotspot: fix it over USB with the updater.
5. **Rollback.** If a trial reaches its 2nd boot without reporting in, `lvboot` puts every
   old file back, removes the files the update added and writes `{result: "rolled back"}`.
   Any unexpected error in `lvboot` also rolls back. Boots with `data/maint` or `data/safe`
   present (the bench and safe modes) don't count.
6. **Power cuts.** Every state change is a write to a `.tmp` file, then a rename over the
   old file (littlefs renames atomically). `boot.py` also checks for a leftover
   `state.json.tmp`. The swap and the undo can each be re-run from any point: the tests
   cut the power at 12 points in each and check the board ends up on exactly the old set
   or exactly the new one.
7. **`data/`** is never written or deleted by any of this (`status()` reads `ota_src` from
   `ship.json`, see 2).

The ship's DNS answers `REFUSED` for `github.com` and `githubusercontent.com` (everything
else still points at the ship, which is how the captive portal works). A phone on the
hotspot then gets a fast failure instead of a redirect to the ship. If the phone has
another route, it may try that one; see 5.

## 5. Captive portal: what to expect

Captive portals behave differently on iOS and Android, so the design doesn't depend on
the page reaching GitHub while it's on the ship's Wi-Fi. What it relies on is the page
being opened with internet at some point, the release kept in `localStorage` for
`http://192.168.4.1`, and the install happening the next time you're on the ship.

**iOS, the captive sheet (CNA / "websheet").** This is what opens by itself when you join
`LV-<n>`.
- The ship never answers Apple's probe with "Success", so iOS treats the network as
  captive and the sheet stays up with **Cancel**.
- The sheet's traffic goes over Wi-Fi only, so it can't reach GitHub.
- The sheet's cookies and storage are thrown away when it closes (Wireless Broadband
  Alliance captive-behaviour notes, and long-standing reports). Some older iOS versions
  reportedly crashed on `localStorage` writes; `ota.js` wraps every storage call in
  `try`.
- So in the sheet the check fails quietly, and a release found elsewhere can't be waiting
  there. **The sheet alone can't do over-the-air updates.**

**iOS, Safari.** If you open `http://192.168.4.1` in Safari, its `localStorage` lasts, unless
you go 7 days of using Safari without touching the page; then Safari may clear it. The
home-screen icon keeps its own copy, which isn't capped (section 6).
- While a network counts as captive, iOS reportedly keeps cellular as the main route. So
  Safari may reach GitHub over mobile data while it talks to the ship over Wi-Fi.
  **[NEEDS A REAL PHONE]**
- Even if it can't, a check at home, or anywhere else with internet, keeps the release in
  Safari for `192.168.4.1`, and the next visit to the ship offers it.
- One more thing to test: whether iOS resolves `raw.githubusercontent.com` through the
  ship's DNS (it would get `REFUSED`) or through cellular DNS. **[NEEDS A REAL PHONE]**

**Android, the sign-in notification** (CaptivePortalLogin, a WebView). It's bound to the
Wi-Fi network and its storage is its own, so it behaves like the iOS sheet. **[NEEDS A
REAL PHONE]**

**Android, Chrome.** After "Stay connected" / "Use this network without internet",
Android usually keeps mobile data as the default network and still reaches the hotspot's
own subnet. Then the page can reach both the ship and GitHub, and the notice can appear
during the same visit.
- This varies by maker and version. Samsung's Intelligent Wi-Fi, "Mobile data always
  active" and similar settings all change it.
- Chrome's `localStorage` for `192.168.4.1` lasts.

**[NEEDS A REAL PHONE]**

**The restart.** At the end of an install the ship restarts and its hotspot drops for
about 10–30 s. The iOS sheet closes when the network goes. Safari and Chrome stay open,
and the page polls `/api/ota` for up to 150 s.
- Whether the phone rejoins `LV-<n>` by itself depends on the phone. If it doesn't, the
  page tells you to rejoin and reload. **[NEEDS A REAL PHONE]**
- The restart also forgets who's signed in, so the page says to sign in again.

## 6. On the home screen

You can add the game to your phone's home screen and open it with one tap, like an app.
The icon only works while your phone is on the ship's Wi-Fi, because `192.168.4.1` only
answers there.

**What the ship serves.** `web/build.py` writes these next to the page. `lvweb.STATIC`
streams them from flash like the other `www/*.gz` files, and the mock serves them too.

| Path | File | Type | Size (gzip) |
| --- | --- | --- | --- |
| `/app.webmanifest` | `www/app.webmanifest.gz` | `application/manifest+json` | 274 B (196 B) |
| `/icon.png`, `/apple-touch-icon.png`, `/apple-touch-icon-precomposed.png` | `www/icon.png.gz` | `image/png` | 1737 B (1622 B) |
| `/ls/<W>x<H>.png` (7 sizes) | `www/ls/<W>x<H>.png`, served as they are by `main.py` | `image/png` | 4.4-7.8 KB each, 49651 B in all |

The icon is 192×192 and drawn by `web/icon.py` with no image library: Earth, Mars, the
transfer arc and the ship, on the page's paper colour. The PNG is committed. The page's
`<head>` has these tags:

- `manifest` and `icon`;
- `apple-touch-icon`;
- `apple-mobile-web-app-capable` and `mobile-web-app-capable`;
- `apple-mobile-web-app-title` ("The Long Voyage");
- `apple-mobile-web-app-status-bar-style` (`default`);
- `theme-color`, light and dark;
- seven `apple-touch-startup-image` links (the launch screens, below).

The manifest sets `display: standalone`, `start_url: /?src=icon` (the funnel's Android
marker, below), `scope: /` and the same name. Its
`background_color` is dark (`#1C1B19`), like the launch screens; `theme_color` stays paper.

**The launch screen (an experiment).** Opened away from the ship, the icon can't load
anything: with no service worker over http there is no offline page. What iOS can show is
the web app's launch image, which it keeps with the icon. So the page names one:

- `web/launch.py` draws them: dark (`#1C1B19`), the icon's chart (Earth, the arc, the ship,
  Mars), THE LONG VOYAGE and "Connect to your ship's Wi-Fi to play". No story text. The
  PNGs are committed (`web/launch/`); `web/build.py` writes the links from the same size list.
- iOS uses one only if it is exactly the screen's size, so there is one per current iPhone
  portrait size, each with a `(device-width) and (device-height) and
  (-webkit-device-pixel-ratio) and (orientation:portrait)` media query:

  | File | Points, scale | iPhones |
  | --- | --- | --- |
  | `1320x2868.png` | 440×956 @3 | 16 Pro Max, 17 Pro Max |
  | `1290x2796.png` | 430×932 @3 | 14 Pro Max, 15 Plus / Pro Max, 16 Plus |
  | `1206x2622.png` | 402×874 @3 | 16 Pro, 17, 17 Pro |
  | `1179x2556.png` | 393×852 @3 | 14 Pro, 15, 15 Pro, 16 |
  | `1284x2778.png` | 428×926 @3 | 12/13 Pro Max, 14 Plus |
  | `1170x2532.png` | 390×844 @3 | 12, 13, 14, 16e |
  | `750x1334.png` | 375×667 @2 | SE (2nd/3rd), 6-8 |

  Not covered (they get no launch image, as before): X/XS/11 Pro/12-13 mini (1125×2436),
  XR/11 (828×1792), XS Max/11 Pro Max (1242×2688), iPhone Air (1260×2736), iPads, landscape.
- Cost: 4-colour palette PNGs, 2 bits a pixel, 49651 B of flash for all seven (and of an
  update the first time they ship). The page grows by about 190 B gzip. They are plain
  files under `www/ls/`; `main.py` answers `GET /ls/<digits>x<digits>.png` from flash with
  one 512 B buffer, so they take no RAM until a phone asks, and only Safari asks, when an
  icon is added. Browsers other than iOS Safari ignore the links; nothing else changes.
- **Re-add the icon to see it.** iOS fetches the launch image when you add the icon and
  keeps that copy. An icon added before this change has none: delete it and add it again
  while on the ship's Wi-Fi.
- **It may not show on iOS 26.** iOS has only ever used launch images for pages with
  `apple-mobile-web-app-capable`, and `app.html` leaves that out on iOS 26 (the short
  window, below). On iOS 18 and earlier, where the tag is in, it should work. On iOS 26 it
  needs a real phone: re-add the icon, open it off the Wi-Fi, and check the nav still
  reaches the bottom on the Wi-Fi. If iOS 26 ignores the image, the only way to get it is
  the capable tag, which brings the short window back, so it stays out.
- **After the launch screen, iOS still tries the page.** Off the ship's Wi-Fi that load
  fails, and iOS may replace the launch screen with its own "can't connect" page after a
  few seconds. The launch screen is what you see first, not a lasting offline page.
  **[NEEDS A REAL PHONE]**

**Where Share is on iOS 26.** Safari's tab layout (Settings › Apps › Safari › Tabs)
decides where Share is:

- **Bottom** and **Top** keep a Share button on the toolbar.
- **Compact**, the default, has no Share button. Apple's guide and most write-ups put
  Share under ⋯ beside the address. Phill's iPhone on iOS 26 Compact has no ⋯ at all:
  back, the address pill with the page menu (a box over two lines) at its left, reload,
  tabs.

On that phone the flow is:

1. The page menu: **Share** is the first item, above Add to Bookmarks.
2. The share sheet: the people row; then AirDrop, Messages, Mail, Notes; then round
   buttons Copy, Add to Bookmarks, Add to Reading List and **View More**.
3. **View More** opens a list: Add Bookmark to…, Add to Favorites, Add to Quick Note,
   Find on Page, and **Add to Home Screen** last.

The card's iOS 26 steps follow that exactly, with the page menu, Share and View More
icons inline:

1. Tap [page menu] in the address bar, then **Share** [share]. Share in Safari's
   toolbar? Tap that.
2. Tap **View More** [chevron], then **Add to Home Screen**.
3. Keep **Open as Web App** on, then tap **Add**.

The second sentence of step 1 covers the Bottom and Top layouts. The iOS 26 captive
sheet's step 3 is the same in one line. The phone's screenshots are on the box in
`/workspace/ui-shots/ios-ref/`. The share sheet's people row is blurred in every copy,
and they're never committed.

**The name is "The Long Voyage", not the ship's name.**

- Every ship answers on the same address. So one icon opens whichever ship's Wi-Fi you're
  on, and a ship name on it would be wrong half the time.
- The manifest is a fixed file built once for all ships. `name` and `short_name` are both
  "The Long Voyage" (Phill's choice), as are `apple-mobile-web-app-title` and the page
  `<title>`. On iOS 26 the page title names the icon, because the Apple tags are left
  out there (below).
- At 15 characters it's wider than one line under an iPhone icon. It measures about
  95-100 px in a 12 px system font. "Voice Memos", about the widest name of Apple's own
  that fits, is about 77 px. So expect iOS to cut it to something like "The Long Voy…".
  Android launchers cut it the same way or wrap it to two lines.
- If that's too ugly, "Long Voyage" (11 characters, about 74 px) fits, and you can rename
  the icon in the Add dialog.

**The status bar is `default`, not `black-translucent`.** `black-translucent` draws the
page under the status bar with white status text. That text would be unreadable on the
light paper colour.

**The game stays on http.** The HTTPS study (branch `https-probe`) came out no-go, so
everything below assumes plain `http://192.168.4.1`.

**Full screen on Android.** With no WebAPK, the Android icon opens a Chrome tab. The
Fullscreen API still works over http, from a tap, so `web/fullscreen.js` puts a small
**Full screen** button (four corners, a 44 px target, `aria-label="Full screen"`) in the
top bar just before the gear:

- Only on Android browsers that have the API (`document.fullscreenEnabled` and
  `requestFullscreen`): Chrome and Samsung Internet. Not in the Android sign-in window
  (a WebView), not on iOS (its icon already opens full screen), not on computers.
- A tap calls `document.documentElement.requestFullscreen({navigationUI: "hide"})`. If the
  browser refuses, nothing happens and nothing is logged.
- It hides while the page is full screen (`fullscreenchange`, and `:root:fullscreen` in
  the CSS) and comes back when Back or a swipe leaves full screen.
- Chrome needs a tap every time: full screen ends when the page reloads or the tab is
  reopened. So it's one tap each time you open the game.
- The Android home-screen steps get a third one: "Open the game from the icon, then tap
  [corners] at the top for **full screen**. Back leaves it." The card's lead says "It opens
  in a Chrome tab; one tap makes it full screen".
- The safe areas still hold in full screen: `web/shots_a2hs.mjs` goes full screen with
  Android insets (24 px status bar, 16 px gesture bar) and checks the header clears the
  status bar and the dock reaches the bottom edge with the nav right above the gesture
  bar, on the home and file screens (`a2hs-12`..`14`). At 320 px with a battery figure the
  two icons close up so the bar still fits (`set-10`). **[NEEDS A REAL PHONE]**: the
  gesture bar and cutout insets Chrome really reports in full screen.

**No one-tap install, and nothing to customise when it fails.**

- The page is plain `http://192.168.4.1`, which isn't a secure context. That rules out:
  - a service worker;
  - `beforeinstallprompt`;
  - a WebAPK on Android.
- `web/shots_a2hs.mjs` loads the page as `http://192.168.4.1/` and reads Chrome's
  verdict: the manifest parses with no errors, and the installability errors include
  `not-from-secure-origin`.
- So every platform is a manual "Add to Home Screen". With no service worker, there's
  also no offline page.

**What each phone does** (the card in `web/a2hs.js` words its steps for each one):

| Where you are | What the card says | What the icon does |
| --- | --- | --- |
| iOS Safari (18 and earlier) | Share (bottom; top on iPad) › Add to Home Screen › Add | Opens full screen in its own window (the `apple-mobile-web-app-capable` tag / manifest `display`) |
| iOS 26 Safari | Page menu (box over two lines) in the address bar › Share (or Share on the toolbar) › View More › Add to Home Screen, keep **Open as Web App** on › Add | The same; on iOS 26 every added site is a web app unless you turn that off |
| Chrome / Firefox / Edge on iOS | Share (address bar or menu) › Add to Home Screen | iOS 16.4+ allows this from other browsers. **[NEEDS A REAL PHONE]** |
| iOS captive sheet | Tap **Cancel**, then **Use Without Internet**. Open Safari, go to `192.168.4.1`, then Share › Add to Home Screen | The sheet has no Share button. A link can't leave it either: links only open Safari once iOS marks the network as connected, which needs the probe answered "Success", and the ship never does that (section 5). So the card shows the address in large type to read and type. **[NEEDS A REAL PHONE]**: the Cancel › Use Without Internet wording |
| Android Chrome | ⋮ › Add to Home screen › Add; then, opened from the icon, tap the Full screen button at the top | A plain shortcut that opens a Chrome tab; the top bar's Full screen button (below) hides Chrome's bars. Over http, Chrome can't make a WebAPK. The shortcut may use the page's icon or a letter, depending on the Chrome version. **[NEEDS A REAL PHONE]** |
| Samsung Internet | ☰ › Add page to › Home screen; then the Full screen button | A shortcut; the Full screen button works the same. **[NEEDS A REAL PHONE]** |
| Android sign-in window | Close it (you stay on the Wi-Fi), open Chrome, go to `192.168.4.1`, then ⋮ › Add to Home screen | It's a WebView with no menu |
| A computer, or already opened from the icon | Nothing | Hidden when `navigator.standalone` or `display-mode: standalone/fullscreen/minimal-ui` |

**iOS 26: the icon's window is too short with the manifest in.** Opened from the home
screen on iOS 26, the nav sat about 98 px above the bottom of the screen: 34 px of home
indicator padding (meant), plus 62 px nothing could paint. The page was already right:
`viewport-fit=cover`, the header padded by `env(safe-area-inset-top)`, the dock
`position:fixed; bottom:0` with `env(safe-area-inset-bottom)` padding, `100dvh`.

- The cause is iOS 26 itself. A page with a web app manifest or Apple's
  `apple-mobile-web-app-*` tags opens from the icon on an older code path. Its window is
  the screen's height minus the status bar, but starts at the top of the screen. So the
  status bar's height (47 or 62 px) is missing at the bottom.
- `innerHeight`, `visualViewport` and `getBoundingClientRect` all agree with that short
  window. Script can't see the strip, and CSS can't paint into it.
- A page with none of that markup gets the new path, which is right. iOS 26 opens a home
  screen icon full screen anyway (**Open as Web App**), so the tags aren't needed there.
- So `app.html` adds the manifest and the Apple tags from a small script, and skips them
  on iOS 26+. It tells iOS 26 by a feature, as the user agent can't: Safari 26 says
  `18_6`, and the icon's user agent has no `Version/`. The feature is CSS anchor
  positioning, which arrived in Safari 26. The `apple-touch-icon` link stays, for the
  icon. On iOS 26 the name under the icon defaults to the page title, The Long Voyage,
  which you can edit in the Add dialog.
- `web/shots_a2hs.mjs` checks the tags are there on iOS 18, Android and a computer, and
  left out on iOS 26. It also checks the layout with Chrome's real safe-area emulation
  (`Emulation.setSafeAreaInsetsOverride`), at 390x844 with insets 47/34 and at 402x874
  with insets 62/34. In both: the header clears the status bar; the dock reaches the
  bottom edge with the nav 34 px above it; the action button sits on the nav; the end of
  the page scrolls clear of the dock. Safari tabs and Android Chrome (no insets) keep
  the dock on the bottom edge.
- Shots: `a2hs-10-ios26-icon-before-*-simulated` (the short window drawn on the full
  screen; Chrome can't produce the bug itself) and `a2hs-11-ios26-icon-after-*`.
- An icon added before this change may keep the old window. If the strip stays after an
  update, remove the icon and add it again. Rotating the phone also fixes it until the
  next launch.

**The card.**

- It shows once, on the home screen under the flight-day header, until you tap **Got
  it**. The dismissal is kept as `localStorage` key `lv.a2hs`.
- The captive sheets forget their storage, so there it comes back each time the sheet
  opens. That's the right place to keep explaining.
- It stays out of the way while an update notice is up: one ask at a time.
- **Settings › Home screen icon** (the gear at the top right) shows the same steps any
  time, with where it opens and that it works on the ship's Wi-Fi only.
- The card and the iOS 26 tag script below add about 2.3 KB (gzip) to the page, which is
  then 37466 B of the 128 KB budget (with Settings, docs/SETTINGS.md: 38.9 KB).
  The game firmware's files on flash go from 79738 B to 84196 B.
- `main.py`'s `home_screen()` adds the four routes to `lvweb.STATIC` at start. `lvweb` is
  frozen in the core, so changing it would ship it again as a RAM-loaded `.mpy`. That
  costs about 1.2 KB of heap on the frozen build (sync 36192 → 37424 B, two phones
  50560 → 51744 B), and the cap is 80,000 B.

**You sign in once more.** The ship remembers a phone by its address plus its
User-Agent. An iOS home-screen app sends a different User-Agent from Safari, so the first
launch from the icon asks for your crew code once.

**Storage, and what it means for updates.**

- An iOS home-screen web app has its own storage, separate from Safari's, even for the
  same `http://192.168.4.1`.
  - It is exempt from Safari's 7-day cap on script-writable storage. WebKit: home-screen
    web apps "have their own counter of days of use… We do not expect the first-party in
    such a web application to have its website data deleted."
  - So the release cache (`lv.ota`), the briefing flag and the card's dismissal last
    there.
- Safari's own copy for `192.168.4.1` can be wiped after 7 days of Safari use without
  your touching the page.
- **The cost:** a release found by Safari isn't seen by the icon, and the other way
  round. Each one checks GitHub for itself.
- On Android, the shortcut is just Chrome, so it shares Chrome's storage.

**Can the icon reach GitHub while it's on the ship's hotspot?** It uses the same
networking as Safari, so this is the same open question as section 5. It is reported to
work through mobile data while the Wi-Fi counts as captive, but that hasn't been
measured. **[NEEDS A REAL PHONE]**

**Opened away from the ship.**

- On iOS, the icon opens its window and shows WebKit's own "can't connect to the server"
  page. On Android, Chrome shows its "This site can't be reached" page.
- Neither can be replaced: an offline page needs a service worker, and a service worker
  needs HTTPS.
- Join the ship's Wi-Fi and open the icon again. (On another ship's Wi-Fi, it opens that
  ship's game.)

### The home-screen funnel

Joining the ship's Wi-Fi is everyone's first contact with the game, so the first visit has
one job: put the game on the phone's home screen, smoothly, once. `web/funnel.js` (with
`web/funnel.css`) runs before the game loads (`await fnGate()` in `app.html`'s boot) and
`board/lvfunnel.py` is the ship's memory of which phones have done it.

**What the page shows.** The page asks `GET /api/hello?ctx=<context>[&m=icon]` (4 s timeout,
with the phone's clock headers) and picks one screen:

| Where it runs | The ship has seen this phone open the icon? | Screen |
| --- | --- | --- |
| iOS captive sheet, Android sign-in window | no | **Open the game in Safari / Chrome**: how to leave the pop-up (Cancel › Use Without Internet; close it and stay connected) and the address in large type. No game, no "play here": the pop-up forgets everything when it closes. |
| the same | yes | **Open the game from your icon**, with the address as a fallback. |
| a browser tab (Safari 18/26, Chrome, Samsung Internet, Chrome on iOS) | no | The guide: the intro card (the goal; Wi-Fi, Bluetooth, daily check-ins, the icon), then this browser's steps drawn as SVG/CSS cards in the game's style (iOS 26: page menu › Share; View More › Add to Home Screen; keep Open as Web App on, Add. iOS 18: Share; Add to Home Screen; Add. Android: ⋮ › Add to Home screen; Add), then **Open it from the icon**. "Play in this browser this time" on every card. |
| the same | yes | **You have the icon**: Play here anyway, or "No icon on this phone? Show me how to add it" (the guide). |
| the icon itself, a computer, or "play here" this tab | — | the game |

The captive pop-up is never told "internet OK": the ship still answers the OS's checks
with the redirect (section 5), so the pop-up only routes the player to the real browser.
The cards use no screenshots; they are drawings of the browser's UI, named in its words.
The guide's step cards also suppress the old home-screen card (`web/a2hs.js`) for that tab.

**What marks a phone installed.** Only an icon launch:

- iOS: the page runs standalone (`navigator.standalone`, or `display-mode: standalone`).
- Android: the shortcut is just Chrome opening the address it was added from, so while the
  guide shows the address carries `?src=icon` (`history.replaceState`, other parameters and
  the hash kept), and the manifest's `start_url` has it too. A marked load counts only as a
  new navigation (not a reload or back/forward) in a tab that never showed the guide
  (`sessionStorage` `lv.fnadd`); the page then takes the marker off and remembers the
  launch for the tab and, as a hint, in `localStorage`.

iOS doesn't use a marker: a restored Safari tab would replay it and count as a launch.
If the page sees the icon appear while the guide is up (it comes back to the foreground),
it asks again and switches to **You have the icon**.

**The ship's memory.** `/data/funnel.bin`: 32 records of 8 bytes (256 B), key (`ip` + the
IPv4 address, or a MAC), flags (installed, tab, sheet, MAC) and a stamp (4-hour units of the
phone-taught clock, mod 256). Phones are told apart by client address for now. The hotspot
leases an address for 24 hours, so an address record is trusted for at most that long
(after it, another phone may hold the address). The hook for MAC mode is `lvfunnel.mac_of`:
firmware that lists its DHCP leases (`ap.status("leases")`, not stock MicroPython 1.29) keys
phones by MAC, and those records don't go stale (iOS and Android keep one private MAC per
network). A full store gives the stalest record that isn't installed to a new phone. The
file is written whole (`.new`, then a rename) and only when a record changes. **Reset this
ship** deletes it (`main.py` `RESET`).

`main.py`'s `ota_route` answers `/api/hello`, importing `lvfunnel` per request and dropping
it after (as `lvota`), so it holds no RAM between requests. It is not frozen: on lv-core
0.2.0 it ships over the air as `lvfunnel.mpy`, and it is in `gen_lvfrozen.py` `BOARD` and
`manifest.py` for the next core. Page cost: 5.3 KB gzip (the page went from 39.6 to 44.9 KB
gzip, 34% of the 128 KB budget). Heap: within the noise of the `--ota` run (board peak 70.5-71.5 KB of
the 80,000 B cap with it, 71.2 KB without).

**[NEEDS A REAL PHONE]**: whether an iPhone keeps one address across sheet, Safari and
icon (private Wi-Fi address on); the Android shortcut's URL (does it keep `?src=icon`, or
use the manifest's `start_url`?); the pop-ups' wording (Cancel › Use Without Internet, the
Android sign-in window's close and "stay connected"); the iOS 26 Add to Home Screen sheet's
labels; the foreground re-check; MAC mode needs firmware with a lease list.

## 7. Tests

Automated (all in `game/tests/run.sh`):

- **`tests/test_ota.py`** (CPython, the unix port, and the frozen-core build). Covers:
  - refusals: tampered, wrong key, unknown key, wrong core, older or same version, bad
    paths, deleting `data/`, too big;
  - wrong offsets and resuming;
  - a tampered file;
  - apply → swap → trial → good;
  - a replay refused;
  - a rollback after 2 boots, and `maint` boots not counted;
  - the 120 s deadline;
  - power cuts at 12 points in the swap and 12 in the rollback;
  - a broken state file;
  - `boot.py` itself;
  - `main.py`'s hooks, including DNS `REFUSED`;
  - HTTP 200/401/404/409;
  - `data/` left untouched.
- **`tests/test_ota_release.py`.** Covers:
  - `sign_release.py` with a test key, its output never showing the key;
  - `boot.py` and `lvboot` left out;
  - the ship's `lvsig` accepting the result;
  - `validate_firmware.py` passing it and refusing a tampered manifest, a bad signature,
    an untrusted key, and a file changed after signing;
  - refusing to sign a release that ships `data/`, or with a key the ships don't trust.
- **`tests/phone_heap.py ... --ota`.** A third phone uploads a signed update over real
  HTTP to the frozen build during the heap test: sign-in, 401 signed out, a tampered
  envelope (403), a wrong offset (409), every file, then cancel. The peak has to stay
  under 80000 B.
- **`web/shots_ota.sh`.** Desktop Chrome against the mock ship (`sim/mockota.py`) and a
  stand-in GitHub, clicking through:
  - the notice and Later;
  - the gear's update dot, and no Ship software row on the crew page;
  - Settings' Ship software section, and the notice's Install opening Settings;
  - an install with progress;
  - "installed" after the restart;
  - an update that went back;
  - a check with no internet.

  It saves the screenshots too.
- **`web/shots_a2hs.sh`.** Chrome with each phone browser's User-Agent, loading the page as
  `http://192.168.4.1/` (requests handed to the mock). It checks:
  - the card and its steps for iOS Safari 18 and 26, the iOS captive sheet, Android
    Chrome, Android's sign-in window and Samsung Internet;
  - that **Got it** hides the card and it stays hidden after a reload;
  - the steps in Settings (from the gear), and no row on the crew page;
  - that nothing shows on a computer or once opened from the icon (`navigator.standalone`
    and `display-mode: standalone`);
  - that Chrome parses the manifest and refuses to install from a non-secure origin.
- **`tests/test_funnel.py`** (CPython, the unix port, and the frozen-core build).
  `board/lvfunnel.py`: address mode and its 24 h trust, MAC mode, a full store and who is
  evicted, writes only on a change and a damaged file; `main.py`'s `/api/hello` hook (the
  clock learned, the module dropped, MAC mode from `web.ap`).
- **`web/shots_funnel.sh`.** Chrome with phone User-Agents against the board's own server
  (`tests/phone_serve.py`), loaded as `http://192.168.4.1/`, at 390x844, 320x640 (iOS) and
  412x915 (Android). It checks each screen and the order of events: the captive sheet and
  sign-in window route to the browser; a first tab shows the guide; an icon launch (iOS
  standalone, Android `?src=icon`) marks the phone and plays; the next tab says **You have
  the icon**; a reload or the guide's own tab doesn't count; Reset this ship forgets the
  phone. It saves the screenshots too.
- **`tests/phone_flow.py`** (`phone_check`, `phone_heap`) fetches `/app.webmanifest`,
  `/icon.png` and `/apple-touch-icon.png` from the real `lvweb` and checks the bytes, the
  gzip encoding and the content type. **`tests/app_e2e.mjs`** checks the manifest's
  fields, the icon's size and the `<head>` tags. It plays as iOS 26 Safari, so it starts on
  the guide, and ends with the funnel: an icon launch marks the phone, the next tab shows
  **You have the icon**, the captive sheet sends it to the icon, Reset this ship forgets it,
  and an Android launch from `?src=icon`.

Still to do on real hardware and phones:

1. A real ship: verify time and peak heap on the RP2040 during an upload; a full install
   and a rollback (a `main.py` that never calls `good()`); a power cut during the swap.
2. An iPhone in the captive sheet: confirm the check fails quietly and nothing is kept.
3. An iPhone in Safari on `http://192.168.4.1`, with mobile data on: does the check reach
   GitHub while on the hotspot?
4. An iPhone in Safari: check at home, then join the ship. Does the notice appear, and does
   the install finish? Does Safari rejoin after the restart?
5. Android Chrome after "Stay connected", with mobile data on: same as 3 and 4. Repeat on a
   Samsung phone.
6. Android's sign-in notification view: same as 2.
7. Home screen on an iPhone (Safari, iOS 18 and 26):
   - On iOS 26, opened from the icon: does the nav sit on the home indicator, with no strip
     below it? Check with an icon added after this change, and with one added before.
   - On iOS 26, try each tab layout (Settings › Apps › Safari › Tabs: Compact, Bottom,
     Top) and check the card's first step finds Share in each.
   - Add the game: check the icon, the name "The Long Voyage" (and how it's cut), and
     that it opens full screen with the status bar readable.
   - Sign in once, close it, then reopen it the next day: are you still signed in, and is
     the briefing flag kept?
   - With mobile data on, does **Check for updates** from the icon reach GitHub while
     you're on the hotspot?
   - Away from the ship: what does the icon show?
8. The iOS captive sheet: does **Cancel** offer **Use Without Internet** and keep the
   Wi-Fi? Does Safari then load `192.168.4.1`?
9. Android Chrome (and a Samsung phone):
   - **Add to Home screen**: which icon and name does the shortcut get? Does it open a
     Chrome tab?
   - Close the sign-in window: does the phone stay on the Wi-Fi?
10. Chrome on iOS: does Share › Add to Home Screen show up, and open as a web app?
11. The home-screen funnel (see "The home-screen funnel" above): one iPhone and one
    Android phone through sheet › browser › guide › icon; then a second phone on the same
    ship; then the next day.

## 8. Releasing an update

```
python3 tools/build_release.py ...                        # as before
python3 game/tools/ota/sign_release.py firmware/releases/<version>/release.json
python3 tools/validate_firmware.py                        # checks the signature like a ship
```

`sign_release.py` reads the key from `--key`, `$LV_OTA_KEY` or
`~/.secrets/lv_ota_signing_key`, and never prints it. A release that isn't signed simply
isn't offered over the air, and USB installs work as before.
