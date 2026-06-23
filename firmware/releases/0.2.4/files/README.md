# Mars Hab incremental Pico W game

A self-contained MicroPython idle/incremental game for Raspberry Pi Pico W. The Pico serves a WiFi AP and vanilla browser SPA; the device is authoritative for state.

## Run / flash

Install a recent Raspberry Pi Pico W MicroPython build, then copy all files from this payload to the device filesystem. Boot `main.py`. Join the AP shown in the serial log and open `http://192.168.4.1`.

## Config constants

Global tuning lives in `config.py`: catch-up clamp, tick interval, persistence interval, load-screen minimum, ports, AP IP, schema versions and protected paths.

## Provisioning per board

Per-device identity lives only in `data/device.json`. First boot creates a default from `machine.unique_id()`. To provision one of the nine boards, POST `/api/provision` with `hab_name`, `signature_resource`, `ap_ssid`, and optional `ap_password`, or edit `data/device.json` over USB before gifting. Firmware updates must never overwrite `data/`.

## Protected updater paths

The updater must preserve and never delete:

- `data/device.json`
- `data/device.bak`
- `data/save.json`
- `data/save.bak`
- `data/passport.json`
- everything under `data/`

The firmware payload intentionally excludes `data/`.

## Content workflow

Stub content lives in `content/*.json`. `content/content_manifest.json` is generated from the engine's authoritative hooks in `content_schema.py`; do not pad the manifest with unused IDs. A writer can replace values in those JSON files using the same keys.

The content surface is structured so the story can grow without engine edits:

- `events`: weighted ambient pools (`weather`, `colony_life`, `equipment`, `anomaly`, `discovery`) with act gates. These are world happenings, not button-tap results.
- `actions`: one canonical `act_<name>` entry per action, with `label`, `flavor`, and `result_1..result_4` variants for immediate tap feedback.
- `away`: composable while-away fragments selected from gated pools during closed-form catch-up.
- `archive`: ordered multi-strand mystery/codex chains (`arc_<strand>_<NN>`) unlocked progressively by act/counters.
- `beats`: act transitions plus internal milestone beats.
- `letters`: recurring senders (`ltr_<sender>_<NN>`) unlocked across the arc.
- `ending`: ordered `end_<NN>_<name>` payoff sequence for the reveal, terraforming climax, and epilogue.
- `ui`: labels, headers, buttons, tooltips, and short system copy.

Run:

```bash
python3 validate_content.py
```

to report missing content, stale extra content, manifest IDs with no engine hook, engine hooks missing from the manifest, and broken pools/chains/sequences.

## Offline progress

The browser sends `Date.now()` to `/api/sync`. The Pico clamps elapsed wall time to 30 days and advances resources with closed-form math; it never loops per second.
