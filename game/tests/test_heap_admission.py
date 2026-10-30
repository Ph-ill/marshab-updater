#!/usr/bin/env python3
"""R1 (reworked in 0.3.0 review 2 M2-M4): one streamed state at a time, other API calls
refused with 503 + Retry-After (which the page and ota.js replay) while one streams, light
playback holds nothing off; admission released on errors."""
import ast
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "board")]


def hooks(route):
    source = ROOT / "board/main.py"
    tree = ast.parse(source.read_text())
    names = {"ota_hooks", "clock_gate", "_Hdr", "net_hooks", "http_admission"}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    clock = [0]

    async def sleep_ms(ms):
        clock[0] += ms
        await asyncio.sleep(0)

    g = {"reboot": None, "asyncio": asyncio, "lvship": NS(ticks_ms=lambda: clock[0], ticks_diff=lambda a, b: a - b,
                                      sleep_ms=sleep_ms, drop=lambda n: None, free=lambda: 100000)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), g)
    g["_clock"] = clock

    async def send(w, status, body=b"", **kwargs):
        w.append((status, kwargs.get("extra", "")))

    wire = NS(send=send, dns_answer=lambda q, ip: None)
    web = NS(route=route, ship=NS(clock=None, ledtest=None))
    g["ota_hooks"](wire, web)
    assert wire.MAX_CONN == 1
    web.clock = clock
    return web


def request(path="/api/state"):
    return NS(path=path, method="GET")


