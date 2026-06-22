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

Stub content lives in `content/*.json`. `content/content_manifest.json` enumerates every ID, context, max length, and trigger. A writer can replace values in those JSON files using the same keys. Run:

```bash
python3 validate_content.py
```

to report missing or extra IDs.

## Offline progress

The browser sends `Date.now()` to `/api/sync`. The Pico clamps elapsed wall time to 30 days and advances resources with closed-form math; it never loops per second.
