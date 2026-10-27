# Bench test: BLE ship-to-ship sync on 2–3 Pico W boards

What this checks, on real hardware, that the tests can only fake: the radio. Boards
advertise, find each other, connect, swap the records the other is missing over one GATT
characteristic and disconnect, while each keeps its Wi-Fi hotspot up. Allow about an
hour for three boards.

Placeholders are in `<ANGLE BRACKETS>`; fill them in for your own bench. Nothing here
needs a server: the boards only talk to each other and to a phone or laptop on their hotspot.

## Fast path: one command per board (`tools/bench.py`)

For the game firmware (lv-core 0.2.0) and the 0.2.0-lv-test build, one command per board does sections 9,
4 and 5's basics and prints a report. On the computer, once: `pip install mpremote`. Then,
from the repo, with **one** board plugged in:

```sh
export LV_HOTSPOT_PASSWORD='<HOTSPOT_PASSWORD>'        # optional; keeps it out of the command line
python3 game/tools/bench.py --ship 1 --launch <LAUNCH_DATE> --led on --led-test --code Phill=<CODE>
```

It:

1. finds the Pico W on USB (or `--port <PORT>`) and checks it runs the game firmware
   `lv-core 0.2.0`, core `2661c2144844`. Stock MicroPython or another core (a board still
   on lv-core 0.1.0 included): **FAIL**, naming `lv-core-0.2.0-2661c2144844-RPI_PICO_W.uf2`
   to flash first (BOOTSEL, drag it on the `RPI-RP2` drive; or add `--uf2 <PATH>` and it
   does that);
2. installs 0.2.0-lv-test (the updater page's files and deletes; files already right are
   skipped) and checks every file's sha256 on the board. It also removes the copies of the
   now-frozen modules a 0.1.0 install left (`lvship.mpy` … `selftest.mpy`, `pack.bin`):
   a file is found before a frozen module, so they would run instead of the firmware's;
3. writes only the settings given into `/data/ship.json` (`--ship`, `--launch` or `--day`,
   `--led on|off`, `--password`/`LV_HOTSPOT_PASSWORD`; everything else in the file stays) and
   the crew codes given into `/data/crew.json` (`--code Name=1234`, repeatable, or `--codes`
   with all 8 in roster order; the others keep theirs);
4. runs the self-test for 60 s (`--seconds`) with the hotspot, the phone server, the captive
   DNS and BLE up, and this computer's time given to the board as a phone would;
5. with `--led-test`, plays 3 slow breaths (the LED fading up and back down 3 times, about
   7 s) and asks whether you saw it pulse (section 12 for seeing the LED through the case);
6. prints the report and saves it with the whole console to `game/build/bench-logs/`
   (codes and the password are never printed or logged), then resets the board into the game.

```
REPORT ship 1 (2026-10-23 20:15 CDT)
firmware/core           PASS  lv-core 0.2.0 core 2661c2144844
files hash-match        PASS  6 files, sha256 as in 0.2.0-lv-test
no stale frozen copies  PASS  none of the 12 frozen board modules or pack.bin left as files
settings saved          PASS  set launch_date, led_notify, ship_id; kept the rest
crew codes              PASS  written; set for Phill
selftest ran            PASS  CHECK (see docs/BENCH_TEST.md)
heap used < 80 KB       PASS  peak … B of 80000
BLE up                  PASS  advertising and scanning
Wi-Fi hotspot up        PASS  hotspot LV-1 active True, ip 192.168.4.1
phone server listening  PASS  phone game listening on port 80
captive DNS up          PASS  every name -> 192.168.4.1 on port 53
flight day              PASS  day=9/phone (expected day=9/phone)
LED path                PASS  notifier ON, waiting …
LED pulse test          PASS  you saw the 3 slow breaths (fading up and down)
peers                   INFO  none
OVERALL PASS
```

`selftest ran … CHECK` with one board is normal (no peer to sync with); `peers` is only a
check with `--peers`. Exit code 0 = all PASS, 1 = something failed: send the log file.

- **Several boards**: `--ships 1,2,3` (same flags), plugging each in when asked; or one
  terminal per board with `--port`. For the sync checks (section 5, 2–4) run two boards'
  self-tests at once with `--peers --seconds 180`.
- **Rollover in two minutes** (section 11): `--rollover 9` sets a launch date and a
  `day_start` a minute or two ahead so FD 8 becomes FD 9 during the self-test, checks the
  STAT lines, and puts your launch date back.
- **Manual day**: `--day 12` instead of `--launch` (clears the launch date).
- `--dry-run` shows what it would do; `--no-install`, `--no-selftest`, `--no-reset`,
  `--quiet`, `--no-clock`. `python3 game/tools/bench.py --help` lists them all.

What it can't see: whether the LED pulsed (it asks you), a phone joining the hotspot and
the captive sheet opening (section 10), range. The manual steps below are unchanged.

### A board that hangs, or a sealed board you need back at the REPL

