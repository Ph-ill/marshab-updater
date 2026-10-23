# Pico W / Pico 2 W Wi-Fi SoftAP + BLE coexistence soak test (MicroPython >= 1.26, tested target 1.29.0).
# Runs: SoftAP (WPA2 or open), catch-all DNS, HTTP captive page (+ /ws WebSocket), BLE advertise + duty-cycled
# passive scan, optional periodic GATT bulk write between the two boards. Logs everything that matters.
# Updater maintenance hook: the web updater drops /data/maint and resets the board when it needs a quiet REPL
# (for example if it could not stop the watchdog). The flag is single-use, so a half-finished update never
# leaves the board stuck: the next normal power-up runs the test again.
# (Not SystemExit: on rp2 that triggers a soft reset, which would rerun main.py and start the test anyway.)
class MaintenanceBoot(Exception):
    pass
try:
    import os as _os
    _os.stat("/data/maint")
    _os.remove("/data/maint")
    _maint = True
except OSError:
    _maint = False
if _maint:
    raise MaintenanceBoot("test not started, watchdog not armed; REPL is free for the updater")

import gc, time, struct, json, machine, network, bluetooth, binascii
import asyncio
import config as C

T0 = time.ticks_ms()
def up_s():
    return time.ticks_diff(time.ticks_ms(), T0) // 1000

# ---------------------------------------------------------------- logging
RING = []
def log(*a):
    line = "%7d " % up_s() + " ".join(str(x) for x in a)
    print(line)
    RING.append(line)
    if len(RING) > 120:
        RING.pop(0)

def _boot_count():
    n = 0
    try:
        with open("/coex_boot.txt") as f:
            n = int(f.read().strip() or 0)
    except OSError:
        pass
    n += 1
    with open("/coex_boot.txt", "w") as f:
        f.write(str(n))
    return n

S = {  # every counter the summary needs
    "boot": _boot_count(), "reset_cause": machine.reset_cause(),
    "mem_free": 0, "mem_min": 1 << 30,
    "stations": 0, "sta_joins": 0, "sta_leaves": 0, "sta_max": 0,
    "http_req": 0, "http_err": 0, "http_ms_max": 0, "dns_q": 0,
    "ws_open": 0, "ws_total": 0, "ws_msgs": 0,
    "adv_updates": 0, "adv_err": 0,
    "scan_on": False, "scan_starts": 0, "scan_err": 0, "scan_results": 0, "scan_ours": 0,
    "peer_seen": 0, "peer_last": -1, "peer_gap_max": 0, "peer_seq_missed": 0, "peer_rssi": 0,
    "stall_peer": 0, "stall_silent": 0,
    "ap_next": C.AP_CYCLE_S, "ap_cycles": 0, "ap_cycle_err": 0,
    "gatt_try": 0, "gatt_ok": 0, "gatt_fail": 0, "gatt_ms_last": 0, "gatt_ms_max": 0, "gatt_rx_bytes": 0,
}

def mem_sample():
    gc.collect()
    f = gc.mem_free()
    S["mem_free"] = f
    if f < S["mem_min"]:
        S["mem_min"] = f

# ---------------------------------------------------------------- Wi-Fi first
try:
    network.country(C.COUNTRY)
except Exception:
    try:
        import rp2
        rp2.country(C.COUNTRY)
    except Exception:
        pass

ap = network.WLAN(network.AP_IF)
SSID = C.SSID_PREFIX + str(C.SHIP_ID)
if C.AP_PASSWORD:
    ap.config(essid=SSID, password=C.AP_PASSWORD, channel=C.AP_CHANNEL)
else:
    ap.config(essid=SSID, channel=C.AP_CHANNEL)
    try:
        ap.config(security=0)          # open network
    except Exception as e:
        log("open-ap config failed (AP may fall back to the default WPA2 key):", e)
ap.active(True)
for _ in range(100):
    if ap.active():
        break
    time.sleep_ms(100)
try:
    ap.config(pm=network.WLAN.PM_NONE)  # no Wi-Fi power save on the AP side
except Exception as e:
    log("pm config not supported on AP:", e)
IP = ap.ifconfig()[0]
log("AP up", SSID, "ch", C.AP_CHANNEL, "ip", IP, "boot", S["boot"], "reset_cause", S["reset_cause"])

# ---------------------------------------------------------------- BLE second, activated exactly once
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3
_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6
_IRQ_PERIPHERAL_CONNECT = 7
_IRQ_PERIPHERAL_DISCONNECT = 8
_IRQ_GATTC_READ_RESULT = 15
_IRQ_GATTC_READ_DONE = 16
_IRQ_MTU_EXCHANGED = 21

