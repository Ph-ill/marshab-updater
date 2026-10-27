# The Long Voyage · Ship Software Service

A static web page that loads, configures and debriefs Long Voyage ships (Raspberry Pi
Pico W / Pico 2 W running MicroPython) straight from the browser over USB, using Web Serial.

Served from your own Docker host behind a reverse proxy, written here as
`https://your-server.example`. The service and container are still called
`marshab-updater` from the Mars Habitat days; see [Deploy](#deploy).

Works in desktop Chrome, Edge, Brave or Chromium, over https or on localhost. Firefox
and Safari have no Web Serial.

## What it does

| Section | What it is for |
| --- | --- |
| 1 Ship on the bench | Board, MicroPython version, free flash, installed release and ship identity. |
| 2 Software load | Pick a release from `firmware/index.json` and install it. Every file is checked by sha256 in the browser before anything is written, and again on the board after. `data/` and the bench logs are always kept. A board holding another project's files is offered a clean install. |
| 3 MicroPython runtime | Checks the board's MicroPython against the release, links the tested `.uf2` on micropython.org with its sha256, and can restart the board into BOOTSEL. |
| 4 Ship configuration | Writes `data/ship.json`: ship number and name, bench role, hotspot password. WPA2 by default; open only when asked for explicitly. Shows the hotspot the role gives (A → `COEX-0`, B → `COEX-1`, none → `COEX-0`). Remembers, in this browser, which board (by `machine.unique_id()`) got which role, preselects the other role for the next board, defaults its ship number to match (A → 1, B → 2), and warns before two boards share a hotspot. Below that, **Crew codes**: one 4-digit sign-in code per crew member for The Long Voyage, written to `data/crew.json` as salted sha256 hashes (`src/crew-codes.js`, read on the board by `game/lv/codes.py`). Blank means "not set up". This browser keeps the plain codes and the fleet salt, so every ship gets the same set; "Fill blanks at random", "Copy list" and "Forget codes" do what they say. |
| 5 Bench logs | Lists and downloads the release's log files, named after the ship and time. |
| 6 Operations log, 7 Recovery | What happened, and what to do when it goes wrong. |

Connecting pauses the ship software. If the firmware's hardware watchdog is running, the
page stops it, or restarts the board in maintenance mode via the one-shot `data/maint` flag.
**Disconnect restarts the ship** (`machine.reset()`), so it is never left stopped at a prompt.

## Layout

```text
index.html, styles.css, favicon.svg   the page (Flight Data File look: paper, ink, one rust accent)
src/                                  ES modules: serial link, installer, ship config, logs, runtime
firmware/index.json                   release list (static, written by tools/build_release.py)
firmware/releases/<ver>/release.json  one self-contained release: files as base64 + size + sha256
firmware/runtime.json                 tested MicroPython build: micropython.org URLs, size, sha256
tools/build_release.py                package a MicroPython source folder as a release
tools/validate_firmware.py            check index, releases, runtime list and the served tree
tests/                                unit, simulated-board integration, headless page check
newgame/                              Mars Habitat game rewrite source; not served
```

Only `index.html`, `styles.css`, `favicon.svg`, `src/` and `firmware/` go into the image.

## Publishing a release

```bash
python3 tools/build_release.py --version 0.0.2-coex --channel bench \
  --label "Wi-Fi + BLE coexistence bench test" \
  --source game/bench/coex-test \
  --log coex_log.csv --log coex_log.old --log coex_boot.txt --roles A,B \
  --notes "What changed and what to look for." \
  --mpy-cross "$(command -v mpy-cross)"
sh tests/run.sh            # must pass
git add firmware && git commit -m "firmware: package Long Voyage 0.0.2-coex" && git push
```

- The builder refuses to package `secrets.py`, `secrets.json`, `ship.json`, `crew.json` or `device.json`.
- `data/` and every `--log` file are preserved on install.
- `--build-time` makes a rebuild byte-for-byte reproducible.
- Channels are `stable`, `beta`, `bench` and `test`. `latest` is the `stable` release if
  there is one, else the newest build outside `test`, unless `--no-latest` is given.
- A `test` build is listed as **[TEST BUILD]** for a hand-picked install only: it is never
  `latest`, so "Install latest" and the update notice skip it (the page enforces that even
  if an index says otherwise), and installing it asks first. Nothing installs on its own.
- `--hotspot-prefix LV-` tells the page the release's hotspot name (prefix + ship number).
- The Long Voyage test build is a **partial release for the game firmware**. Build the
  `.uf2` and the board files from `game/` first (`sh tools/build_firmware.sh`, then
  `MPY_CROSS=... sh tools/board_build.sh`), then from the repository root:

  ```bash
  python3 tools/build_release.py --version 0.2.0-lv-test --channel test \
    --label "Long Voyage test: the phone game on the board, BLE sync (game firmware 0.2.0)" \
    --source game/build/board-fw \
    --frozen game/tools/fw/cores/lv-core-0.2.0-<core>.json --hotspot-prefix LV- \
    --delete config.py --delete index.html --notes "..." --mpy-cross "$(command -v mpy-cross)"
  ```

  lv-core 0.2.0 freezes the board modules and the story pack too, so `0.2.0-lv-test` ships
  only `main.py`, `engage.bin` and the phone page. For such a core the builder adds every
  file copy of a frozen board module (`<module>.py`, `<module>.mpy`) and `pack.bin` that
  the release doesn't ship to `delete` (a file is found before the frozen module, so a 0.1.0
  install's leftovers would run instead), and lists the ones it does ship, hotfixes built
  by `board_build.sh` when a board module or the pack changed since the core, in
  `"replaces"`. The page removes those stale copies too, even for a release that doesn't
  list them. Boards still on lv-core 0.1.0 keep `0.1.0-lv-test`.

  `--frozen` names the frozen core the release runs on (`tools/fw/cores/` keeps one
  manifest per core). The release then has no `lv/` files; `lvx/<module>.mpy` overrides
  are allowed only for modules that core has, and are listed in `"overrides"`;
  `lv` and `lvx` are added to `delete` so a stale `/lv` or an old override can't win.
  `tools/validate_firmware.py` checks all of that, and the page reads the board's frozen
  core and refuses a release built for another one (or for stock MicroPython) before
  writing anything. `game/tools/board_build.sh` works out the overrides by itself: only
  core modules changed since that manifest go into `build/board-fw/lvx/`.

  The updater writes files over USB only; the `.uf2` game firmware
  (`game/tools/build_firmware.sh`) is flashed by hand (BOOTSEL), see `game/docs/BENCH_TEST.md`.

- **Over the air.** A ship that has had one USB install with `boot.py`, `lvboot`, `lvota`
  and `lvsig` can also update from a phone. Sign the release
  (`game/tools/ota/sign_release.py firmware/releases/<version>/release.json`; the key stays
  outside the repo). Once it's pushed to `main`, the game page on any phone that reaches the
  internet picks it up from `raw.githubusercontent.com` and offers it on the ship's Wi-Fi.
  The ship checks the Ed25519 signature and every file, switches over at restart and rolls
  back if the new version doesn't start. `data/` is never touched. See `game/docs/OTA.md`.
- **On the home screen.** The phone page has a web app manifest, an Apple touch icon
  (192 px, 1.6 KB from flash) and a one-time card that shows how to add the game to your
  home screen in the browser you're using. iOS Safari opens it full screen. Android Chrome
  makes a shortcut to a Chrome tab. It only works on the ship's Wi-Fi, because the page is
  plain http, so there is no one-tap install and no offline page. See section 6 of
  `game/docs/OTA.md`.

To move to a newer MicroPython, update `firmware/runtime.json`: URL, size and sha256 from
micropython.org. Then run `python3 tools/validate_firmware.py --online` to download both
`.uf2` files and check them.

## Tests

```bash
sh tests/run.sh            # node --check, 8 unit + 12 integration checks, validator
sh tests/run.sh --online   # also verifies the micropython.org .uf2 sha256 values
```

The integration test runs the real installer against `tests/sim-device.mjs`, a fake board
that executes each raw-REPL snippet in CPython inside a temp directory.

To check the page itself, serve it with the repo's nginx config on localhost, then run the
headless Chrome check. It fails on console errors, exceptions or HTTP errors, and writes a
screenshot.

```bash
node --experimental-websocket tests/page-check.mjs http://localhost:8199/ page-check.png
```

Local preview without nginx: `python3 -m http.server 8140`, then open http://localhost:8140.

## Deploy

Any Docker host works; the repo assumes a reverse proxy in front and a git-backed compose
stack (Portainer, or plain `docker compose`). Nothing about a particular server is kept in
the repo. Names used below are placeholders:

| Placeholder | Meaning |
| --- | --- |
| `https://your-server.example` | the public address your reverse proxy serves the page on |
| `<DOCKER_HOST>` | the machine that runs the container |
| `<PORTAINER_STACK>` | the Portainer stack that builds this repo, if you use Portainer |

Local settings live in an untracked `.env` file next to `docker-compose.yml` (or in the
stack's environment variables in Portainer). Start from the example:

```bash
cp .env.example .env    # .env is in .gitignore; never commit it
```

`MARSHAB_HOST_PORT` is the loopback port published on `<DOCKER_HOST>` (see `.env.example`
for the default).

1. Merge to `main`.
2. Redeploy: `docker compose up -d --build` on `<DOCKER_HOST>`, or in Portainer open
   `<PORTAINER_STACK>` and choose **Pull and redeploy** with "re-pull image" on. If the
   stack has a GitHub push webhook with force-update, a push may already have done this.
3. Open `https://your-server.example` and hard-reload. The title should read
   "The Long Voyage". `/firmware/index.json` should list the current release.

Networking:
- The reverse proxy (for example Nginx Proxy Manager) forwards the public hostname to
  `http://marshab-updater:80` over the external docker network `Shared`.
- The host port is bound to `127.0.0.1` only, so plain http on the LAN is closed.
- Do not rename the service or container without updating the proxy host.

## Going back to Mars Habitat

The last Mars Habitat version of this updater is preserved, unchanged, under the annotated
tag **`marshab-final`**. It is commit `3a61c6f`, the build deployed until the Long Voyage
switch. It contains:
- all MarsHab firmware releases 0.1.1 to 0.3.16;
- `firmware/manifest.json`, `firmware-assets/`, `archive/` and `tools/make_release_asset.py`;
- the Wi-Fi panel and the GitHub Releases flow.

To read it:

```bash
git fetch --tags origin
git show marshab-final              # tag message with these steps
git checkout marshab-final          # browse it (detached HEAD)
```

To deploy it again:

```bash
git fetch --tags origin
git checkout -b marshab marshab-final
# the old page fetched release assets from .../main/firmware-assets/, which no longer
# exists on main; point it at the tag instead
sed -i 's#/main/firmware-assets/#/marshab-final/firmware-assets/#' src/github-releases.js
git commit -am "restore: Mars Habitat updater from marshab-final"
git push origin marshab
```

Then, in Portainer, either set `<PORTAINER_STACK>`'s repository reference to `refs/heads/marshab`
and **Pull and redeploy**, or merge `marshab` into `main` and redeploy.

To get back here afterwards, set the reference to `refs/heads/main` again.

Notes:
- The old compose file publishes the host port on all interfaces, not just loopback.
- The old nginx config has an open `/github-api/` proxy.
- Some old releases ship a `secrets.py`; treat whatever it contains as public.