- Before the self-test, bench.py **hard-resets** the board into the REPL (`machine.reset()`
  with `/data/maint`, so the game doesn't start), so the CYW43 radio chip starts clean.
  mpremote's own soft reset leaves the radio chip as the previous program left it, and on
  2026-10-25 one board (ship 2, which had an older project on it) never came back from
  switching Bluetooth on after one: `bluetooth.BLE().active(True)` waited forever, so
  `Ship(...)` never returned. A hard reset cleared it at once (BLE up in under a second).
  `--no-fresh-boot` skips the reset.
- Every mpremote call has a real deadline. A board that stops answering is cut off and
  reported as `selftest ran FAIL TIMEOUT ...`: unplug it, plug it back in (a power cycle
  restarts the radio chip too) and run bench.py again for that ship.
- **Getting a sealed board (no BOOTSEL) to the REPL**: `main.py` waits 2 s after power-up
  before it touches the radio. Plug the board in and within those 2 s run
  `mpremote connect <PORT> exec "print('stopped')"` (any mpremote command sends Ctrl-C);
  Ctrl-C also stops the game at any later point in its Python code. An empty
  `/data/maint` skips the game once (`mpremote connect <PORT> touch :/data/maint`, then
  reset); an empty `/data/safe` skips it on every boot until you remove it
  (`mpremote connect <PORT> rm :/data/safe`). `mpremote connect <PORT> bootloader` reaches
  BOOTSEL (the RPI-RP2 drive) without the button.
- If mpremote says the port is "in use by another program", close whatever else has it
  open (another mpremote, a serial monitor, Thonny, ModemManager) before blaming the board.

## 0. What you need

- 2 or 3 Raspberry Pi Pico W (or Pico 2 W) boards and USB data cables.
- MicroPython **1.29** firmware for the board (`RPI_PICO_W` / `RPI_PICO2_W` `.uf2` from
  micropython.org). The `.mpy` files are built for 1.29's bytecode version; a different
  major version refuses to import them (`ValueError: incompatible .mpy file`).
- On the computer: Python 3, `pip install mpremote mpy-cross==1.29.0`, and this repo.
- Optional: a phone to join a board's hotspot.

## 1. Flash MicroPython (each board, once)

1. Hold BOOTSEL, plug the board in, release: a `RPI-RP2` drive appears.
2. Copy the `.uf2` onto it. The board reboots into MicroPython.
3. `mpremote connect list` shows it (e.g. `/dev/ttyACM0`, `COM5`). Note each board's port
   and label the boards **A**, **B**, **C**.

## 2. Build and copy (one command per board)

From `game/`:

```sh
sh tools/board_build.sh <PORT_A>
sh tools/board_build.sh <PORT_B>
sh tools/board_build.sh <PORT_C>
```

The script compiles the pack, precompiles every module with `mpy-cross` (nothing is
compiled on the board: compiling `engine.py` alone needs more RAM than the whole running
ship), and copies `lv/*.mpy`, the glue (`lvship`, `lvdays`, `lvweb`, `lvphone`, `lvstat`,
`lvwifi`, `selftest` as `.mpy`), `pack.bin`, `engage.bin`, the phone page `www/*.gz` and
`main.py`. It removes stale `.py` copies of those modules first (a `.py` would be imported
instead of the `.mpy`), never touches `/data/ship.json`, and ends with
`board: flash free … KB, heap free … B`. About 113 KB of flash; a running ship uses about
78 KB of heap with a sync in progress (inside the 80 KB cap; section 7).

This is **Variant A** (stock MicroPython). It runs the BLE sync and a bench status page
on the hotspot, but **not the phone game**: with every module loaded from files the game
server doesn't fit the heap (about 114 KB with two phones playing). The phone game needs
the game firmware, Variant B (section 8); the board decides by itself (`phone_game: "auto"`).

Without a port it only builds into `build/board/`. `MPY_CROSS=` / `MPREMOTE=` override the
tool paths.

## 3. Configure each board

Create `ship.json` on the computer for each board, then copy it:

```json
{"ship_id": 1, "day": 3, "hotspot": true, "hotspot_password": "<WIFI_PASSWORD_8_TO_63_CHARS>",
 "ssid_prefix": "LV-", "country": "<COUNTRY_CODE>", "led_notify": false}
```

```sh
mpremote connect <PORT_A> cp ship.json :/data/ship.json
```

- `ship_id`: **A = 1, B = 2, C = 3** (1–8, unique per board).
- `day`: the same bench flight day on every board (any 1–42).
- `hotspot_password`: 8–63 characters. Without one the hotspot uses the public
  placeholder `CHANGE_ME`; fine on the bench, never off it.
- Leave `fleet_key` out: the boards use the public test key, which is what the tests use.
- `led_notify` stays `false` (the default) except in check 6.

Optional, for the bulk-transfer check (5): preload the whole simulated season on **A only**:

```sh
mpremote connect <PORT_A> cp build/board/season_log.bin :/data/log.bin
```

`tools/board_build.sh` prints that file's record count and digest (274 records,
`942f23fc` at the time of writing). To start again from empty: `mpremote connect <PORT> rm :/data/log.bin`.

