# Over-the-air updates

A ship can update its game software from a phone, without a USB cable or a file you
download yourself. The phone looks for a newer signed release on GitHub whenever it can
reach the internet. It keeps the release, and when it's on the ship's Wi-Fi it offers
to install it: a notice on the home screen (**Install** / **Later**), and
**CREW › Ship software**, which shows what's installed, what's available, when it last
checked, and a **Check for updates** button. Installing sends the release to the ship
in small pieces. The ship checks the signature and every file, switches over at
restart, and goes back by itself if the new version doesn't start.

Your settings and the game (`data/`) are never touched.

Anything marked **[NEEDS A REAL PHONE]** has only been reasoned about or tried in desktop
Chrome. Section 6 lists the tests still to do.

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

**iOS, Safari.** If you open `http://192.168.4.1` in Safari, its `localStorage` lasts.
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

## 6. Tests

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
  - the Ship software row on your crew page;
  - the Ship software screen;
  - an install with progress;
  - "installed" after the restart;
  - an update that went back;
  - a check with no internet.

  It saves the screenshots too.

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

## 7. Releasing an update

```
python3 tools/build_release.py ...                        # as before
python3 game/tools/ota/sign_release.py firmware/releases/<version>/release.json
python3 tools/validate_firmware.py                        # checks the signature like a ship
```

`sign_release.py` reads the key from `--key`, `$LV_OTA_KEY` or
`~/.secrets/lv_ota_signing_key`, and never prints it. A release that isn't signed simply
isn't offered over the air, and USB installs work as before.