MAGIC = b"LV"                       # manufacturer-data tag the two boards look for
COMPANY = b"\xff\xff"               # 0xFFFF = test/unassigned company id
SVC = bluetooth.UUID("7a1c0001-5e1f-4c6b-9d36-0c0e5e1f0001")
CHR = bluetooth.UUID("7a1c0002-5e1f-4c6b-9d36-0c0e5e1f0001")

ble = bluetooth.BLE()
H_CHR = 0
if C.BLE_ENABLE:
    ble.active(True)
    try:
        ble.config(gap_name=SSID, mtu=131)
    except Exception:
        ble.config(gap_name=SSID)
    ((H_CHR,),) = ble.gatts_register_services(((SVC, ((CHR, bluetooth.FLAG_READ | bluetooth.FLAG_WRITE_NO_RESPONSE),)),))
    ble.gatts_set_buffer(H_CHR, 256)
    ble.gatts_write(H_CHR, struct.pack("<I", 0))
    log("BLE up, addr", binascii.hexlify(ble.config("mac")[1]).decode(), "chr handle", H_CHR)
else:
    log("BLE disabled (phase 0 baseline)")

seq = 0
last_any_adv = time.ticks_ms()
peer_last_ms = None
peer_last_seq = None
peer_addr = None   # (addr_type, addr bytes)
G = {"conn": None, "mtu": 23, "read": None, "state": "idle"}   # GATT client state
rx_bytes_session = 0
P_CONN = [False]   # we are the peripheral in a GATT connection

