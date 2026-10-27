# TLS server probe for the Pico W (lv-core firmware = MicroPython v1.29.0, stock mbedTLS
# config) and the unix probe build. Starts a minimal HTTPS server with a test cert and logs,
# per connection: gc.mem_free() before accept / after wrap / after handshake / after the
# response, the handshake time and the total time. Ends with a summary line.
#
#   Pico:  mpremote connect <PORT> cp testcert/fullchain.pem :/probe_cert.pem
#          mpremote connect <PORT> cp testcert/privkey.pem  :/probe_key.pem
#          mpremote connect <PORT> run tls_probe.py          (see README.md)
#   unix:  micropython-tls32 -X heapsize=193k tls_probe.py [seq|async] [port] [cert key]
#
# Modes: seq   one connection at a time, blocking handshake (clean timing + heap per step)
#        async asyncio.start_server(ssl=ctx) like lvweb would, at most MAX_CONN at once;
#              tracks the lowest gc.mem_free() seen while connections are in flight.
# Settings below can be changed before `mpremote run` (or exec'd first, see README).
import gc, sys, time, socket

MODE = "seq"            # or "async"
PORT = 443
CERT = "/probe_cert.pem"
KEY = "/probe_key.pem"
BODY = 16384            # response size (the phone page is ~15-25 KB gzipped)
CONNS = 20              # stop after this many connections (seq) / seconds idle (async)
MAX_CONN = 4            # async: accept at most this many at once (the rest wait in the backlog)
AP_SSID = "LV-TLSPROBE" # Pico only: open AP, 192.168.4.1; nothing else runs
IDLE_S = 60

# Overrides without editing this file (mpremote keeps globals between commands in one call):
#   mpremote connect <PORT> exec "PROBE={'cert':'/probe_cert.pem','key':'/probe_key.pem','mode':'async'}" run tls_probe.py
try:
    _o = PROBE      # noqa: F821
except NameError:
    _o = {}
MODE = _o.get("mode", MODE)
PORT = _o.get("port", PORT)
CERT = _o.get("cert", CERT)
KEY = _o.get("key", KEY)
BODY = _o.get("body", BODY)
CONNS = _o.get("conns", CONNS)
IDLE_S = _o.get("idle_s", IDLE_S)
AP_SSID = _o.get("ssid", AP_SSID)

if sys.platform == "linux" and not _o:
    CERT = "testcert/fullchain.pem"
    KEY = "testcert/privkey.pem"
    PORT = 8443
    if len(sys.argv) > 1:
        MODE = sys.argv[1]
    if len(sys.argv) > 2:
        PORT = int(sys.argv[2])
    if len(sys.argv) > 4:
        CERT, KEY = sys.argv[3], sys.argv[4]

try:
    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
except AttributeError:
    ticks_ms = lambda: int(time.time() * 1000)
    ticks_diff = lambda a, b: a - b


def free():
    gc.collect()
    return gc.mem_free()


def log(*a):
    print("PROBE", *a)


def start_ap():
    try:
        import network, machine
    except ImportError:
        return "0.0.0.0"
    log("cpu_hz", machine.freq())
    ap = network.WLAN(network.AP_IF)
    ap.config(ssid=AP_SSID, security=0)
    ap.active(True)
    while not ap.active():
        time.sleep_ms(100)
    ip = ap.ifconfig()[0]
    log("ap", AP_SSID, ip)
    return "0.0.0.0"


def make_ctx():
    import ssl
    f0 = free()
    t = ticks_ms()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with open(CERT, "rb") as f:
        cert = f.read()
    with open(KEY, "rb") as f:
        key = f.read()
    ctx.load_cert_chain(cert, key)
    del cert, key
    f1 = free()
    log("ctx heap=%d B load_ms=%d" % (f0 - f1, ticks_diff(ticks_ms(), t)))
    return ctx


CHUNK = memoryview(b"x" * 512)   # slicing a memoryview allocates nothing
HDR = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"


def respond(s):
    s.write(HDR % BODY)
    n = BODY
    while n > 0:
        k = min(n, 512)
        s.write(CHUNK[:k])
        n -= k


