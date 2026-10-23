# Coexistence soak test settings. Per-board values (role, ship number, hotspot password) normally come from
# /data/ship.json, written by the web updater; the overrides at the bottom of this file apply them.
# Without that file, edit SHIP_ID per board (0 and 1) and copy with mpremote as before.
SHIP_ID = 0                 # 0 = board A, 1 = board B (B is the GATT central when GATT_TEST is on)
SSID_PREFIX = "COEX-"       # AP name becomes COEX-0 / COEX-1
AP_PASSWORD = "CHANGE_ME"   # WPA2 placeholder; this file is public, so set the real per-board
                            # password in /data/ship.json (see data/ship.example.json). "" = open
AP_CHANNEL = 6              # fixed channel; repeat the soak on 1 and 11 if 6 is crowded
COUNTRY = "US"
AP_CYCLE_S = 0              # >0: every AP_CYCLE_S seconds turn the AP off for AP_OFF_S (tests the "hotspot button")
AP_OFF_S = 20

BLE_ENABLE = True           # False = phase 0 Wi-Fi-only baseline

# Scheduling mode for BLE scanning:
#   "concurrent"     scan all the time at the duty cycle below (the design's default)
#   "phone_priority" scan only while no phone is associated with the AP
#   "burst"          scan BURST_ON_S seconds out of every BURST_PERIOD_S
MODE = "concurrent"
SCAN_INTERVAL_MS = 300      # scan window opens this often
SCAN_WINDOW_MS = 30         # and listens this long (30/300 = 10 % duty)
SCAN_ACTIVE = False         # passive: never send scan requests
BURST_ON_S = 10
BURST_PERIOD_S = 60

ADV_INTERVAL_MS = 1000      # advert interval
ADV_ROTATE_S = 5            # re-issue gap_advertise with a new sequence number this often
ADV_CONNECTABLE = True      # must be True for the GATT test; False tests the pure-broadcast design

GATT_TEST = True            # board 1 connects to board 0 and pushes GATT_BYTES periodically
GATT_PERIOD_S = 300
GATT_BYTES = 8192
GATT_ONLY_WHEN_NO_PHONES = False   # True = the fallback rule "no GATT while a phone is connected"

STALL_PEER_S = 60           # log a stall if the other board is not heard for this long while scanning
STALL_SILENT_S = 30         # log a stall if NO advert of any kind is heard for this long while scanning
STAT_EVERY_S = 60           # stats line to USB serial
FLASH_EVERY_S = 600         # stats row appended to /coex_log.csv
FLASH_LOG_MAX = 180_000     # bytes; rotates to /coex_log.old
USE_WDT = True              # hardware watchdog (8 s); a reset counts as a failure in the results

# ---------------------------------------------------------------- per-ship overrides (web updater)
# /data/ship.json survives firmware updates. Keys: ship_id (1-7), ship_name, role ("A"/"B"),
# hotspot_password (optional, 8-63 chars), hotspot_open (optional, true = no password).
SHIP_NUM = 0
SHIP_NAME = ""
try:
    import json as _json
    with open("/data/ship.json") as _f:
        _ship = _json.load(_f)
    SHIP_NUM = int(_ship.get("ship_id") or 0)
    SHIP_NAME = str(_ship.get("ship_name") or "")
    _role = str(_ship.get("role") or "").upper()
    if _role in ("A", "B"):
        SHIP_ID = 0 if _role == "A" else 1
    # Hotspot stays WPA2 with AP_PASSWORD above unless ship.json sets its own 8-63 char password,
    # or explicitly asks for an open network with "hotspot_open": true.
    _pw = str(_ship.get("hotspot_password") or "")
    if _ship.get("hotspot_open") is True:
        AP_PASSWORD = ""
    elif 8 <= len(_pw) <= 63:
        AP_PASSWORD = _pw
    del _json, _f, _ship, _role, _pw
except Exception:  # a broken ship.json must never stop the board booting
    pass