def adv_payload():
    md = COMPANY + MAGIC + struct.pack("<BIH", C.SHIP_ID, seq, min(up_s() // 60, 65535))
    p = b"\x02\x01\x06" + bytes((len(md) + 1, 0xFF)) + md
    name = SSID.encode()
    return p + bytes((len(name) + 1, 0x09)) + name

def parse_ours(adv):
    i = 0
    n = len(adv)
    while i + 1 < n:
        ln = adv[i]
        if ln == 0:
            break
        if adv[i + 1] == 0xFF and ln >= 12 and adv[i + 2:i + 6] == COMPANY + MAGIC:
            sid, sq, _ = struct.unpack("<BIH", adv[i + 6:i + 13])
            return sid, sq
        i += ln + 1
    return None

def bt_irq(event, data):
    global last_any_adv, peer_last_ms, peer_last_seq, peer_addr, rx_bytes_session
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv = data
        S["scan_results"] += 1
        last_any_adv = time.ticks_ms()
        r = parse_ours(bytes(adv))
        if r is None:
            return
        S["scan_ours"] += 1
        sid, sq = r
        if sid == C.SHIP_ID:
            return
        now = time.ticks_ms()
        if peer_last_ms is not None:
            gap = time.ticks_diff(now, peer_last_ms) // 1000
            if gap > S["peer_gap_max"]:
                S["peer_gap_max"] = gap
        if peer_last_seq is not None and sq > peer_last_seq + 1:
            S["peer_seq_missed"] += sq - peer_last_seq - 1   # whole advert rotations never heard
        if peer_last_seq is None or sq != peer_last_seq:
            S["peer_seen"] += 1
        peer_last_seq = sq
        peer_last_ms = now
        S["peer_rssi"] = rssi
        peer_addr = (addr_type, bytes(addr))
    elif event == _IRQ_SCAN_DONE:
        S["scan_on"] = False
    elif event == _IRQ_CENTRAL_CONNECT:
        rx_bytes_session = 0
        P_CONN[0] = True
        log("gatt: central connected")
    elif event == _IRQ_CENTRAL_DISCONNECT:
        P_CONN[0] = False
        log("gatt: central disconnected, rx", rx_bytes_session)
    elif event == _IRQ_GATTS_WRITE:
        conn, h = data
        if h == H_CHR:
            n = len(ble.gatts_read(H_CHR))
            rx_bytes_session += n
            S["gatt_rx_bytes"] += n
            ble.gatts_write(H_CHR, struct.pack("<I", rx_bytes_session))
    elif event == _IRQ_PERIPHERAL_CONNECT:
        conn, _, _ = data
        G["conn"] = conn
        G["state"] = "connected"
    elif event == _IRQ_PERIPHERAL_DISCONNECT:
        G["conn"] = None
        G["state"] = "idle"
    elif event == _IRQ_MTU_EXCHANGED:
        G["mtu"] = data[1]
    elif event == _IRQ_GATTC_READ_RESULT:
        G["read"] = bytes(data[2])
    elif event == _IRQ_GATTC_READ_DONE:
        if G["read"] is None:
            G["read"] = b""

if C.BLE_ENABLE:
    ble.irq(bt_irq)

def advertise():
    global seq
    seq += 1
    try:
        ble.gap_advertise(C.ADV_INTERVAL_MS * 1000, adv_data=adv_payload(), connectable=C.ADV_CONNECTABLE)
        S["adv_updates"] += 1
    except Exception as e:
        S["adv_err"] += 1
        log("adv error", e)

def scan(on):
    if on == S["scan_on"]:
        return
    try:
        if on:
            ble.gap_scan(0, C.SCAN_INTERVAL_MS * 1000, C.SCAN_WINDOW_MS * 1000, C.SCAN_ACTIVE)
            S["scan_starts"] += 1
        else:
            ble.gap_scan(None)
        S["scan_on"] = on
    except Exception as e:
        S["scan_err"] += 1
        log("scan error", on, e)

def want_scan():
    if G["state"] != "idle":
        return False
    if C.MODE == "phone_priority":
        return S["stations"] == 0
    if C.MODE == "burst":
        return (up_s() % C.BURST_PERIOD_S) < C.BURST_ON_S
    return True

# ---------------------------------------------------------------- tasks
async def ble_task():
    global last_any_adv
    stall_peer_open = False
    stall_silent_open = False
    t_adv = 0
    while True:
        if time.ticks_diff(time.ticks_ms(), t_adv) >= C.ADV_ROTATE_S * 1000 and G["state"] == "idle" and not P_CONN[0]:
            advertise()
            t_adv = time.ticks_ms()
        scan(want_scan())
        if S["scan_on"]:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_any_adv) > C.STALL_SILENT_S * 1000:
                if not stall_silent_open:
                    S["stall_silent"] += 1
                    stall_silent_open = True
                    log("STALL silent: no adverts of any kind for", C.STALL_SILENT_S, "s while scanning")
            else:
                stall_silent_open = False
            if peer_last_ms is not None and time.ticks_diff(now, peer_last_ms) > C.STALL_PEER_S * 1000:
                if not stall_peer_open:
                    S["stall_peer"] += 1
                    stall_peer_open = True
                    log("STALL peer: other board not heard for", C.STALL_PEER_S, "s")
            else:
                stall_peer_open = False
        else:
            last_any_adv = time.ticks_ms()   # don't count time spent not scanning
        await asyncio.sleep_ms(500)

async def gatt_task():
    if not C.GATT_TEST or C.SHIP_ID != 1:
        return
    await asyncio.sleep(30)
    while True:
        await asyncio.sleep(C.GATT_PERIOD_S)
        if C.GATT_ONLY_WHEN_NO_PHONES and S["stations"]:
            continue
        if peer_addr is None or peer_last_ms is None or time.ticks_diff(time.ticks_ms(), peer_last_ms) > 3000:
            log("gatt: skip, peer not heard in last 3 s")
            continue
        S["gatt_try"] += 1
        t = time.ticks_ms()
        ok = await gatt_push()
        ms = time.ticks_diff(time.ticks_ms(), t)
        if ok:
            S["gatt_ok"] += 1
            S["gatt_ms_last"] = ms
            S["gatt_ms_max"] = max(S["gatt_ms_max"], ms)
        else:
            S["gatt_fail"] += 1
        log("gatt push", "ok" if ok else "FAIL", ms, "ms mtu", G["mtu"])
        if G["conn"] is not None:
            try:
                ble.gap_disconnect(G["conn"])
            except Exception:
                pass
        for _ in range(40):
            if G["conn"] is None:
                break
            await asyncio.sleep_ms(50)
        G["state"] = "idle"

async def gatt_push():
    G["state"] = "connecting"
    scan(False)
    await asyncio.sleep_ms(50)
    try:
        ble.gap_connect(peer_addr[0], peer_addr[1], 2000)
    except Exception as e:
        log("gatt connect error", e)
        return False
    for _ in range(60):
        if G["conn"] is not None:
            break
        await asyncio.sleep_ms(50)
    if G["conn"] is None:
        try:
            ble.gap_connect(None)        # cancel the pending connection
        except Exception:
            pass
        return False
    try:
        ble.gattc_exchange_mtu(G["conn"])
        await asyncio.sleep_ms(300)
    except Exception:
        pass
    chunk = bytes(max(20, G["mtu"] - 3))
    sent = 0
    deadline = time.ticks_add(time.ticks_ms(), 20000)
    while sent < C.GATT_BYTES:
        if G["conn"] is None or time.ticks_diff(deadline, time.ticks_ms()) < 0:
            return False
        try:
            ble.gattc_write(G["conn"], H_CHR, chunk, 0)   # peer has the same handle: same firmware
            sent += len(chunk)
        except OSError:
            await asyncio.sleep_ms(20)                   # controller buffers full, back off
            continue
        await asyncio.sleep_ms(0)
    await asyncio.sleep_ms(500)
    G["read"] = None
    try:
        ble.gattc_read(G["conn"], H_CHR)
    except Exception:
        return False
    for _ in range(40):
        if G["read"] is not None:
            break
        await asyncio.sleep_ms(50)
    if not G["read"] or len(G["read"]) < 4:
        return False
    got = struct.unpack("<I", G["read"][:4])[0]
    if got < sent:
        log("gatt: peer counted", got, "of", sent)
    return got >= sent

async def wifi_task():
    known = set()
    while True:
        try:
            st = ap.status("stations")
        except Exception:
            st = []
        now = set()
        for x in st:
            mac = x[0] if isinstance(x, tuple) else x
            now.add(binascii.hexlify(mac).decode())
        for m in now - known:
            S["sta_joins"] += 1
            log("wifi: join", m)
        for m in known - now:
            S["sta_leaves"] += 1
            log("wifi: leave", m)
        known = now
        S["stations"] = len(now)
        S["sta_max"] = max(S["sta_max"], len(now))
        if C.AP_CYCLE_S and up_s() >= S["ap_next"]:
            S["ap_next"] = up_s() + C.AP_CYCLE_S
            try:
                ap.active(False)
                await asyncio.sleep(C.AP_OFF_S)
                ap.active(True)
                for _ in range(50):
                    if ap.active():
                        break
                    await asyncio.sleep_ms(100)
                S["ap_cycles"] += 1
                log("wifi: AP cycled", S["ap_cycles"], "active", ap.active())
            except Exception as e:
                S["ap_cycle_err"] += 1
                log("wifi: AP cycle error", e)
            known = set()
        await asyncio.sleep(1)

async def dns_task():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 53))
    s.setblocking(False)
    ip = bytes(int(x) for x in IP.split("."))
    while True:
        try:
            q, addr = s.recvfrom(512)
        except OSError:
            await asyncio.sleep_ms(20)
            continue
        if len(q) < 12:
            continue
        S["dns_q"] += 1
        i = 12
        while i < len(q) and q[i] != 0:
            i += q[i] + 1
        qend = i + 5
        r = q[:2] + b"\x81\x80" + q[4:6] + q[4:6] + b"\x00\x00\x00\x00" + q[12:qend]
        r += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + ip
        try:
            s.sendto(r, addr)
        except OSError:
            pass