## 4. Run the self-test

`main.py` starts the ship at boot. For the self-test, stop it first, then run the test in
the foreground on every board **at roughly the same time** (one terminal per board):

```sh
mpremote connect <PORT_A> exec "import selftest; selftest.run(180, gift_to=2)"
mpremote connect <PORT_B> exec "import selftest; selftest.run(180, gift_to=3)"
mpremote connect <PORT_C> exec "import selftest; selftest.run(180, gift_to=1)"
```

(`mpremote` interrupts `main.py` when it connects. If a board doesn't stop, put it in
maintenance once: `mpremote connect <PORT> touch :/data/maint` and reset it, then run the line
again.) Add `wifi=True` to bring the hotspot up during the test (check 7), `led=True` for
check 6, and `epoch=<UNIX_TIME>` to give the board the time (otherwise only a phone does).

Every 10 s a board prints a `STAT` line; at the end, a summary and one line per check:

```
SELFTEST lvship 0.2.0-lv-test on rp2, MicroPython 3.4.0; MicroPython v1.29.0 …
SELFTEST config: ship 1, day 3, story True, hotspot False, led_notify False
SELFTEST heap before start: free <N>
SELFTEST firmware: no frozen core (stock MicroPython: every module from the filesystem)
SELFTEST code: lvship.mpy (filesystem), engine filesystem, pack: file
SELFTEST phone game: off (needs the game firmware, or phone_game in ship.json), files all there
SELFTEST ble: active True, advert 020106 10ff ffff4c56 01 00 03 …
SELFTEST log: 1 records, digest <8 hex>, story <16 hex>
SELFTEST gift out: ship 1 -> ship 2, record <26 hex>
SELFTEST led: notifier off (led_notify False), time known False, waiting False
SELFTEST t=10s STAT ship=1 recs=1 digest=… ble=idle peers=2* ok=0 fail=0 sent=0 got=0 new=0 gifts_in=0 led=off/0 heap_used=… heap_free=… day=3/manual
SELFTEST t=60s STAT ship=1 recs=3 digest=… ble=idle peers=2= 3= ok=2 fail=0 sent=1 got=2 new=2 gifts_in=1 led=off/0 …
…
SELFTEST peers seen: ship 2 (same log, 3 records, ok 1, fails 0), ship 3 (same log, 3 records, ok 1, fails 0)
SELFTEST records: sent 2, received 2, new 2; sessions ok 2, failed 0, retries 0
SELFTEST gifts in: from ship 3 item 0 day 3
SELFTEST led: notifier off, waiting True, pin writes 0
SELFTEST heap: used …, peak …, free now …, lowest free …
SELFTEST ble active             PASS
SELFTEST peer heard             PASS
SELFTEST in sync with a peer    PASS
SELFTEST no stuck session       PASS
SELFTEST heap used < 80 KB      PASS
SELFTEST led off unless asked   PASS
SELFTEST RESULT PASS
```

In `peers=`, `2=` means ship 2 was last heard with the same log as ours; `2*` means it
has something we don't (or the reverse) and a sync is due. Log lines in between:
`ble: connecting to ship 2`, `ble: synced with ship 2: sent 1, got 1 (1 new)`,
`gift: from ship 3, item 0, day 3`.

## 5. Checklist

Tick each one; the expected output is what a pass looks like.

| # | Check | How | Expected |
|---|-------|-----|----------|
| 1 | Boots and advertises | 4, any board | `ble: active True`; advert starts `020106 10ff ffff 4c56 01` |
| 2 | Boards find each other | 4, two boards | within ~30 s, `peers=` lists the other ship |
| 3 | First sync | 4, A and B | within ~60 s: `ble: synced with ship …`, `ok=1`+, both `digest=` equal, `peers=2=` / `1=` |
| 4 | Gift path | 4, `gift_to` | the target prints `gift: from ship …`; `gifts in:` lists it |
| 5 | Bulk transfer | preload A (section 3), run A and B | B reaches 274 records plus the gifts, and A's digest, in under 2 min; `retries` small |
| 6 | LED path (game firmware) | `selftest.run(120, gift_to=2, led=True, led_test=True, epoch=<UNIX_TIME>, tz=<MINUTES_EAST_OF_UTC>)` on A, gift from B; or `bench.py --led on --led-test` | A: 3 slow breaths first, then `led=gift/…` in STAT and a double pulse every ~4 s (outside 22:00–07:00). Without `led=True`: `pin writes 0`, `led=off/0`, dark. Section 12 |
| 7 | Coexistence with Wi-Fi | `wifi=True` on A; join `LV-1` from a phone, open `http://192.168.4.1/status` and `/api/sync` | hotspot stays up and pages load during and after a sync; the sync still completes. (On the game firmware `/` is the phone game: section 10) |
| 8 | Relay (3 boards) | keep A and C apart (another room, or C off until A–B synced), then bring C near B only | C gets A's records through B |
| 9 | Off / out of range | power B off mid-test, back on after a minute | A shows `fail=` going up at most once or twice, then quiet (backoff), and syncs again within ~1 min of B returning; nothing stuck in `ble=connecting`/`sync` |
| 10 | Reboot keeps the log | reset a board, run 4 again | `log:` shows the same record count as before the reset |