def seq(ctx, host):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(socket.getaddrinfo(host, PORT)[0][-1])
    srv.listen(2)
    log("listening", PORT, "mode seq")
    worst_hs = 0
    worst_heap = 0
    hs_sum = 0
    done = 0
    while done < CONNS:
        f0 = free()
        c, addr = srv.accept()
        t0 = ticks_ms()
        c.settimeout(10)
        try:
            s = ctx.wrap_socket(c, server_side=True, do_handshake_on_connect=False)
            f1 = gc.mem_free()
            t1 = ticks_ms()
            req = s.read(1)         # the handshake runs here (blocking socket)
            t2 = ticks_ms()
            f2 = gc.mem_free()
            while req and not req.endswith(b"\r\n\r\n"):
                b = s.read(1)
                if not b:
                    break
                req += b
            respond(s)
            f3 = gc.mem_free()
            t3 = ticks_ms()
            s.close()
        except Exception as e:
            log("conn error", repr(e))
            try:
                c.close()
            except Exception:
                pass
            continue
        hs = ticks_diff(t2, t1)
        used = f0 - min(f1, f2, f3)   # heap held by the live connection (handshake temporaries are gone by then)
        worst_hs = max(worst_hs, hs)
        worst_heap = max(worst_heap, used)
        hs_sum += hs
        done += 1
        log("conn %d free_before=%d after_wrap=%d after_hs=%d after_resp=%d held=%d hs_ms=%d total_ms=%d free_after_close=%d"
            % (done, f0, f1, f2, f3, used, hs, ticks_diff(t3, t0), free()))
    srv.close()
    log("SUMMARY seq conns=%d hs_ms_avg=%d hs_ms_max=%d held_max=%d free_now=%d" % (
        done, hs_sum // max(done, 1), worst_hs, worst_heap, free()))


def run_async(ctx, host):
    try:
        import asyncio
    except ImportError:
        import uasyncio as asyncio
    st = {"busy": 0, "peak_busy": 0, "low": free(), "served": 0, "err": 0, "last": ticks_ms(),
          "hs": []}
    base = st["low"]

    async def handle(r, w):
        st["busy"] += 1
        st["peak_busy"] = max(st["peak_busy"], st["busy"])
        t0 = ticks_ms()
        try:
            line = await r.readline()      # handshake happens inside the first read
            st["hs"].append(ticks_diff(ticks_ms(), t0))
            st["low"] = min(st["low"], gc.mem_free())
            while True:
                l = await r.readline()
                if not l or l == b"\r\n":
                    break
            w.write(HDR % BODY)
            n = BODY
            while n > 0:
                k = min(n, 512)
                w.write(CHUNK[:k])
                await w.drain()
                st["low"] = min(st["low"], gc.mem_free())
                n -= k
            st["served"] += 1
        except Exception as e:
            st["err"] += 1
            log("conn error", repr(e))
        finally:
            st["low"] = min(st["low"], gc.mem_free())
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
            st["busy"] -= 1
            st["last"] = ticks_ms()

    async def main():
        srv = await asyncio.start_server(handle, host, PORT, backlog=8, ssl=ctx)
        log("listening", PORT, "mode async (note: start_server wraps every accepted socket;"
            " MAX_CONN is not enforced before the TLS buffers are allocated)")
        while ticks_diff(ticks_ms(), st["last"]) < IDLE_S * 1000:
            await asyncio.sleep_ms(200)
            st["low"] = min(st["low"], gc.mem_free())
        srv.close()

    asyncio.run(main())
    hs = st["hs"] or [0]
    log("SUMMARY async served=%d errors=%d peak_concurrent=%d heap_base=%d lowest_free=%d"
        " max_used=%d hs_ms_avg=%d hs_ms_max=%d" % (
            st["served"], st["err"], st["peak_busy"], base, st["low"], base - st["low"],
            sum(hs) // len(hs), max(hs)))


log("start", sys.implementation, "free", free())
host = start_ap()
ctx = make_ctx()
if MODE == "async":
    run_async(ctx, host)
else:
    seq(ctx, host)