PAGE = None
def page():
    global PAGE
    if PAGE is None:
        with open("/index.html", "rb") as f:
            PAGE = f.read()
    return PAGE

def stats_json():
    d = dict(S)
    d["uptime_s"] = up_s()
    d["ship"] = C.SHIP_ID
    d["ship_num"] = getattr(C, "SHIP_NUM", 0)
    d["ship_name"] = getattr(C, "SHIP_NAME", "")
    d["mode"] = C.MODE
    d["peer_age_s"] = -1 if peer_last_ms is None else time.ticks_diff(time.ticks_ms(), peer_last_ms) // 1000
    return json.dumps(d)

CAPTIVE = (b"/generate_204", b"/gen_204", b"/hotspot-detect.html", b"/library/test/success.html",
           b"/connecttest.txt", b"/ncsi.txt", b"/redirect", b"/canonical.html", b"/success.txt")

async def send(w, status, ctype, body, extra=b""):
    w.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: " + ctype + b"\r\nContent-Length: " +
            str(len(body)).encode() + b"\r\nCache-Control: no-store\r\nConnection: close\r\n" + extra + b"\r\n")
    w.write(body)
    await w.drain()

async def http_handler(r, w):
    t = time.ticks_ms()
    S["http_req"] += 1
    upgraded = False
    try:
        line = await asyncio.wait_for_ms(r.readline(), 5000)
        parts = line.split()
        path = parts[1] if len(parts) > 1 else b"/"
        hdr = {}
        while True:
            h = await asyncio.wait_for_ms(r.readline(), 5000)
            if not h or h == b"\r\n":
                break
            k, _, v = h.partition(b":")
            hdr[k.strip().lower()] = v.strip()
        path = path.split(b"?")[0]
        if path in CAPTIVE:
            await send(w, b"302 Found", b"text/plain", b"", b"Location: http://" + IP.encode() + b"/\r\n")
        elif path == b"/":
            await send(w, b"200 OK", b"text/html; charset=utf-8", page())
        elif path == b"/ping":
            await send(w, b"200 OK", b"text/plain", b"ok")
        elif path == b"/api/stats":
            await send(w, b"200 OK", b"application/json", stats_json().encode())
        elif path == b"/log":
            await send(w, b"200 OK", b"text/plain", "\n".join(RING).encode())
        elif path == b"/ws" and hdr.get(b"upgrade", b"").lower() == b"websocket":
            upgraded = True
            await ws_session(r, w, hdr.get(b"sec-websocket-key", b""))
        else:
            await send(w, b"302 Found", b"text/plain", b"", b"Location: http://" + IP.encode() + b"/\r\n")
    except Exception as e:
        S["http_err"] += 1
    finally:
        if not upgraded:
            ms = time.ticks_diff(time.ticks_ms(), t)
            if ms > S["http_ms_max"]:
                S["http_ms_max"] = ms
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass

