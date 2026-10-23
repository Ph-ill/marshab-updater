# The bench status server for a board on stock MicroPython (Variant A, every module a file):
# the phone game (lvweb.py + lvphone.py) needs the game firmware's frozen core to fit in
# the heap, so here the hotspot serves only what the bench needs.
#   GET /, /status    one STAT line          GET /api/sync    status JSON
#   GET /api/gift?to=N  a bench gift from this ship's crew member
#   anything else     302 to /


async def handle(ship, reader, writer):
    try:
        line = await reader.readline()
        hdr = {}
        for _ in range(40):
            h = await reader.readline()
            if not h or h in (b"\r\n", b"\n"):
                break
            i = h.find(b":")
            if i > 0:
                k = str(h[:i].strip().lower(), "utf-8")
                if k.startswith("x-phone"):
                    hdr[k] = str(h[i + 1:].strip(), "utf-8")
        ship.clock.learn_headers(hdr.get)
        ship.http_hits += 1
        parts = str(line, "utf-8").split(" ")
        path = parts[1] if len(parts) > 1 else "/"
        code, body, ctype = 200, None, "application/json"
        if path.startswith("/api/gift"):
            q = path.split("to=")
            try:
                r = ship.gift(int(q[1].split("&")[0]) if len(q) > 1 else 0)
                body = '{"gift":"%s"}' % r.hex()
            except (ValueError, IndexError) as e:
                code, body = 400, '{"error":"%s"}' % e
        elif path.startswith("/api/sync"):
            import json
            body = json.dumps(ship.status())
        elif path == "/" or path.startswith("/status"):
            ctype, body = "text/plain", ship.stat_line() + "\n"
        else:
            code, body = 302, ""
        body = bytes(body, "utf-8")
        writer.write(bytes("HTTP/1.0 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n%s\r\n" % (
            code, ctype, len(body), "Location: /\r\n" if code == 302 else ""), "utf-8"))
        writer.write(body)
        await writer.drain()
    except Exception as e:      # one bad request never takes the server down
        ship.say("http: %s" % e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def server(ship):
    return lambda r, w: handle(ship, r, w)