class Admission(unittest.IsolatedAsyncioTestCase):
    async def test_browser_startup_burst_queues_unread_with_one_owner(self):
        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        scope = {"asyncio": asyncio}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        entered, release = asyncio.Event(), asyncio.Event()
        parsed, closed, answers = [], [], []

        async def handle(reader, writer):
            parsed.append(reader)
            entered.set()
            await release.wait()

        async def close(writer):
            closed.append(writer)

        async def send(writer, status, body=b"", **kwargs):
            answers.append((status, kwargs.get("extra")))

        web = NS(handle=handle, _close=close, refused=0)
        scope["http_admission"](NS(send=send), web)
        first = asyncio.create_task(web.handle(1, 1))
        await entered.wait()
        waiting = [asyncio.create_task(web.handle(n, n)) for n in range(2, 9)]
        await asyncio.sleep(0)
        self.assertEqual(web.http_waiting, 8)
        self.assertEqual(parsed, [1])
        await web.handle(9, 9)
        self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
        self.assertEqual(closed, [9])
        release.set()
        await asyncio.gather(first, *waiting)
        self.assertEqual(parsed, list(range(1, 9)))
        self.assertEqual(web.http_waiting, 0)

    async def test_upload_retries_instead_of_owning_http_while_light_plays(self):
        from unittest.mock import AsyncMock, patch
        import lvotaq

        async def route(req, writer):
            self.fail("upload must use its own handler")

        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: 0)
        web.ship.ledtest = 0
        req = NS(path="/api/ota/put", method="POST", q={}, body=b"piece")
        answers = []
        quiet = AsyncMock()
        upload = AsyncMock(return_value="uploaded")
        with patch.object(lvotaq, "quiet", quiet), \
                patch.dict(sys.modules, {"lvotap": NS(api=upload)}):
            await web.route(req, answers)
            self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
            quiet.assert_not_awaited()
            upload.assert_not_awaited()
            self.assertEqual(web.ota_busy, 0)
            web.ship.ledtest = None
            self.assertEqual(await web.route(req, answers), "uploaded")
            quiet.assert_awaited_once()
            upload.assert_awaited_once()
            self.assertEqual(web.ota_busy, 0)

    async def test_unread_waiter_deadline_refuses_and_closes(self):
        answers, closed = [], []

        async def timeout(coro, seconds):
            self.assertEqual(seconds, 15)
            coro.close()
            raise asyncio.TimeoutError

        async def handle(reader, writer):
            self.fail("timed-out admission must not read the request")

        async def close(writer):
            closed.append(writer)

        async def send(writer, status, body=b"", **kwargs):
            answers.append((status, kwargs.get("extra")))

        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        scope = {"asyncio": NS(Lock=asyncio.Lock, wait_for=timeout, TimeoutError=asyncio.TimeoutError)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        web = NS(handle=handle, _close=close, refused=0)
        scope["http_admission"](NS(send=send), web)
        await web.handle(1, 1)
        self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
        self.assertEqual(closed, [1])
        self.assertEqual(web.http_waiting, 0)
        self.assertEqual(web.refused, 1)


    async def test_cancelled_unread_waiter_closes_and_releases_slot(self):
        entered, release = asyncio.Event(), asyncio.Event()
        closed = []

        async def handle(reader, writer):
            entered.set()
            await release.wait()

        async def close(writer):
            closed.append(writer)

        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        scope = {"asyncio": asyncio}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        web = NS(handle=handle, _close=close)
        scope["http_admission"](NS(), web)
        first = asyncio.create_task(web.handle(1, 1))
        await entered.wait()
        waiting = asyncio.create_task(web.handle(2, 2))
        await asyncio.sleep(0)
        self.assertEqual(web.http_waiting, 2)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(closed, [2])
        self.assertEqual(web.http_waiting, 1)
        release.set()
        await first
        await web.handle(3, 3)
        self.assertEqual(web.http_waiting, 0)

    async def test_unread_waiter_does_not_parse_or_count_as_web_busy(self):
        from unittest.mock import patch
        import lvweb
        entered, release = asyncio.Event(), asyncio.Event()
        parsed, answers, closed = [], [], []
        web = lvweb.Server(NS(http_hits=0), say=lambda s: None)

        async def read_req(reader):
            parsed.append(reader)
            return request("/")

        async def route(req, writer):
            entered.set()
            await release.wait()

        async def send(writer, status, body=b"", **kwargs):
            answers.append((status, kwargs.get("extra")))

        async def close(writer):
            closed.append(writer)

        source = ROOT / "board/main.py"
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        scope = {"asyncio": asyncio}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        web.route, web._close = route, close
        scope["http_admission"](lvweb, web, slots=2)
        with patch.object(lvweb, "MAX_CONN", 1), \
                patch.object(lvweb, "read_req", read_req), \
                patch.object(lvweb, "send", send):
            first = asyncio.create_task(web.handle(1, 1))
            await entered.wait()
            waiting = asyncio.create_task(web.handle(2, 2))
            await asyncio.sleep(0)
            self.assertEqual(web.http_waiting, 2)
            self.assertEqual(web.busy, 1)
            self.assertEqual(parsed, [1])
            await web.handle(3, 3)
            self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
            self.assertEqual(closed, [3])
            release.set()
            await asyncio.gather(first, waiting)
        self.assertEqual(parsed, [1, 2])
        self.assertEqual(web.served, 2)
        self.assertEqual(web.busy, 0)
        self.assertEqual(web.http_waiting, 0)

    async def test_single_socket_refuses_second_before_parsing(self):
        from unittest.mock import patch
        import lvweb
        entered, release = asyncio.Event(), asyncio.Event()
        parsed, answers = [], []
        web = lvweb.Server(NS(http_hits=0), say=lambda s: None)

        async def read_req(reader):
            parsed.append(reader)
            return request("/api/login")

        async def route(req, writer):
            entered.set()
            await release.wait()

        async def send(writer, status, body=b"", **kwargs):
            answers.append((status, kwargs.get("extra")))

        web.route = route
        with patch.object(lvweb, "MAX_CONN", 1), \
                patch.object(lvweb, "read_req", read_req), \
                patch.object(lvweb, "send", send):
            running = asyncio.create_task(web.handle(1, NS()))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await web.handle(2, NS())
                self.assertEqual(parsed, [1])
                self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
                self.assertEqual(web.busy, 1)
                self.assertEqual(web.refused, 1)
            finally:
                release.set()
                await running
        self.assertEqual(web.busy, 0)
        self.assertEqual(web.served, 1)

    async def test_socket_admission_refuses_third_before_parsing(self):
        from unittest.mock import patch
        import lvweb
        entered, release = asyncio.Event(), asyncio.Event()
        parsed, answers = [], []
        web = lvweb.Server(NS(http_hits=0), say=lambda s: None)

        async def read_req(reader):
            parsed.append(reader)
            return request("/api/login")

        async def route(req, writer):
            if len(parsed) == 2:
                entered.set()
            await release.wait()

        async def send(writer, status, body=b"", **kwargs):
            answers.append((status, kwargs.get("extra")))

        web.route = route
        with patch.object(lvweb, "MAX_CONN", 2), \
                patch.object(lvweb, "read_req", read_req), \
                patch.object(lvweb, "send", send):
            running = [asyncio.create_task(web.handle(n, NS())) for n in (1, 2)]
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await web.handle(3, NS())
                self.assertEqual(parsed, [1, 2])
                self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
                self.assertEqual(web.busy, 2)
                self.assertEqual(web.refused, 1)
            finally:
                release.set()
                await asyncio.gather(*running)
        self.assertEqual(web.busy, 0)
        self.assertEqual(web.served, 2)

    async def test_overlap_is_refused_with_retry_after_before_loading(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def route(req, w):
            calls.append(req.path)
            if req.path == "/api/state" and len(calls) == 1:
                entered.set()
                await release.wait()

        web = hooks(route)
        running = asyncio.create_task(web.route(request(), []))
        await entered.wait()
        self.assertTrue(web.radio_hold)
        for path in ("/api/state", "/api/login", "/api/crew", "/api/ota", "/api/live"):
            answer = []
            await web.route(request(path), answer)
            self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])   # replayed by api()/otaFetch
        self.assertEqual(calls, ["/api/state"])     # nothing else allocates mid-stream
        release.set()
        await running
        self.assertFalse(web.state_busy)
        self.assertFalse(web.radio_hold)
        await web.route(request("/api/login"), [])
        self.assertEqual(calls, ["/api/state", "/api/login"])

    async def test_live_stream_holds_radio_until_snapshot_is_released(self):
        from unittest.mock import patch
        import lvliveapi

        async def route(req, w):
            self.fail("live should use its streaming handler")

        async def live(*args):
            self.assertTrue(web.radio_hold)

        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: None)
        with patch.object(lvliveapi, "live", live):
            await web.route(request("/api/live"), [])
        self.assertFalse(web.radio_hold)

    async def test_failed_live_stream_releases_radio_and_http_admission(self):
        from unittest.mock import patch
        import lvliveapi

        async def route(req, w):
            self.fail("live must use its streaming handler")

        async def live(*args):
            self.assertTrue(web.radio_hold)
            self.assertTrue(web.state_busy)
            raise asyncio.CancelledError

        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: None)
        with patch.object(lvliveapi, "live", live):
            with self.assertRaises(asyncio.CancelledError):
                await web.route(request("/api/live"), [])
        self.assertFalse(web.radio_hold)
        self.assertFalse(web.state_busy)

    async def test_authenticated_snapshot_precedes_encoder_import(self):
        import builtins
        from unittest.mock import patch
        events = []
        snapshot = ([], [], [], [], None, {"duel": []})

        async def route(req, w):
            self.fail("live must use its streaming handler")

        def prepare(sh, maintained):
            self.assertTrue(maintained)
            self.assertEqual(events, [])
            events.append("prepare")
            return snapshot

        async def live(wire, got, req, writer, maintained, prepared):
            self.assertIs(prepared, snapshot)
            self.assertEqual(events, ["prepare", "encoder"])
            self.assertTrue(got.radio_hold)

        original = builtins.__import__

        def importing(name, *args, **kwargs):
            if name == "lvliveapi":
                events.append("encoder")
            return original(name, *args, **kwargs)

        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: 0)
        web.ship.live = None
        web.ship.clock = NS(learn_headers=lambda h: False)
        req = NS(path="/api/live", method="GET", header=None)
        with patch.dict(sys.modules, {"lvliveops": NS(_prep=prepare), "lvliveapi": NS(live=live)}), \
                patch.object(builtins, "__import__", importing):
            await web.route(req, [])
        self.assertFalse(web.radio_hold)
        self.assertFalse(web.state_busy)

    async def test_live_stream_refuses_an_existing_radio_session_before_loading(self):
        from unittest.mock import patch
        import lvliveapi

        async def route(req, w):
            self.fail("live must use its streaming handler")

        async def live(*args):
            self.fail("an active radio session must exclude the encoder")

        web = hooks(route)
        web.ship.ble = NS(state="sync")
        web.get_phone = lambda: NS(who=lambda req: None)
        answers = []
        with patch.object(lvliveapi, "live", live):
            await web.route(request("/api/live"), answers)
        self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
        self.assertFalse(web.radio_hold)
        self.assertFalse(web.state_busy)

    async def test_continuous_live_streams_give_radio_reveal_an_unread_turn(self):
        from unittest.mock import patch
        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        events, clock = [], [0]
        ble = NS(state="idle")

        async def quiet(ms):
            self.assertEqual(web.busy, 0)
            self.assertFalse(web.radio_hold)
            self.assertEqual(web.http_waiting, 2)
            clock[0] += ms
            events.append("radio")
            # An idle radio still needs a sender's retry. The next queued
            # phone must remain unread until that reveal makes receive progress.
            if clock[0] >= 300:
                ble.state = "idle"
                web.ship.live.n["in"] += 1
            await asyncio.sleep(0)

        scope = dict(asyncio=asyncio, lvship=NS(sleep_ms=quiet,
                     ticks_ms=lambda: clock[0], ticks_diff=lambda a, b: a - b))
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        entered, release = asyncio.Event(), asyncio.Event()
        async def route(req, writer):
            self.fail("live must use its streaming handler")
        web = hooks(route)
        web.ship.ble = ble
        web.ship.live = NS(n={"held": 0, "in": 0})
        web.busy = 0
        web.refused = 0
        web.get_phone = lambda: NS(who=lambda req: None)

        async def live(*args):
            self.assertTrue(web.radio_hold)
            events.append("live")
            if len(events) == 1:
                web.ship.live.n["held"] += 1
            entered.set()
            await release.wait()

        async def handle(reader, writer):
            web.busy += 1
            try:
                await web.route(request("/api/live"), writer)
            finally:
                web.busy -= 1

        web.handle = handle
        scope["http_admission"](NS(), web)
        import lvliveapi
        with patch.object(lvliveapi, "live", live):
            first = asyncio.create_task(web.handle(None, []))
            await entered.wait()
            second = asyncio.create_task(web.handle(None, []))
            await asyncio.sleep(0)
            release.set()
            # The final request also receives a quiet turn, with no waiter.
            original = scope["lvship"].sleep_ms
            async def turns(ms):
                if events.count("live") == 1:
                    await original(ms)
                else:
                    self.assertEqual(web.busy, 0)
                    self.assertFalse(web.radio_hold)
            scope["lvship"].sleep_ms = turns
            await asyncio.gather(first, second)
        self.assertEqual(events, ["live", "radio", "radio", "radio", "live"])
        self.assertEqual(ble.state, "idle")
        self.assertEqual(web.http_waiting, 0)

    async def test_deferred_radio_turn_is_bounded_when_the_sender_disappears(self):
        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        clock = [0]
        async def quiet(ms):
            self.assertEqual(web.busy, 0)
            self.assertFalse(web.radio_hold)
            clock[0] += ms
        async def handle(reader, writer):
            web.radio_turn = True
            web.radio_retry = 7
        scope = dict(asyncio=asyncio, lvship=NS(sleep_ms=quiet,
                     ticks_ms=lambda: clock[0], ticks_diff=lambda a, b: a - b))
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        web = NS(handle=handle, busy=0, radio_hold=False,
                 ship=NS(ble=NS(state="idle"), live=NS(n={"in": 7})))
        scope["http_admission"](NS(), web)
        await web.handle(None, None)
        self.assertEqual(clock[0], 15250)
        self.assertIsNone(web.radio_retry)
        self.assertFalse(web.radio_pending)
        self.assertEqual(web.http_waiting, 0)

    async def test_live_snapshot_does_not_impose_a_fixed_retry_window(self):
        from unittest.mock import patch
        import lvliveapi
        calls = []

        async def route(req, w):
            calls.append(req.path)

        async def live(*args):
            self.assertTrue(web.radio_hold)
            calls.append("live")

        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: None)
        with patch.object(lvliveapi, "live", live):
            await web.route(request("/api/live"), [])
            answers = []
            await web.route(request("/api/live"), answers)
            self.assertEqual(answers, [])
            await web.route(request("/api/login"), [])
            web.clock[0] += 2000
            await web.route(request("/api/live"), [])
        self.assertEqual(calls, ["live", "live", "/api/login", "live"])
        self.assertFalse(web.radio_hold)

    async def test_active_radio_refuses_heavy_but_not_light_without_pending_turn(self):
        calls = []
        async def route(req, writer):
            calls.append(req.path)
        web = hooks(route)
        web.ship.ble = NS(state="sync")
        web.radio_pending = False
        for path in ("/api/state", "/api/live"):
            answers = []
            await web.route(request(path), answers)
            self.assertEqual(answers, [(503, "Retry-After: 1\r\n")])
        await web.route(request("/api/login"), [])
        self.assertFalse(web.radio_hold)
        web.ship.ble.state = "idle"
        await web.route(request("/api/state"), [])
        self.assertEqual(calls, ["/api/login", "/api/state"])
        self.assertFalse(web.radio_pending)

    async def test_failed_live_preparation_still_schedules_a_radio_turn(self):
        from unittest.mock import patch
        async def route(req, writer):
            self.fail("live must not dispatch here")
        web = hooks(route)
        web.get_phone = lambda: NS(who=lambda req: 0)
        web.ship.live = None
        web.ship.clock = NS(learn_headers=lambda h: False)
        def prepare(*args):
            raise MemoryError("snapshot")
        with patch.dict(sys.modules, {"lvliveops": NS(_prep=prepare)}):
            with self.assertRaises(MemoryError):
                await web.route(NS(path="/api/live", method="GET", header=None), [])
        self.assertTrue(web.radio_turn)
        self.assertFalse(web.radio_hold)

    async def test_cancelled_radio_turn_releases_admission_and_slot(self):
        source = ROOT / "board/main.py"
        node = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "http_admission")
        entered = asyncio.Event()
        async def quiet(ms):
            entered.set()
            await asyncio.Event().wait()
        async def handle(reader, writer):
            web.radio_turn = True
        scope = dict(asyncio=asyncio, lvship=NS(sleep_ms=quiet))
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        web = NS(handle=handle)
        scope["http_admission"](NS(), web)
        task = asyncio.create_task(web.handle(None, None))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(web.http_waiting, 0)
        # The captured handle schedules another turn; cancel it only after it
        # acquires admission, proving the lock was not leaked by cancellation.
        entered.clear()
        task = asyncio.create_task(web.handle(None, None))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(web.http_waiting, 0)

    async def test_cancelled_state_releases_radio(self):
        entered = asyncio.Event()

        async def route(req, w):
            entered.set()
            await asyncio.Event().wait()

        web = hooks(route)
        running = asyncio.create_task(web.route(request(), []))
        await entered.wait()
        self.assertTrue(web.radio_hold)
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertFalse(web.radio_hold)
        self.assertFalse(web.state_busy)

    async def test_update_piece_holds_only_state_and_live(self):
        calls = []

        async def route(req, w):
            calls.append(req.path)

        web = hooks(route)
        web.ota_busy = 1
        for path in ("/api/state", "/api/live"):
            answer = []
            await web.route(request(path), answer)
            self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])
        await web.route(request("/api/login"), [])
        await web.route(request("/api/crew"), [])
        self.assertEqual(calls, ["/api/login", "/api/crew"])
        web.ota_busy = 0
        await web.route(request(), [])
        self.assertEqual(calls, ["/api/login", "/api/crew", "/api/state"])

    async def test_light_playback_does_not_hold_state_off(self):
        # review 2 M2: a hail's flicker (up to ~40 s) or Test light (10 s) no longer 503s
        # /api/state or /api/live, nor any other call
        calls = []

        async def route(req, w):
            calls.append(req.path)

        web = hooks(route)
        web.ship.ledtest = 123
        for path in ("/api/state", "/api/login", "/api/crew"):
            answer = []
            await web.route(request(path), answer)
            self.assertEqual(answer, [])
        self.assertEqual(calls, ["/api/state", "/api/login", "/api/crew"])
        self.assertFalse(web.state_busy)

    async def test_failed_writer_releases_admission(self):
        async def route(req, w):
            raise OSError("phone disconnected")

        web = hooks(route)
        with self.assertRaises(OSError):
            await web.route(request(), [])
        self.assertFalse(web.state_busy)
        self.assertFalse(web.radio_hold)

    async def test_stalled_stream_frees_other_phones_after_the_write_deadline(self):
        # review 3 MAJOR-1: a phone that stops reading mid-/api/state (out of range, screen
        # locked) used to hold every other phone's /api/* off until lwIP gave up (minutes).
        # Each stream write now waits at most lvstateapi.DRAIN_MS; then the stream fails (its
        # socket is closed by lvweb.Server.handle) and admission is released.
        import time
        import lvstateapi

        class Stalled:
            def write(self, b):
                pass

            async def drain(self):
                await asyncio.Event().wait()       # never takes another byte

        calls = []

        async def route(req, w):
            calls.append(req.path)
            if req.path == "/api/state":
                await lvstateapi.drain(Stalled())

        saved = lvstateapi.DRAIN_MS
        lvstateapi.DRAIN_MS = 200
        try:
            web = hooks(route)
            t0 = time.monotonic()
            stuck = asyncio.create_task(web.route(request(), []))
            await asyncio.sleep(0.02)
            answer = []
            await web.route(request("/api/login"), answer)
            self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])     # held while it streams
            with self.assertRaises(asyncio.TimeoutError):
                await stuck
            self.assertLess(time.monotonic() - t0, 2.0)       # the deadline, not minutes
            self.assertFalse(web.state_busy)
            answer = []
            await web.route(request("/api/login"), answer)
            self.assertEqual(answer, [])
            self.assertEqual(calls, ["/api/state", "/api/login"])
        finally:
            lvstateapi.DRAIN_MS = saved

    async def test_live_stream_writes_use_the_deadline(self):
        # GET /api/live (and the radio test's ping) stream through lvliveapi.wdrain
        import lvliveapi

        class Stalled:
            async def drain(self):
                await asyncio.Event().wait()

        class Moving:
            n = 0

            async def drain(self):
                Moving.n += 1

        saved = lvliveapi.DRAIN_MS
        lvliveapi.DRAIN_MS = 50
        try:
            with self.assertRaises(asyncio.TimeoutError):
                await lvliveapi.wdrain(Stalled())
            await lvliveapi.wdrain(Moving())
            self.assertEqual(Moving.n, 1)
        finally:
            lvliveapi.DRAIN_MS = saved

    def test_lvweb_left_as_frozen(self):
        # lvweb is frozen in the lv-core firmware: changing it ships a ~4 KB .mpy kept in RAM
        # (the review 3 heap runs went 76.5 -> 80.5 KB), so the deadline lives in the stream
        # modules instead
        src = (ROOT / "board/lvweb.py").read_text()
        self.assertNotIn("DRAIN_MS", src)

    async def test_stale_busy_mark_is_ignored_after_20_s(self):
        # the backstop: a state_busy mark that somehow outlived its stream holds nobody off
        # for more than ~20 s
        calls = []

        async def route(req, w):
            calls.append(req.path)

        web = hooks(route)
        web.clock[0] = 1000
        web.state_busy = 1000
        answer = []
        await web.route(request("/api/login"), answer)
        self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])
        web.clock[0] = 1000 + 19000
        answer = []
        await web.route(request("/api/login"), answer)
        self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])
        web.clock[0] = 1000 + 20001
        answer = []
        await web.route(request("/api/login"), answer)
        self.assertEqual(answer, [])
        self.assertEqual(calls, ["/api/login"])