def ws_frame(payload):
    n = len(payload)
    if n < 126:
        return bytes((0x81, n)) + payload
    return bytes((0x81, 126)) + struct.pack(">H", n) + payload

async def ws_session(r, w, key):
    import hashlib
    acc = binascii.b2a_base64(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()).strip()
    w.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
    await w.drain()
    S["ws_open"] += 1
    S["ws_total"] += 1
    try:
        while True:
            try:
                b0 = await asyncio.wait_for_ms(r.readexactly(1), 2000)   # 1 byte: a timeout can't split a header
            except asyncio.TimeoutError:
                w.write(ws_frame(stats_json().encode()))     # push stats every 2 s of silence
                await w.drain()
                continue
            h = b0 + await r.readexactly(1)
            op = h[0] & 0x0F
            n = h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", await r.readexactly(2))[0]
            elif n == 127:
                break
            mask = await r.readexactly(4) if h[1] & 0x80 else b"\0\0\0\0"
            data = bytearray(await r.readexactly(n))
            for i in range(n):
                data[i] ^= mask[i & 3]
            if op == 0x8:
                break
            if op == 0x9:
                w.write(bytes((0x8A, n)) + data)
            elif op == 0x1:
                S["ws_msgs"] += 1
                w.write(ws_frame(bytes(data)))   # echo: client measures round trip
            await w.drain()
    finally:
        S["ws_open"] -= 1

async def stats_task():
    t_flash = time.ticks_ms()
    while True:
        await asyncio.sleep(C.STAT_EVERY_S)
        mem_sample()
        log("STAT", stats_json())
        if time.ticks_diff(time.ticks_ms(), t_flash) >= C.FLASH_EVERY_S * 1000:
            t_flash = time.ticks_ms()
            flash_row()

FIELDS = ("uptime_s", "boot", "mem_free", "mem_min", "stations", "sta_joins", "sta_leaves", "http_req",
          "http_err", "http_ms_max", "ws_total", "scan_results", "scan_ours", "peer_seen", "peer_age_s",
          "peer_gap_max", "peer_seq_missed", "stall_peer", "stall_silent", "scan_err", "adv_err",
          "gatt_try", "gatt_ok", "gatt_fail", "gatt_ms_max", "ap_cycles", "ap_cycle_err")

def flash_row():
    import os
    d = json.loads(stats_json())
    try:
        if os.stat("/coex_log.csv")[6] > C.FLASH_LOG_MAX:
            os.rename("/coex_log.csv", "/coex_log.old")
    except OSError:
        pass
    new = False
    try:
        os.stat("/coex_log.csv")
    except OSError:
        new = True
    with open("/coex_log.csv", "a") as f:
        if new:
            f.write(",".join(FIELDS) + "\n")
        f.write(",".join(str(d.get(k, "")) for k in FIELDS) + "\n")

async def wdt_task():
    if not C.USE_WDT:
        return
    wdt = machine.WDT(timeout=8000)
    while True:
        wdt.feed()          # only fed while the asyncio loop is alive
        await asyncio.sleep_ms(1000)

async def main():
    mem_sample()
    asyncio.create_task(wdt_task())
    asyncio.create_task(wifi_task())
    asyncio.create_task(dns_task())
    if C.BLE_ENABLE:
        asyncio.create_task(ble_task())
        asyncio.create_task(gatt_task())
    asyncio.create_task(stats_task())
    await asyncio.start_server(http_handler, "0.0.0.0", 80, backlog=4)
    log("running mode", C.MODE, "scan", C.SCAN_WINDOW_MS, "/", C.SCAN_INTERVAL_MS, "ms adv", C.ADV_INTERVAL_MS, "ms")
    flash_row()
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
