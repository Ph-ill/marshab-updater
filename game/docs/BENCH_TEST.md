# Bench test: BLE ship-to-ship sync on 2–3 Pico W boards

What this checks, on real hardware, that the tests can only fake: the radio. Boards
advertise, find each other, connect, swap the records the other is missing over one GATT
characteristic and disconnect, while each keeps its Wi-Fi hotspot up. Allow about an
hour for three boards.

Placeholders are in `<ANGLE BRACKETS>`; fill them in for your own bench. Nothing here
needs a server: the boards only talk to each other and to a phone or laptop on their hotspot.

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
SELFTEST lvship 0.1.0-lv-test on rp2, MicroPython 3.4.0; MicroPython v1.29.0 …
SELFTEST config: ship 1, day 3, story True, hotspot False, led_notify False
SELFTEST heap before start: free <N>
SELFTEST firmware: no frozen core (stock MicroPython: every module from the filesystem)
SELFTEST code: lvship.mpy (filesystem), engine filesystem, pack: file
SELFTEST phone game: off (needs the game firmware, or phone_game in ship.json), files all there
SELFTEST ble: active True, advert 020106 10ff ffff4c56 01 00 03 …
SELFTEST log: 1 records, digest <8 hex>, story <16 hex>
SELFTEST gift out: ship 1 -> ship 2, record <26 hex>
SELFTEST led: notifier off (led_notify False), time known False, waiting False
SELFTEST t=10s STAT ship=1 recs=1 digest=… ble=idle peers=2* ok=0 fail=0 sent=0 got=0 new=0 gifts_in=0 led=off heap_used=… heap_free=…
SELFTEST t=60s STAT ship=1 recs=3 digest=… ble=idle peers=2= 3= ok=2 fail=0 sent=1 got=2 new=2 gifts_in=1 led=off …
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
| 6 | LED path | `selftest.run(120, gift_to=2, led=True, epoch=<UNIX_TIME>)` on A, gift from B | A: `notifier ON`, `waiting True`, LED blinks per the notifier schedule. Without `led=True`: `pin writes 0` and the LED stays dark |
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
  story at day 42, a sync running) are in section 8: 78 KB on Variant A, 51 KB on the game
  firmware, 73–74 KB on the game firmware with two phones playing. The board number is in
  `SELFTEST heap:`. The Wi-Fi driver's and lwIP's buffers live outside the MicroPython
  heap and aren't in these numbers.
- **Range** and how often boards actually meet in practice.

## 8. Variant B: the game firmware (the core frozen in, the rest updatable)

Variant A (sections 1–2) is stock MicroPython plus the whole game copied over as `.mpy`
files. Variant B is one `.uf2`: MicroPython v1.29.0 with the game's **core** frozen in
(`lv/`: engine, state, pack reader, record log, BLE sync and the other stable libraries,
plus `lvfrozen`, its version manifest). Frozen code runs from flash, not the heap, which
is what makes room for the phone game. Everything likely to change stays a file the
updater page can replace: `main.py`, the glue (`lvship`, `lvdays`, `lvweb`, `lvphone`,
`lvstat`, `lvwifi`, `selftest`), the story pack `pack.bin`, `engage.bin` and the phone
page `www/app.html.gz`, `www/text.json.gz`, `www/engage.json.gz`.