class SplitHelpers(unittest.TestCase):

    def test_envelope_releases_request_body_before_verification(self):
        from unittest.mock import patch
        import lvota
        import lvotap
        req = NS(body=b"test envelope chunk")
        received = []

        def append(q, off, body):
            received.append(body)
            return None

        def verify(*args):
            self.assertEqual(req.body, b"")
            return True

        with patch.object(lvota, "env_piece", append), \
                patch.object(lvota, "envelope_prep", lambda p: ("hash", b"message", b"signature", b"public", None)), \
                patch.object(lvota, "envelope_done", lambda *args: (200, {"ok": args[2]})), \
                patch.object(lvotap, "_verify", verify):
            self.assertEqual(lvotap.put({"f": "0", "o": "0"}, None, req), (200, {"ok": True}))
        self.assertEqual(received, [b"test envelope chunk"])

    def test_prepare_hotspot_and_story(self):
        from unittest.mock import patch
        import lvsetup
        cfg = {"hotspot": True}
        ap = NS(ifconfig=lambda: ("192.168.4.7",))
        made = []
        board = NS(phone_game=lambda c: True, Ship=lambda c, days: made.append(days) or "ship")
        with patch.object(lvsetup, "lvship", board), patch.dict(sys.modules, {
                "lvwifi": NS(hotspot=lambda c: ap), "lvdays": NS(Days=lambda p: ("days", p))}):
            self.assertEqual(lvsetup.prepare(cfg), ("ship", ap, "192.168.4.7", True))
            self.assertEqual(made, [("days", "/data/days.bin")])
            cfg["hotspot"] = False
            self.assertEqual(lvsetup.prepare(cfg), ("ship", None, "192.168.4.1", False))
            self.assertIsNone(made[-1])

    def test_look_drops_new_submodules_from_their_package(self):
        # review 3 nit-3: lvotak._look frees a submodule its import brought in, from
        # sys.modules and from the package that also holds it as an attribute
        import tempfile
        import lvotak
        with tempfile.TemporaryDirectory() as d:
            os_ = __import__("os")
            os_.mkdir(os_.path.join(d, "pkgr3"))
            open(os_.path.join(d, "pkgr3", "__init__.py"), "w").close()
            open(os_.path.join(d, "pkgr3", "sub.py"), "w").write("X = 1\n")
            open(os_.path.join(d, "lvr3probe.py"), "w").write("from pkgr3 import sub\nOK = sub.X\n")
            sys.path.insert(0, d)
            try:
                import pkgr3
                lvotak._look("lvr3probe", ("OK",))
                self.assertNotIn("lvr3probe", sys.modules)
                self.assertNotIn("pkgr3.sub", sys.modules)
                self.assertFalse(hasattr(pkgr3, "sub"))
                self.assertIn("pkgr3", sys.modules)         # loaded before: kept
            finally:
                sys.path.remove(d)
                for k in ("pkgr3", "pkgr3.sub", "lvr3probe"):
                    sys.modules.pop(k, None)

    def test_boot_fallback_and_safe_stop(self):
        from unittest.mock import patch
        import lvsetup
        cfg = {"ship_id": 4}
        drops, sleeps = [], []

        def missing(path):
            raise OSError("absent")

        def damaged(*args, **kwargs):
            raise ImportError("damaged boot checker")

        board = NS(load_config=lambda: cfg, DEFAULTS=cfg, drop=drops.append,
                   VERSION="test", free=lambda: 100000)
        filesystem = NS(stat=missing, mkdir=lambda p: None)
        with patch.object(lvsetup, "lvship", board), \
                patch.object(lvsetup, "os", filesystem), \
                patch.object(lvsetup, "time", NS(sleep_ms=sleeps.append)), \
                patch.dict(sys.modules, {"lvsafe": NS(check=damaged)}):
            # config's default dependency is the real board; replace just this binding
            # for the isolated boot test, as on a real boot both refer to the same board.
            original = lvsetup.config
            with patch.object(lvsetup, "config", lambda got: original(got, board)):
                self.assertEqual(lvsetup.boot(0, lambda p: False, self.fail), (cfg, False))
            self.assertIn("lvsafe", drops)
            self.assertIn("lvledcfg", drops)
            self.assertIsNone(lvsetup.boot(0, lambda p: p == "/data/safe", self.fail))
            self.assertEqual(sleeps, [0, 0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
