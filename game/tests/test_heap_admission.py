#!/usr/bin/env python3
"""R1: reject expensive overlap before allocating; release admission on errors."""
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
    names = {"ota_hooks", "clock_gate", "_Hdr", "net_hooks"}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    g = {"reboot": None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), g)

    async def send(w, status, body=b"", **kwargs):
        w.append((status, kwargs.get("extra", "")))

    wire = NS(send=send, dns_answer=lambda q, ip: None)
    web = NS(route=route, ship=NS(clock=None, ledtest=None))
    g["ota_hooks"](wire, web)
    return web


def request(path="/api/state"):
    return NS(path=path, method="GET")


class Admission(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_response_refused_before_allocation(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def route(req, w):
            calls.append(req.path)
            entered.set()
            await release.wait()

        web = hooks(route)
        running = asyncio.create_task(web.route(request(), []))
        await entered.wait()
        try:
            for path in ("/api/state", "/api/login", "/api/live", "/api/ota/put"):
                answer = []
                await web.route(request(path), answer)
                self.assertEqual(answer, [(503, "Retry-After: 1\r\n")])
            self.assertEqual(calls, ["/api/state"])
        finally:
            release.set()
            await running
        self.assertFalse(web.state_busy)

    async def test_upload_and_light_admission_and_recovery(self):
        calls = []

        async def route(req, w):
            calls.append(req.path)

        web = hooks(route)
        web.ota_busy = 1
        for path in ("/api/state", "/api/live"):
            answer = []
            await web.route(request(path), answer)
            self.assertEqual(answer[0][0], 503)
        web.ota_busy = 0
        web.ship.ledtest = 123
        answer = []
        await web.route(request(), answer)
        self.assertEqual(answer[0][0], 503)
        self.assertFalse(calls)
        web.ship.ledtest = None
        await web.route(request(), [])
        self.assertEqual(calls, ["/api/state"])

    async def test_failed_writer_releases_admission(self):
        async def route(req, w):
            raise OSError("phone disconnected")

        web = hooks(route)
        with self.assertRaises(OSError):
            await web.route(request(), [])
        self.assertFalse(web.state_busy)


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
