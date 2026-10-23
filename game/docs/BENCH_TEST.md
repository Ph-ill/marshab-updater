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
ship), and copies `lv/*.mpy`, `lvship.mpy`, `selftest.mpy`, `lvwifi.mpy`, `pack.bin` and
`main.py`. It removes stale `.py` copies of those modules first (a `.py` would be imported
instead of the `.mpy`), never touches `/data/ship.json`, and ends with
`board: flash free … KB, heap free … B`. About 50 KB of flash; a running ship uses about
76 KB of heap with a sync in progress (well inside the 96 KB budget; section 7).

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
SELFTEST lvship 0.1.0-ble on rp2, MicroPython 3.4.0; MicroPython v1.29.0 …
SELFTEST config: ship 1, day 3, story True, hotspot False, led_notify False
SELFTEST heap before start: free <N>
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
| 7 | Coexistence with Wi-Fi | `wifi=True` on A; join `LV-1` from a phone, open `http://192.168.4.1/` and `/api/sync` | hotspot stays up and pages load during and after a sync; the sync still completes |
| 8 | Relay (3 boards) | keep A and C apart (another room, or C off until A–B synced), then bring C near B only | C gets A's records through B |
| 9 | Off / out of range | power B off mid-test, back on after a minute | A shows `fail=` going up at most once or twice, then quiet (backoff), and syncs again within ~1 min of B returning; nothing stuck in `ble=connecting`/`sync` |
| 10 | Reboot keeps the log | reset a board, run 4 again | `log:` shows the same record count as before the reset |

Timings are loose: scans run 3 s in every 12 s, and the higher-numbered ship waits ~45 s
before trying a connection itself, so a first sync can take a minute.

## 6. If something fails, send back

1. The whole console output of every board from the run (copy the terminal), including
   any traceback.
2. Which check, which boards, and roughly how far apart they were.
3. `mpremote connect <PORT> exec "import sys, gc, os; gc.collect(); print(sys.implementation, gc.mem_free(), os.listdir('/'), os.listdir('/lv'))"`
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
- **Real heap.** The unix-port measurement is 76 KB peak for a board with the whole
  season, the story, the status server and a sync running (32-bit, `.mpy`); the board
  number is in `SELFTEST heap:`.
- **Range** and how often boards actually meet in practice.