Timings are loose: scans run 3 s in every 12 s, and the higher-numbered ship waits ~45 s
before trying a connection itself, so a first sync can take a minute.

## 6. If something fails, send back

1. The whole console output of every board from the run (copy the terminal), including
   any traceback.
2. Which check, which boards, and roughly how far apart they were.
3. `mpremote connect <PORT> exec "import sys, gc, os, lv; gc.collect(); print(sys.implementation, gc.mem_free(), os.listdir('/'), lv.describe())"`
4. The board's `/data/ship.json` **with the password removed**.
5. For heap problems, the `SELFTEST heap:` line and the `heap_free=` column from the STAT lines.
6. For Wi-Fi problems: did the hotspot appear at all, did it drop during a sync, phone model.

Common ones:

- `ImportError` / `incompatible .mpy file`: firmware isn't 1.29, or `mpy-cross` isn't 1.29.
- `ble: active False` / `OSError` at start: the firmware build has no Bluetooth (use the
  `_W` firmware), or BLE was left in a bad state: power-cycle the board.
- Peers heard but never synced, `fails` growing: the reason is in `peers seen` and the
  `ble: sync with ship … failed (…)` lines. "no answer" / "connect …" = the connection
  never came up (range, or the other board busy); "silent" / "no ack" right after
  connecting = the GATT handle or CCCD assumption (section 7) is the first suspect;
  "link lost" mid-transfer is normal now and then (the next meeting carries on).
- `MemoryError`: send the heap lines; try without `story` (`"story": false`) to narrow it down.

## 7. What only hardware can tell us

The tests run the same `lv/ble.py` against a fake `bluetooth` module (lossy, duplicating,
reordering, mid-transfer disconnects, power-off, out-of-date and wedged peers; 32- and
64-bit MicroPython) and the protocol against an in-memory link. They can't show:

- **Fixed GATT handles.** Every board registers the same single service, so the code
  assumes the characteristic's value handle is the same on every board and skips service
  discovery (and that its CCCD is the handle after it). If the stack numbers them
  differently, connections set up then fail.
- **CCCD / notifications.** That writing the CCCD on the peer enables notifications, and
  that `gatts_notify` failing with `ENOMEM` when the stack's buffers are full is
  recoverable back-pressure (the code waits and resends).
- **MTU exchange** (128 requested); the code falls back to 23 if it's refused.
- **Cancelling a connect** with `gap_connect(None)` after a timeout.
- **Coexistence** with the SoftAP on the shared CYW43 radio at the configured scan duty
  (3 s of scanning per 12 s, 30 ms window per 300 ms interval, ~2.5 % of airtime).
- **IRQ timing**: the IRQ handler only queues; work happens in `poll()` from the asyncio
  loop. Long blocking work elsewhere would delay acks (the retry timer allows 1.5 s).
- **Real heap.** The unix-port measurements (32-bit, `.mpy`, the whole season and the
  story at day 42, a sync running) are in section 8: 79 KB on Variant A, 35 KB on the game
  firmware (lv-core 0.2.0; 52 KB on 0.1.0), 46–49 KB with two phones playing, the ship light
  and the battery (78–80 KB on 0.1.0). The board number is in
  `SELFTEST heap:`. The Wi-Fi driver's and lwIP's buffers live outside the MicroPython
  heap and aren't in these numbers.
- **Range** and how often boards actually meet in practice.
- **The ship light**: that the breathing is visible (section 12) and that the LED writes
  (commands to the CYW43 chip, about 50 a second while a pattern plays) don't disturb BLE
  or the hotspot: compare `ok`/`fail` in the STAT lines with the light on and off, and
  phone page loads while it pulses.
- **`tools/bench.py` on a real board**: finding the port, stopping `main.py` to get the
  REPL, the `--uf2` BOOTSEL copy. Tested only against fake boards; if it misbehaves, the
  manual steps in this file still work.

## 8. Variant B: the game firmware (the game frozen in, every part still updatable)

Variant A (sections 1–2) is stock MicroPython plus the whole game copied over as `.mpy`
files. Variant B is one `.uf2`: MicroPython v1.29.0 with the game frozen in. Frozen code
and data run from flash, not the heap, which is what makes room for the phone game.

- **lv-core 0.2.0** (current) freezes the core `lv/` (engine, state, pack reader, record
  log, BLE sync and the other stable libraries), `lvfrozen` (its version manifest), the
  12 board modules (`lvship`, `lvreport`, `lvcal`, `lvled`, `lvledcfg`, `lvbatt`, `lvdays`,
  `lvweb`, `lvphone`, `lvstat`, `lvwifi`, `selftest`) and the story pack (as `lvpackdata`,
  a bytes object read in place). Files on the board: `main.py`, `engage.bin` and the
  phone page `www/app.html.gz`, `www/text.json.gz`, `www/engage.json.gz`.
