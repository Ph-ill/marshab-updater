# Heap-harness regressions (CPython): explicit busy refusals are not ambiguous POST
# failures, and a preempted/acknowledged notifier needs a fresh test stimulus.
# phone_flow.tcp stops reading once HTTP framing (Content-Length) proves the answer is
# complete, so a reset after any complete answer is not an error; a reset before the
# framed body is complete (or before any answer) still is.
import asyncio
import sys

sys.path[:0] = ["board", ".", "tests"]
import lvled
import lvlight
import lvweb
import phone_flow as F
from lv.clock import Clock


class Pin:
    def value(self, v):
        pass


class Timer:
    def ticks_us(self):
        return 0

    def ticks_diff(self, a, b):
        return a - b

    def sleep_us(self, n):
        pass


def notifier():
    t = [1000]
    old = lvled._t
    lvled._t = Timer()
    try:
        led = lvled.Led(Clock(ticks=lambda: t[0], diff=lambda a, b: a - b),
                        q=None, unknown=True, pin=lambda: Pin())
        led.set_enabled(True)
        led.note("test")
        led.note("gift")
        led.poll(False)                   # consumes test on its first, dark frame
        sh = type("Ship", (), {"led": led})()
        lvlight._hold(sh)                  # a Hail/Test-light playback preempts it
        led.note("seen")                  # a signed-in phone acknowledges the gift
        t[0] += 10000
        lvlight._hold(sh, True)

        def drain():
            end = t[0] + 9000
            while t[0] < end:
                t[0] += min(100, max(1, led.poll(False)))

        drain()
        assert led.writes == 0            # legal idle, not a task that failed to run
        led.note("test")                  # mp_sync_heap's independent final stimulus
        drain()
        assert led.writes >= 6
    finally:
        lvled._t = old


async def reset_response(raw, status):
    class Reader:
        async def read(self, n):
            if self.raw:
                b, self.raw = self.raw, b""
                return b
            raise ConnectionResetError(104, "reset")

    class Writer:
        closed = False

        def write(self, b):
            pass

        async def drain(self):
            pass

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    r, w = Reader(), Writer()
    r.raw = raw
    original = asyncio.open_connection

    async def connect(*a):
        return r, w

    asyncio.open_connection = connect
    try:
        try:
            answer = await F.tcp(1)("POST", "/api/login", b"{}")
        except ConnectionResetError:
            assert status is None
        else:
            assert status is not None and answer[0] == status
        assert w.closed
    finally:
        asyncio.open_connection = original


async def sockets():
    sh = type("Ship", (), {"http_hits": 0})()
    web = lvweb.Server(sh, say=lambda s: None)
    server = await asyncio.start_server(web.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    peers = []
    try:
        for _ in range(4):
            peers.append(await asyncio.open_connection("127.0.0.1", port))
        while web.busy < 4:
            await asyncio.sleep(0.001)
        for _ in range(10):
            s, _, _ = await F.tcp(port)("POST", "/api/login", b'{"crew":1,"pin":"1234"}')
            assert s == 503
        assert web.refused == 10
    finally:
        for _, w in peers:
            w.close()
            await w.wait_closed()
        server.close()
        await server.wait_closed()


async def main():
    await reset_response(b'HTTP/1.0 503 Busy\r\nContent-Length: 2\r\n\r\n{}', 503)
    await reset_response(b'HTTP/1.0 503 Busy\r\nContent-Length: 3\r\n\r\n{}', None)
    await reset_response(b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}', 200)
    await reset_response(b'HTTP/1.0 200 OK\r\nContent-Length: 3\r\n\r\n{}', None)
    await reset_response(b"", None)
    await sockets()


notifier()
asyncio.run(main())
print("heap timing: notifier preemption, complete 503/reset, ambiguous resets, real socket admission: PASS")
