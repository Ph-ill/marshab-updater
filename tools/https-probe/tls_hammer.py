#!/usr/bin/env python3
"""Host-side client for tls_probe.py: N parallel HTTPS GETs (each a full TLS 1.2 handshake,
no session reuse, like a phone opening the page), repeated R rounds. Prints per-connection
handshake time, total time, bytes, failures, and the negotiated cipher.

    python3 tls_hammer.py --host 192.168.4.1 --port 443 -n 6 -r 3 [--ca testcert/ca.pem]
"""
import argparse, socket, ssl, threading, time

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="192.168.4.1")
ap.add_argument("--port", type=int, default=443)
ap.add_argument("--sni", default="voyage.coolphill.com")
ap.add_argument("-n", type=int, default=4, help="parallel connections per round")
ap.add_argument("-r", type=int, default=1, help="rounds")
ap.add_argument("--ca", default=None, help="verify against this CA (testcert/ca.pem); default: no verification")
ap.add_argument("--timeout", type=float, default=30)
ap.add_argument("--tls13", action="store_true", help="allow TLS 1.3 (the stock firmware is 1.2 only)")
a = ap.parse_args()

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
if a.ca:
    ctx.load_verify_locations(a.ca)
else:
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
if not a.tls13:
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
res = []
lock = threading.Lock()


def one(i):
    t0 = time.monotonic()
    r = {"i": i}
    try:
        raw = socket.create_connection((a.host, a.port), timeout=a.timeout)
        t1 = time.monotonic()
        s = ctx.wrap_socket(raw, server_hostname=a.sni)
        t2 = time.monotonic()
        r["cipher"] = "%s %s" % (s.version(), s.cipher()[0])
        s.sendall(b"GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % a.sni.encode())
        n = 0
        while True:
            b = s.recv(4096)
            if not b:
                break
            n += len(b)
        s.close()
        r.update(ok=True, tcp_ms=(t1 - t0) * 1000, hs_ms=(t2 - t1) * 1000,
                 total_ms=(time.monotonic() - t0) * 1000, bytes=n)
    except Exception as e:
        r.update(ok=False, err=repr(e), total_ms=(time.monotonic() - t0) * 1000)
    with lock:
        res.append(r)


for rnd in range(a.r):
    ts = [threading.Thread(target=one, args=(rnd * a.n + i,)) for i in range(a.n)]
    t0 = time.monotonic()
    [t.start() for t in ts]
    [t.join() for t in ts]
    print("round %d: %d connections in %.0f ms" % (rnd + 1, a.n, (time.monotonic() - t0) * 1000))
for r in sorted(res, key=lambda r: r["i"]):
    if r["ok"]:
        print("conn %3d ok   tcp %6.0f ms  handshake %6.0f ms  total %6.0f ms  %d B  %s" % (
            r["i"], r["tcp_ms"], r["hs_ms"], r["total_ms"], r["bytes"], r["cipher"]))
    else:
        print("conn %3d FAIL after %.0f ms: %s" % (r["i"], r["total_ms"], r["err"]))
ok = [r for r in res if r["ok"]]
if ok:
    hs = sorted(r["hs_ms"] for r in ok)
    print("SUMMARY ok=%d fail=%d handshake ms: min %.0f median %.0f max %.0f; total ms max %.0f" % (
        len(ok), len(res) - len(ok), hs[0], hs[len(hs) // 2], hs[-1], max(r["total_ms"] for r in ok)))
else:
    print("SUMMARY ok=0 fail=%d" % len(res))