- **lv-core 0.1.0** froze only `lv/` and `lvfrozen`; the board modules and `pack.bin` were
  files. Its releases (`0.1.0-lv-test`) don't install on 0.2.0 and the other way round.

Every frozen part can still be replaced without reflashing: a file is found before the
frozen module (see "Fixing … without reflashing" below).

| Heap peak, unix 32-bit (whole season, story at day 42, sync running) | Variant A | Variant B, lv-core 0.1.0 | Variant B, lv-core 0.2.0 |
|---|---|---|---|
| Sync only (status page) | about 79 KB (ship light: stays dark) | about 52 KB | about 35 KB |
| Sync + two phones playing the game | about 114 KB (so: off) | about 75–78 KB; about 78–80 KB with the ship light and battery | about 46–49 KB, ship light and battery included |
| Code in the heap | about 51 KB | about 23 KB (31 KB with the phone server) | about 14 KB (16 KB with the phone server) |

**Build** (on the computer, from `game/`; the first run downloads MicroPython and the Pico
SDK, about 10 minutes): `sh tools/build_firmware.sh`. It needs `gcc-arm-none-eabi`,
`libnewlib-arm-none-eabi`, `cmake`, `make` and Python 3, and writes
`build/firmware/lv-core-<version>-<core>-RPI_PICO_W.uf2`, its `.sha256`, and
`lv-core-<version>-<core>.json` (what was frozen, module by module; a copy goes in
`tools/fw/cores/`). `<core>` is a 12-hex hash of the frozen sources. Or use the `.uf2`
you were given.

**Flash** (each board):

1. Optional, if the board ran Variant A: clear the old files, because the filesystem
   survives a flash and a leftover `/lv` folder hides the frozen core. Keeps `/data`
   (settings, crew codes, the log) and bench logs:
   `mpremote connect <PORT> run tools/fw/clean_fs.py`. (The updater's install, step 3,
   removes `/lv` itself.)
2. Hold BOOTSEL, plug in, release: the `RPI-RP2` drive appears. Drag
   `lv-core-<version>-<core>-RPI_PICO_W.uf2` onto it. The board reboots into MicroPython
   with the core inside; it has no game files yet.
3. Put the game's files on it: the updater page (section 9), or from `game/`:
   `LAYOUT=fw sh tools/board_build.sh <PORT>` (copies `build/board-fw/`).

**Configure**: as in section 3; a board keeps `/data` across a flash.

**Self-test**: same commands as section 4. The extra lines should read

```
SELFTEST firmware: frozen lv-core 0.2.0 (core <12 hex>), overrides: [], board files: []
SELFTEST code: lvship.py (frozen), engine frozen, pack: frozen
SELFTEST phone game: on, files all there
```

`HIDDEN by a /lv directory` means step 1 is needed; `engine filesystem` without an
override means the same. `board files: [lvship, …]` (or `lvship.mpy (filesystem)`,
`pack: file`) without a hotfix release means copies from an older install are left:
install the release again (it removes them) or run step 1.

**Compare with Variant A** (same board, same `ship.json`, same day):

- `SELFTEST log:` digest and story hash: **identical** (same game, same records).
- `SELFTEST heap: … peak …` and `heap_used=`: B about 25 KB **lower** with Wi-Fi off;
  with `wifi=True` and phones playing, still under 80 KB.
- Checks 1–10 in section 5 behave the same, sync times included.

**Fixing a board module or the story without reflashing** (lv-core 0.2.0). Put
`/<module>.mpy` (e.g. `/lvweb.mpy`) or `/pack.bin` on the board: it is found before the
frozen copy, and `SELFTEST firmware:` lists it under `board files`. `tools/board_build.sh`
does this by itself: it compares `board/` and `build/pack.bin` with the core's manifest
and puts only what changed into `build/board-fw/`; `tools/build_release.py` then lists
those under `"replaces"` and deletes every other copy, so a hotfix never outlives the
release that shipped it.

**Fixing a core module without reflashing.** Put `lvx/<module>.mpy` on the board (e.g.
`lvx/engine.mpy`): `lv/__init__` loads it over the frozen `lv.<module>` at boot, and
`SELFTEST firmware:` lists it under `overrides`. A broken override falls back to the
frozen module with a printed warning. Only modules the core already has can be replaced
(`lv/__init__.py` itself, or a new module, needs a new `.uf2`). `tools/board_build.sh`
does this by itself: it compares `lv/` with the newest `tools/fw/cores/*.json` (or
`FROZEN_CORE=…`) and puts only the changed modules into `build/board-fw/lvx/`.

**Roll back** to stock MicroPython: BOOTSEL as above and drag the stock
`RPI_PICO_W-…-v1.29.0.uf2` from micropython.org (the updater page, section 3, links it with
its sha256). `/data` is kept. Then copy Variant A (section 2), or install `0.0.2-coex`.

## 9. The test build on the updater page

