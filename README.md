# The Long Voyage · Ship Software Service

A static web page that loads, configures and debriefs Long Voyage ships (Raspberry Pi
Pico W / Pico 2 W running MicroPython) straight from the browser over USB, using Web Serial.

Public URL: `https://your-server.example` (the hostname and the container name are
unchanged from the Mars Habitat days; see [Deploy](#deploy)).

Works in desktop Chrome, Edge, Brave or Chromium, over https or on localhost. Firefox
and Safari have no Web Serial.

## What it does

| Section | What it is for |
| --- | --- |
| 1 Ship on the bench | Board, MicroPython version, free flash, installed release and ship identity. |
| 2 Software load | Pick a release from `firmware/index.json` and install it. Every file is checked by sha256 in the browser before anything is written, and again on the board after. `data/` and the bench logs are always kept. A board holding another project's files is offered a clean install. |
| 3 MicroPython runtime | Checks the board's MicroPython against the release, links the tested `.uf2` on micropython.org with its sha256, and can restart the board into BOOTSEL. |
| 4 Ship configuration | Writes `data/ship.json`: ship number and name, bench role, hotspot password. WPA2 by default; open only when asked for explicitly. Shows the hotspot the role gives (A → `COEX-0`, B → `COEX-1`, none → `COEX-0`). Remembers, in this browser, which board (by `machine.unique_id()`) got which role, preselects the other role for the next board, defaults its ship number to match (A → 1, B → 2), and warns before two boards share a hotspot. |
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

- The builder refuses to package `secrets.py`, `secrets.json`, `ship.json` or `device.json`.
- `data/` and every `--log` file are preserved on install.
- `--build-time` makes a rebuild byte-for-byte reproducible.
- Channels are `stable`, `beta` and `bench`. `latest` follows the newest build unless
  `--no-latest` is given.

To move to a newer MicroPython, update `firmware/runtime.json`: URL, size and sha256 from
micropython.org. Then run `python3 tools/validate_firmware.py --online` to download both
`.uf2` files and check them.

## Tests

```bash
sh tests/run.sh            # node --check, 6 unit + 11 integration checks, validator
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

Portainer stack `<PORTAINER_STACK>` (`marshab-updater`) on <DOCKER_HOST> builds this repo's `main` with
`docker-compose.yml`.

1. Merge to `main`.
2. In Portainer, open stack <PORTAINER_STACK> and choose **Pull and redeploy**. Keep "re-pull image"
   on. The stack also has a GitHub push webhook with force-update set, so a push may
   already have triggered this.
3. Open https://your-server.example and hard-reload. The title should read
   "The Long Voyage". `/firmware/index.json` should list the current release.

Networking:
- Nginx Proxy Manager forwards the public hostname to `http://marshab-updater:80` over
  the external docker network `Shared`.
- The host port is bound to `127.0.0.1:<HOST_PORT>` only, so http on the LAN is closed.
- Do not rename the service or container without updating the NPM proxy host.

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

Then, in Portainer, either set stack <PORTAINER_STACK>'s repository reference to `refs/heads/marshab`
and **Pull and redeploy**, or merge `marshab` into `main` and redeploy.

To get back here afterwards, set the reference to `refs/heads/main` again.

Notes:
- The old compose file publishes `<HOST_PORT>:80` on all interfaces.
- The old nginx config has an open `/github-api/` proxy.
- Some old releases ship a `secrets.py`; treat whatever it contains as public.
