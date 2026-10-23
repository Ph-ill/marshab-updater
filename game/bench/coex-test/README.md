# Wi-Fi SoftAP + BLE coexistence soak test (Pico W / Pico 2 W, MicroPython)

This firmware answers one question before any game code gets written: can one CYW43439 run a SoftAP with
phones on a captive page **and** BLE advertising, scanning and the odd GATT transfer, for days, without
dropping either side?

**Status:** I syntax-checked it with mpy-cross 1.29.0 and ran the host scripts against fake data. It has **not run on
hardware yet**. Expect a fix-up pass during the first hour on the bench. Sources and reasoning are in the
"Wi-Fi + Bluetooth coexistence" section of the design Page.

## Files
| File | What it does |
|---|---|
| `config.py` | Every knob: ship id, channel, scan duty, advert interval, mode, GATT test, stall thresholds, watchdog |
| `main.py` | Starts the AP first, then BLE (activated once and never toggled), then the tasks listed below |
| `index.html` | Test page. Opens a WebSocket to `/ws` and sends an echo every 2 s, falling back to HTTP polling. Shows round trips and the board's counters |
| `host/probe.py` | Laptop probe: `/ping` every 2 s (round trip and failures), `/api/stats` every 60 s |
| `host/summarize.py` | Turns the probe CSV and stats JSONL (plus board B's `/coex_log.csv`) into a PASS/FAIL table |

Tasks in `main.py`:
- **DNS:** catch-all DNS on UDP 53 that answers every name with 192.168.4.1.
- **HTTP:** asyncio server on port 80.
  - Captive-probe paths (`/generate_204`, `/hotspot-detect.html`, `/connecttest.txt`, ...) get a 302 to `/`.
  - `/` serves the page. `/ping`, `/api/stats` and `/log` (last 120 log lines) are the diagnostic endpoints.
  - `/ws` is a WebSocket echo that also pushes stats.
- **Wi-Fi:** polls `ap.status("stations")` every second and logs every join and leave by MAC.
- **BLE advertising:**
  - Legacy adverts at 1 s with manufacturer data `FFFF 'LV' ship seq uptime`.
  - The payload is re-issued with a new sequence number every 5 s. This is the same "rotate the advert" pattern the game uses.
- **BLE scanning:**
  - Passive and duty-cycled (30 ms window every 300 ms = 10 %).
  - Counts every advert, plus the other board's sequence numbers. Gaps in the numbers show missed rotations.
  - Logs **STALL peer** (other board unheard for 60 s) and **STALL silent** (nothing at all heard for 30 s while scanning). The second one is the HCI-stall signature from pico-sdk#1472.
- **GATT (board 1 only):** every 5 min it connects to board 0, but only if board 0 was heard in the last 3 s.
  - It pushes 8 KB by write-without-response, reads back board 0's byte counter, and disconnects.
  - Both boards register the same service, so the value handle is known without discovery.
- **Stats:** one line to USB serial every 60 s, and one CSV row to `/coex_log.csv` every 10 min (rotated at 180 KB).
- **Watchdog:**
  - An 8 s hardware watchdog is fed only by the asyncio loop. A wedged stack resets the board, and the boot counter in `/coex_boot.txt` records it.
  - It can't be stopped once started. Set `USE_WDT = False` while you're editing files over USB.

## Setup
1. Flash MicroPython **v1.29.0** (cyw43-driver 1.1.1, pico-sdk 2.3.0) on both boards.
   - Pico W: `RPI_PICO_W` uf2. Pico 2 W: `RPI_PICO2_W` uf2.
   - Don't mix firmware versions between the two boards.
2. Edit `config.py`: `SHIP_ID = 0` for board A, `SHIP_ID = 1` for board B.
3. Copy the files to each board:
   `mpremote cp config.py main.py index.html :`
   then `mpremote reset`.
4. Capture board A's serial log on the laptop:
   `mpremote connect /dev/ttyACM0 repl | ts '%Y-%m-%d %H:%M:%S' > boardA.log`
   (`ts` comes from moreutils). Board B can run on a USB power bank; read its log from flash afterwards.
5. Join the laptop to `COEX-0` (WPA2 password `CHANGE_ME`; set `AP_PASSWORD=""` for an open network) and run `python3 host/probe.py --minutes 1440`.
6. Join 1-3 phones to `COEX-0` and leave the page open with the screen kept on.
   - An old phone on a charger is ideal.
   - Note which phone joined first: iOS and Android show the captive sheet differently.

Put the boards **2-5 m apart**, ideally in the room where the ships will actually sit. Note what else is on 2.4 GHz
(your home router's channel, Bluetooth headphones, a microwave).

## Bench plan (2 boards, about 6 days end to end)
| Phase | Duration | Config change | What it proves | Pass |
|---|---|---|---|---|
| 0 Baseline Wi-Fi | 2 h | `BLE_ENABLE=False` | Router-free AP and page are solid on their own; gives the RTT baseline | 100 % `/ping`, p95 within 2x of phase 0 later |
| 1 Baseline BLE | 2 h | Default config, no phones and no laptop joined | Scanning and adverts alone: peer heard, no stalls | Peer gap max <= 60 s, 0 stalls |
| 2 Concurrent, design settings | **24 h** | Default config (10 % passive scan, 1 s adverts, GATT every 5 min) | **The main test** | Every PASS row in `summarize.py` |
| 3 Stress | 12 h | `SCAN_WINDOW_MS=90` (30 %), `SCAN_ACTIVE=True`, `GATT_PERIOD_S=60`, 3 phones + laptop | Where the margin is. Failing here is fine; it tells you how close phase 2 is to the edge | Record, don't gate |
| 4 Soak | **72 h** | Whatever passed phase 2, unchanged | Days of stability, heap drift, flash-write interaction | Every PASS row, 0 watchdog resets |
| 5a Hotspot button | 4 h | `AP_CYCLE_S=300`, `AP_OFF_S=20` (about 48 off/on cycles) | Whether turning the hotspot off and on with BLE running is safe. The design's "hotspot button" depends on it | `ap_cycles` > 40, `ap_cycle_err` 0, peer still heard after every cycle, no reboot |
| 5b Abuse | 2 h | Default | Recovery: 50x phone leave/join, 20x board B power-cycle, laptop sleep/wake, walking out of range | AP still accepts joins, board A sees B again within 60 s, no reboot on A |

If phase 2 fails, repeat it once in each fallback mode before you change anything else:
`GATT_ONLY_WHEN_NO_PHONES=True` (tier B), then `MODE="phone_priority"` (tier C), then `MODE="burst"` (tier D). These match the fallback tiers on the design Page.

### Pass/fail thresholds (`summarize.py`)
- No unplanned reboot: the boot counter is unchanged over the run.
- `/ping` success >= 99.5 %. p95 round trip <= 300 ms. No outage longer than 10 s (5 probes in a row).
- Server-side HTTP errors < 0.5 % of requests.
- Laptop is never dropped from the AP (check `/log` for any `wifi: leave` of the laptop's MAC).
- Peer heard with a max gap <= 60 s. At least 50 % of the other board's 5 s advert rotations heard.
- 0 BLE stalls. 0 scan or advert API errors.
- Free heap (sampled after `gc.collect()`) not trending down by more than 4 KB over the run.
- Board B: GATT transfers >= 95 % successful; note the worst-case time.

### Also record by hand
- Does the captive sheet pop up on iOS and on Android?
- Does the WebSocket connect inside the captive mini-browser, or only in the full browser? The page shows the transport.
- Page `gap_max_s` and `ws_reconnects` from each phone, as a screenshot at the end of the run.
- The `STAT` line at the start and at the end (`mem_min`, `peer_seq_missed`).

### Results to copy off the boards
`mpremote cp :/coex_log.csv coex_log_A.csv`, `mpremote cp :/coex_boot.txt .`, and the same for board B. Then run:
`python3 host/summarize.py probe_*.csv stats_*.jsonl coex_log_B.csv`

## Known limits of this test
- With `AP_PASSWORD=""`, the open-network call `ap.config(security=0)` is wrapped in try. If firmware rejects it,
  the AP falls back to the MicroPython default WPA2 key (`picoW123`), and the log line says so.
- In phase 5a the laptop probe fails for 20 s every cycle, which is expected. Judge 5a by the board counters, not by `summarize.py`.
- `ap.config(pm=PM_NONE)` on the AP interface may be ignored. That's harmless.
- The Wi-Fi join and leave log comes from polling the station list once a second. There are no driver events behind it.
- Write-without-response back-pressure is handled by catching `OSError` and backing off 20 ms. If the first GATT runs
  show ENOMEM storms, lower `GATT_BYTES` or add a longer sleep.

## Flash with the web updater

1. Open https://your-server.example/?product=long-voyage in desktop Chrome, Edge or Brave.
2. If the board does not run MicroPython 1.29.0, follow the runtime steps on the page (BOOTSEL, then drag the UF2).
3. Connect device, then click Install latest (0.0.1-coex).
4. In SHIP CONFIG pick ship number, name, role A or B and (optional) hotspot password, then Save.
   The values go to `/data/ship.json` and `config.py` applies them at boot. Role A runs as COEX-0 and role B as COEX-1.
5. Click Disconnect. The board restarts and the test runs.

Logs: BENCH LOGS lists `coex_log.csv`, `coex_log.old` and `coex_boot.txt` and downloads them as
`coex_log_<role>ship<n>_<UTC time>.csv`. Connecting pauses the test (the updater turns the watchdog off for the
session) and the restart afterwards counts as a boot, so pull logs only at the end of a phase.
If the updater cannot turn the watchdog off, it writes `/data/maint` and resets. `main.py` then stops before starting
the test, once, so the REPL is free.