| Heap peak, unix 32-bit (whole season, story at day 42, sync running) | Variant A | Variant B |
|---|---|---|
| Sync only (status page) | about 78 KB | about 51 KB |
| Sync + two phones playing the game | about 114 KB (so: off) | about 73–74 KB |
| Code in the heap | about 51 KB | about 23 KB (31 KB with the phone server) |

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
SELFTEST firmware: frozen lv-core 0.1.0 (core <12 hex>), overrides: []
SELFTEST code: lvship.mpy (filesystem), engine frozen, pack: file
SELFTEST phone game: on, files all there
```

`HIDDEN by a /lv directory` means step 1 is needed; `engine filesystem` without an
override means the same.

**Compare with Variant A** (same board, same `ship.json`, same day):

- `SELFTEST log:` digest and story hash: **identical** (same game, same records).
- `SELFTEST heap: … peak …` and `heap_used=`: B about 25 KB **lower** with Wi-Fi off;
  with `wifi=True` and phones playing, still under 80 KB.
- Checks 1–10 in section 5 behave the same, sync times included.

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

The updater lists `0.1.0-lv-test` as **[TEST BUILD]** in section 2. It's a **partial
release for the game firmware**: only the updatable files above (no `lv/`), built against
one frozen core (`release.json` `"frozen": {"requires": "<core>"}`, plus `lvx/`
overrides if any core module changed since). The page reads the board's frozen core
(section 1 shows `MicroPython 1.29.0 · game firmware: frozen lv-core … overrides: […]`)
and refuses to install on stock MicroPython or another core, before writing anything,
naming the `.uf2` to flash. Installing removes `/lv` and old `lvx/` overrides first. It
is never "latest": "Install latest" and the update notice ignore it, and installing it
asks first. Ship settings and crew codes in `data/` are kept. To go back, install
`0.0.2-coex` (it runs on the game firmware too).

## 10. Play it on your phone

One board is enough. Tick each step.

1. **Flash** `lv-core-0.1.0-<core>-RPI_PICO_W.uf2` (section 8, step 2).
2. **Updater page**, connect the board. Section 1 shows
   `game firmware: frozen lv-core 0.1.0 (core <core>), overrides: []`.
3. **Section 4**: set the ship number (the hotspot is `LV-<ship number>`), the hotspot
   password, and the **crew codes** (4 digits per crew member; a blank one shows "Not set
   up" and can't sign in). Save.
4. **Section 2**: pick `0.1.0-lv-test [TEST BUILD]`, Install, confirm. Expect it to finish
   with every file verified. (If an earlier `0.1.0-lv-test` is already on the board,
   install it again anyway: the version number is the same but `www/app.html.gz` is new;
   the board's core and `.uf2` are unchanged.) (On a board without the game firmware it stops here with
   "needs the game firmware …": go back to step 1.)
5. Optional, **flight day**: the page's ship settings start the bench at day 1. For a
   later day (more of the story to read):
   `mpremote connect <PORT> exec "import json; p='/data/ship.json'; c=json.load(open(p)); c['day']=9; open(p,'w').write(json.dumps(c))"`
   (do this after step 3: saving section 4 again resets it).
6. **Power-cycle** the board. On the console (`mpremote connect <PORT>`), expect
   `firmware: frozen lv-core 0.1.0 …`, then `web: phone game on http://192.168.4.1/`.
7. **Join `LV-<ship number>`** on the phone with the password. Expect the sign-in sheet
   to open by itself (iPhone "Log in" sheet, Android "Sign in to network"): the board
   answers every DNS name with itself and sends the phones' connectivity probes to the
   game. If nothing opens, browse to `http://192.168.4.1/` (or any `http://` address).
8. **Sign in**: tap your name, enter a wrong code once (expect "That code doesn't match. 4 tries left."), then the
   right one. The first time this crew member signs in since the board booted, expect the
   welcome card (your astronaut's portrait) with **Crew briefing · 6 cards** where "Go
   aboard" usually is: tap it, step through the six cards with Next (Skip works too), and
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
11. **A phone that stops**: lock one phone mid-game or walk out of range. The other
    phone must not stall (the board drops a silent connection after 5 s and serves up to
    4 requests at once; a fifth at the same moment gets "busy, try again": tap again).
12. **Sign out** from your astronaut's page; reopening the sheet asks for the code again.
    Reopening without signing out the same flight day goes straight back in.
13. **Status and heap**: `http://192.168.4.1/status` shows the STAT line;
    `heap_used=` must stay under 80 KB with phones playing and another board syncing
    nearby. Or run `selftest.run(180, wifi=True)` and play during it: `SELFTEST heap used <
    80 KB PASS`.

Send back: the console from step 6 on, the phone models, whether the sheet opened by
itself (step 7), and any step that didn't do what it says.