The updater lists `0.2.0-lv-test` (lv-core 0.2.0) and `0.1.0-lv-test` (lv-core 0.1.0) as
**[TEST BUILD]** in section 2. Each is a **partial release for the game firmware**: only
the files above (no `lv/`), built against one frozen core (`release.json` `"frozen":
{"requires": "<core>"}`, plus `lvx/` overrides if any core module changed since, and on
0.2.0 `/<module>.mpy` or `/pack.bin` hotfixes listed in `"replaces"`). The page reads the board's frozen core
(section 1 shows `MicroPython 1.29.0 · game firmware: frozen lv-core … overrides: […]`)
and refuses to install on stock MicroPython or another core, before writing anything,
naming the `.uf2` to flash. Installing removes `/lv` and old `lvx/` overrides first and,
on 0.2.0, every file copy of a frozen board module or the pack it doesn't ship. It
is never "latest": "Install latest" and the update notice ignore it, and installing it
asks first. Ship settings and crew codes in `data/` are kept. To go back, flash the older
`.uf2` and install its release (`0.1.0-lv-test` on lv-core 0.1.0), or install `0.0.2-coex`
(it runs on the game firmware too).

## 10. Play it on your phone

One board is enough. Tick each step.

1. **Flash** `lv-core-0.2.0-<core>-RPI_PICO_W.uf2` (section 8, step 2).
2. **Updater page**, connect the board. Section 1 shows
   `game firmware: frozen lv-core 0.2.0 (core <core>), overrides: [], board files: []`
   (board files listed before the install are a 0.1.0 install's leftovers; step 4
   removes them).
