# Over-the-air updates

A ship can update its game software from a phone, without a USB cable or a file you
download yourself. The phone looks for a newer signed release on GitHub whenever it can
reach the internet. It keeps the release, and when it's on the ship's Wi-Fi it offers
to install it: a notice on the home screen (**Install** / **Later**), and
**Settings › Ship software** (the gear at the top right; docs/SETTINGS.md), which shows what's installed, what's available, when it last
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

## 4. On the ship

`/api/ota` (GET, open to anyone on the hotspot) returns
`{ota, v, ch, core, chunk, free, last, phase, staged}`. Every POST needs a signed-in crew
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
4. **`main.py`, 30 s after the game is up.** Calls `lvota.good()`. That writes
   `ota/last.json` `{result: "installed"}` and removes `ota/old` and the state.
5. **Rollback.** If a trial reaches its 2nd boot without reporting in, `lvboot` puts every
   old file back, removes the files the update added and writes `{result: "rolled back"}`.
   Any unexpected error in `lvboot` also rolls back. Boots with `data/maint` or `data/safe`
   present (the bench and safe modes) don't count.
6. **Power cuts.** Every state change is a write to a `.tmp` file, then a rename over the
   old file (littlefs renames atomically). `boot.py` also checks for a leftover
   `state.json.tmp`. The swap and the undo can each be re-run from any point: the tests
   cut the power at 12 points in each and check the board ends up on exactly the old set
   or exactly the new one.
7. **`data/`** is never read, written or deleted by any of this.

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

The icon is 192×192 and drawn by `web/icon.py` with no image library: Earth, Mars, the
transfer arc and the ship, on the page's paper colour. The PNG is committed. The page's
`<head>` has these tags:

- `manifest` and `icon`;
- `apple-touch-icon`;
- `apple-mobile-web-app-capable` and `mobile-web-app-capable`;
- `apple-mobile-web-app-title` ("The Long Voyage");
- `apple-mobile-web-app-status-bar-style` (`default`);
- `theme-color`, light and dark.

The manifest sets `display: standalone`, `start_url: /`, `scope: /` and the same name.

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
| Android Chrome | ⋮ › Add to Home screen › Add | A plain shortcut that opens a Chrome tab, not full screen. Over http, Chrome can't make a WebAPK. The shortcut may use the page's icon or a letter, depending on the Chrome version. **[NEEDS A REAL PHONE]** |
| Samsung Internet | ☰ › Add page to › Home screen | A shortcut. **[NEEDS A REAL PHONE]** |
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
- **`tests/phone_flow.py`** (`phone_check`, `phone_heap`) fetches `/app.webmanifest`,
  `/icon.png` and `/apple-touch-icon.png` from the real `lvweb` and checks the bytes, the
  gzip encoding and the content type. **`tests/app_e2e.mjs`** checks the manifest's
  fields, the icon's size and the `<head>` tags.

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

## 8. Releasing an update

```
python3 tools/build_release.py ...                        # as before
python3 game/tools/ota/sign_release.py firmware/releases/<version>/release.json
python3 tools/validate_firmware.py                        # checks the signature like a ship
```

`sign_release.py` reads the key from `--key`, `$LV_OTA_KEY` or
`~/.secrets/lv_ota_signing_key`, and never prints it. A release that isn't signed simply
isn't offered over the air, and USB installs work as before.