3. **Section 4**: set the ship number (the hotspot is `LV-<ship number>`), the hotspot
   password, and the **crew codes** (4 digits per crew member; a blank one shows "Not set
   up" and can't sign in). For the real calendar also set **Launch date** (see step 5 and
   section 11). Save. Use the updater page from this branch (from the repo root:
   `python3 -m http.server 8140`, open http://localhost:8140 in Chrome); the deployed page
   is older: it has no launch date field and its Save overwrites the whole `ship.json`, which
   clears `launch_date` and a bench `day`.
4. **Section 2**: pick `0.2.0-lv-test [TEST BUILD]`, Install, confirm. Expect it to finish
   with every file verified. (If an earlier `0.2.0-lv-test` is already on the board,
   install it again anyway: the version number can stay the same while files change.) (On a board without the game firmware it stops here with
   "needs the game firmware …": go back to step 1.)
5. **Flight day**. Two ways:
   - **Calendar** (how the voyage runs): with a **Launch date** set in step 3, flight day 1
     starts at 06:00 that day and a new one starts every morning at 06:00, local time, up to
     day 42 (six weeks). The board learns the time from the phones (every page request
     carries the phone's clock and time zone), so the day is right once a phone has opened
     the page. Before 06:00 on the launch date the page shows a countdown ("Pre-launch ·
     FD 00") instead of the crew list. Section 11 has a quick rollover test.
   - **Manual bench day** (Launch date blank, as before): the board stays on the `day` in
     `ship.json` (1 if unset). For a later day:
     `mpremote connect <PORT> exec "import json; p='/data/ship.json'; c=json.load(open(p)); c['day']=9; open(p,'w').write(json.dumps(c))"`.
     Saving section 4 on this branch's page keeps it.
6. **Power-cycle** the board. On the console (`mpremote connect <PORT>`), expect
   `firmware: frozen lv-core 0.2.0 …`, then `web: phone game on http://192.168.4.1/`.
7. **Join `LV-<ship number>`** on the phone with the password. Expect the sign-in sheet
   to open by itself (iPhone "Log in" sheet, Android "Sign in to network"): the board
   answers every DNS name with itself and sends the phones' connectivity probes to the
   game. If nothing opens, browse to `http://192.168.4.1/` (or any `http://` address).
8. **Sign in**: tap your name, enter a wrong code once (expect "That code doesn't match. 4 tries left."), then the
   right one. The first time this crew member signs in since the board booted, expect the
   welcome card (your astronaut's portrait) with **Crew briefing · 10 cards** where "Go
   aboard" usually is: tap it, step through the cards with Next (three intro cards: the
   goal, how the ship works with Wi-Fi and Bluetooth, your day; then instructions, what
   needs you, deliveries, how things travel, watch duty, the ship light, the log; Skip
   works too), and
   **Go aboard** on the last one lands on home with today's story. The phone remembers it
   has read the briefing; a later sign-in goes straight home (it's under FILE › How to
   play). A phone that forgets (some captive-portal sheets don't keep storage) is offered
   it again only on the first sign-in after a reboot. Check the eight portraits on the
   sign-in sheet look distinct and none has a chest symbol (the flagship's chest ring is
   rust).
9. **Vote** on an open card, if today has one (the card shows your pick afterwards);
   **send a gift** from Gifts and asks (a second one the same day is refused: "One gift a
   day"); **open** today's drop if there is one; look at the **crew** page and the
   **log**.
10. **Second phone** as another crew member at the same time: both keep working; a tap on
    one shows up on the other within about 15 s (the board has no WebSocket, so the page
    polls `/api/v`; the page shows "Live link down · checking every 15 s", which is
    expected here).

    **Who's in range**, with a second board (another ship number) powered next to this
    one: your crew page shows that ship's astronaut as **Nearby · in sync** (or
    **Nearby · syncing** for a moment) within about a minute, and the gift pickers show
    **Nearby** under their name. Unplug the second board: about 3 minutes later it reads
    **In range N min ago**. Crewmates whose ship this board hasn't heard since it booted
    (or in the last day) show **Not in range lately**. A gift goes through either way;
    nearby only means it lands now.
11. **A phone that stops**: lock one phone mid-game or walk out of range. The other
    phone must not stall (the board drops a silent connection after 5 s and serves up to
    4 requests at once; a fifth at the same moment gets "busy, try again": tap again).
12. **Sign out** in Settings (the gear at the top right); reopening the sheet asks for the code again.
    Reopening without signing out the same flight day goes straight back in.
13. **Status and heap**: `http://192.168.4.1/status` shows the STAT line (it ends with
    `day=<flight day>/<source>`: `phone`, `saved`, `peer`, `none` or `manual`);
    `heap_used=` must stay under 80 KB with phones playing and another board syncing
    nearby. Or run `selftest.run(180, wifi=True)` and play during it: `SELFTEST heap used <
    80 KB PASS`.

Send back: the console from step 6 on, the phone models, whether the sheet opened by
itself (step 7), and any step that didn't do what it says.

## 11. Flight days from the calendar: a quick rollover test

What the board does (`board/lvcal.py`):

- **Day** = days since 06:00 local on the launch date, plus 1, between 1 and 42. Before
  06:00 on the launch date it is 0 (the countdown). After day 42 it stays 42.
- **Time** comes from the phones' clock (`X-Phone-Time`, `X-Phone-TZ` on every request), so
  the phone's time zone and daylight saving are used as they are. With no phone yet since
  boot, the board continues from the time it saved to flash (`/data/clock.json`, written when
  the day changes and at most once an hour otherwise, to spare the flash), counting the time
  it was switched off as zero; a phone then corrects it.
- **Never backwards**: a phone with a wrong (earlier) clock can't move the day back.
- **Peers**: with no clock at all, a board takes a nearby board's day only when it is from
  our fleet (same fleet key; other fleets are ignored by the radio) and exactly one day
  ahead. One step per board, so one wrong board can't push the fleet ahead.
- The story is the same: the day only decides how many days are played out, and every
  board plays the same days from the same records (determinism checks: 8 of 8 ships match).
- While running, the board checks every 10 s and on every phone request; at 06:00 it plays
  out the new day and an open page shows it on its next poll (within about 15 s).

**Quick test tonight** (one board, about 10 minutes). Pick a flight day N (e.g. 9) and a
time T a few minutes from now (e.g. `21:30`).

1. Launch date = today minus N−1 days (today the 23rd, N = 9: the 15th). Set it in
   section 4 of the updater page (step 3 above) and Save, or by mpremote.
2. Move the morning to T for the test (`day_start`; only settable by mpremote; default
   `06:00`):
   `mpremote connect <PORT> exec "import json; p='/data/ship.json'; c=json.load(open(p)); c['launch_date']='2026-10-15'; c['day_start']='21:30'; open(p,'w').write(json.dumps(c))"`
3. Power-cycle, join `LV-<ship number>`, open the page. Before T it shows **FD N−1** (today's
   day hasn't started yet); console: `day: flight day <N−1> (phone)`.
4. Sign in and leave the page open. At T the console prints `day: flight day N (phone)` and
   the page shows **FD N** and the new day's story within about 15 s, without reloading.
5. Reboot keeps the day: power-cycle and, before opening the game page, watch the console
   STAT lines (or browse to `http://192.168.4.1/status`, which doesn't send the phone's
   clock): they end `day=N/saved`. After the game page opens: `day=N/phone`. Never N−1.
6. Countdown: set the launch date to tomorrow (or `day_start` later today with launch date
   today). The page shows "Pre-launch · FD 00", "Launch in …", and no crew to tap; it
   switches to the crew list by itself when the time comes.
7. Afterwards: remove `day_start` (or set it to `"06:00"`) and set the real launch date.
   Changing the launch date or `day_start` starts the saved clock over (it doesn't carry an
   old day across). Back to the manual bench day: clear Launch date in section 4 and Save.

## 12. The ship light (LED notifier)

The Pico W's onboard LED as a quiet "something is waiting" light (`board/lvled.py`). Game
firmware only (on stock MicroPython its code would push the heap past the cap, so it stays
dark there). **Off unless switched on**, three ways: tick "Pulse the onboard light…" in
section 4 of the updater page and Save; the **Ship light** button in Settings on the
phone (the gear at the top right; kept in `ship.json` too); or `bench.py --led on`.

Every pattern **breathes**: the LED has no dimmer (it is a pin on the radio chip, on or
off), so the board flicks it 100 times a second, lit for part of each 10 ms frame, the lit
part following a squared ramp up and back down. The eye sees a soft glow swelling and
fading, not a blink (tried on a real board first, and it looked right).

What it shows (most important first):

| Pattern | Means | Rhythm |
|---------|-------|--------|
| 3 slow breaths, once | the bench test (`--led-test`, `selftest.run(..., led_test=True)`) | 1 s up, 1 s down, 0.5 s dark between |
| 3 quick breaths, once | a new flight day's page is ready (06:00) | 0.2 s up, 0.3 s down |
| double pulse | a crewmate sent a gift | 2 quick pulses (0.4 s) every ~4 s |
| one slow breath | today's page hasn't been opened here yet | 0.6 s up, 0.8 s down, every ~5 s |

- **Clears** as soon as a signed-in phone opens the game on this board.
- **Quiet hours** 22:00–07:00 local time (the phones' clock, so daylight saving follows the
  phones); the 06:00 breaths fall inside them and show at 07:00 instead. `"led_quiet":
  "HH:MM-HH:MM"` in `ship.json` changes them, `""` turns them off.
- **No time, no light**: until a phone has brought the time since boot it stays dark
  (`"led_unknown_time": true` to light anyway).
- **Budget**: at most 900 s lit a day (`"led_budget_s"`), counted by brightness (a breath
  averages a third of full), about 2.5 hours of the waiting breath; resets at local midnight.
- **Radio and CPU**: the LED hangs off the CYW43 Wi-Fi/BT chip, so each on/off is a command
  to it over SPI: about 0.3-0.4 ms each, measured on a Pico W with the hotspot up. The
  light runs as its own asyncio task and yields after every edge, so the web server, the
  DNS and the BLE sync keep running between frames; only the dim end of a ramp (lit under
  1.5 ms) is a short busy-wait. While a pattern plays that is up to 2 writes per 10 ms frame
  and about 10% of the CPU (measured on ship 1: 12% during the slow test breaths, 8-10%
  over the waiting and gift rhythms); between patterns it sleeps and sends nothing. No memory is
  allocated per frame.
- **Fallbacks**: a pattern never starts during a BLE sync or an HTTP request; if one starts
  while a pattern is playing, the rest of it is a plain blink (lit through the bright middle
  of each breath, 2 writes a breath). The light times its own writes (a running average): if
  the radio chip gets slow (over 2 ms a write) it plays plain blinks until the writes are
  fast again. The selftest's end line shows `write cost … us`.
- STAT lines show it as `led=<state>/<pin writes>`: `off`, `idle`, `test`, `day`, `gift`,
  `waiting`, or why it is dark: `quiet`, `no clock`, `budget`.

**Seeing it tonight through the current (opaque) case**: the LED sits on the top of the
board next to the USB socket. Take the lid off for the test (or look in at the USB opening
from the side, in a dim room). `--led-test` gives about 7 s of slow breaths right after the
self-test starts; the bench asks "Did you see the LED pulse: fade up and back down 3 times
(not hard blinks)?" (a board still on an older build blinks instead, and the bench asks
about blinks). The transparent PLA case is what it's for later.

Check at the bench: `bench.py --led on --led-test` → `LED path PASS` and `LED pulse test
PASS` (you saw it). To watch the real schedule: leave it on with a launch date, power-cycle,
open the game on a phone once (the board learns the time), close it: nothing until the next
gift or 06:00 page; send a gift from another board's phone and the double pulse starts
within a few seconds (outside quiet hours), and stops when you open the game on this board.
Off again: `bench.py --led off --no-selftest` or the Ship light button.

## 13. The ship battery (optional UPS-Lite)

A board with a UPS-Lite v1.3 wired to it (`board/lvbatt.py`; the wiring and soldering
guide is `docs/BATTERY.md`) reports its battery in the self-test, in the bench report and
on the phones. Nothing to switch on: at boot the board looks for the fuel gauge (I2C
address 0x62 on GP4/GP5) once, and a board without one carries on exactly as before.

- Self-test: `SELFTEST battery: detected, 87%, 4012 mV, charging yes` (also printed at the
  end, after a fresh reading), or `none detected (optional, docs/BATTERY.md)`. Just after
  the gauge wakes up it can say `reading unknown` for a few seconds.
- Bench report: a `battery` row, always **INFO**: a missing or unreadable battery never
  fails the bench.
- Phones: a small battery mark with the percent at the top of the ship's page (a bolt while
  it charges), a gentle "plug your ship in" line on Home under 15%, and a Battery line on
  the "How it works" briefing card. None of it shows on a board without a battery.
- `ship.json` (all optional): `"battery": false` never looks, `true` always shows the
  battery (as "unknown" if the gauge doesn't answer); `bat_sda`, `bat_scl` (default 4, 5),
  `bat_chg` (default 6, `-1` for none), `bat_chg_pull` (`"down"`, `"up"`, `"none"`),
  `bat_every_s` (default 60), `bat_khz` (unset: 50 kHz, falling back to 10 kHz; the Pico's
  internal pull-ups are switched on, so the 4.7 kΩ resistors are optional).
