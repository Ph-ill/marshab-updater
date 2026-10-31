#!/usr/bin/env python3
"""Heap regression: measure three near-limit transcripts and durable reply intents."""
import ast
import asyncio
import json
from pathlib import Path
import sys
import time
import unittest
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "board")]


def functions(path, names, scope):
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    return scope


class WorstDuelHeap(unittest.TestCase):
    def test_outbound_helpers_are_not_retained_by_inbound_module(self):
        import lvlivein as inbound
        from unittest.mock import patch
        events = []
        def operation(*args):
            events.append(args)
            raise ValueError("failed operation")
        # Every compatibility call must release the extra module on failure.
        for name, args in (("dial", (1, 2, 3)), ("done", (1, 2, 3, 4, 5)),
                           ("failed", (1, 2, 3)), ("expire", (1,)), ("forget", (1,))):
            with patch.dict(sys.modules, {"lvlivex": NS(**{name: operation})}):
                with self.assertRaisesRegex(ValueError, "failed operation"):
                    getattr(inbound, name)(*args)
                self.assertNotIn("lvlivex", sys.modules)
            self.assertEqual(events[-1], args)

    def test_known_proof_bypasses_shot_and_recovery_modules(self):
        from unittest.mock import patch
        game = {"to": 1, "id": b"ab"}
        box = {"g": [game]}
        link = NS()
        body = b"ab" + bytes(9)
        calls = []
        scope = dict(box=lambda lk: box, sweep=lambda *a: False,
                     gid=lambda g: g["id"],
                     layout_call=lambda *a: calls.append(a) or (False, None))
        functions(ROOT / "board/lvduel.py", {"receive"}, scope)
        with patch.dict(sys.modules, {"lvduelrx": None, "lvduelother": None}):
            self.assertEqual(scope["receive"](link, 1, 7, body), (box, (False, None)))
        self.assertEqual(calls, [("proof", link, 1, body, box, game)])

    def test_socket_client_rejects_a_short_content_length_body(self):
        import phone_flow

        async def run():
            async def serve(reader, writer):
                await reader.readline()
                writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: 9\r\n\r\n{}")
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(serve, "127.0.0.1", 0)
            try:
                request = phone_flow.tcp(server.sockets[0].getsockname()[1])
                with self.assertRaisesRegex(EOFError, "incomplete HTTP response"):
                    await request("GET", "/api/live")
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(run())

    def test_test_peer_does_not_parse_while_its_previous_frames_wait(self):
        from unittest.mock import patch
        for stage in (0, 1):
            queued = [[0, b"frame"]]
            scope = dict(duel_peer_stage=[stage], peer_link=NS(out=queued))
            functions(ROOT / "tests/mp_sync_heap.py", {"duel_progress"}, scope)
            with patch.dict(sys.modules, {"lvduel": None}):
                scope["duel_progress"]()
            self.assertEqual(queued, [[0, b"frame"]])
            self.assertEqual(scope["duel_peer_stage"], [stage])

    def test_idle_maintenance_does_not_import_receive_rules(self):
        import builtins
        from unittest.mock import patch
        import lvlivein as I
        box = {"g": [{"id": "abcd", "to": 1, "i": 0, "n": 1,
                      "s": "active", "t": 1}], "r": {}}
        clock = NS(known=lambda: True, epoch_ms=lambda: 1000)
        link = NS(sh=NS(data="unused", clock=clock), duel_times={}, out=[], node=NS(ship=0))
        original = builtins.__import__

        def importing(name, *args, **kwargs):
            self.assertNotEqual(name, "lvduel", "ordinary maintenance loaded receive rules")
            return original(name, *args, **kwargs)

        with patch.object(I, "load", return_value=box), \
                patch.object(I, "save") as save, \
                patch.object(builtins, "__import__", importing):
            I.duel_maintain(link)
        save.assert_not_called()
        self.assertIn((1, "abcd"), link.duel_times)
        self.assertNotIn("lvduelmaint", sys.modules)
        self.assertNotIn("lvduelstore", sys.modules)

    def test_snapshot_operations_are_reclaimed_before_duel_view(self):
        import weakref
        from types import ModuleType
        from unittest.mock import patch
        import lvliveapi as A
        ops = ModuleType("lvliveops")
        box = {"g": [], "r": {}}
        snapshot = ([], [], [], [], None, {"duel": box})
        ops._prep = lambda *args: snapshot
        ref = weakref.ref(ops)
        calls = []

        def view(link, state):
            self.assertIs(state, box)
            self.assertNotIn("lvliveops", sys.modules)
            self.assertIsNone(ref(), "operation globals overlap view construction")
            calls.append(link)
            return []

        with patch.dict(sys.modules):
            sys.modules["lvliveops"] = ops
            sys.modules["lvduelview"] = NS(view=view)
            ops = None
            self.assertIs(A._prep(NS(live="link"), True), snapshot)
            self.assertEqual(calls, ["link"])
            self.assertEqual(snapshot[-1]["duel"], [])

    def test_replay_helper_is_released_before_intent_checkpoint(self):
        import weakref
        from types import ModuleType
        from unittest.mock import patch
        import lvlivein as I
        helper = ModuleType("lvduelstore")
        helper.cleanout = lambda *args: None
        helper.flush = lambda *args: True
        ref = weakref.ref(helper)
        saves = []

        def save(path, state):
            if saves:
                self.assertNotIn("lvduelstore", sys.modules)
                self.assertIsNone(ref(), "replay globals remain rooted at checkpoint")
            saves.append(state)

        box = {"g": [], "r": {}}
        link = NS(v=0, sh=NS(data="unused"))
        with patch.dict(sys.modules), patch.object(I, "save", save):
            sys.modules["lvduelstore"] = helper
            helper = None
            I.duel_store(link, box)
        self.assertEqual(saves, [box, box])
        self.assertEqual(link.v, 1)

    def test_radio_publication_releases_the_whole_rule_module(self):
        import builtins
        import weakref
        from types import ModuleType
        from unittest.mock import patch
        import lvlivein as I
        events = []
        box = {"g": [], "r": {}}
        rules = ModuleType("lvduel")
        rules.receive = lambda *args: (box, (True, None))
        ref = weakref.ref(rules)

        def store(link, state):
            self.assertNotIn("lvduel", sys.modules)
            self.assertIsNone(ref(), "receive globals remain rooted during save")
            self.assertIs(state, box)
            events.append("save")

        def load(path):
            events.append("parse")
            return box

        original_import = builtins.__import__

        def importing(name, *args, **kwargs):
            if name == "lvduel":
                self.assertEqual(events, ["parse"], "rules imported before box parsing")
                events.append("rules")
            return original_import(name, *args, **kwargs)

        link = NS(v=0, sh=NS(data="unused", duel_probe=lambda state: events.append("probe")))
        with patch.dict(sys.modules), patch.object(I, "load", load), \
                patch.object(I, "save", store), \
                patch.object(builtins, "__import__", importing):
            sys.modules["lvduel"] = rules
            rules = None
            sys.modules["lvduelstore"] = NS(cleanout=lambda *args: None, flush=lambda *args: None)
            self.assertTrue(I.duel_take(link, 1, 5, bytes(11)))
            self.assertNotIn("lvduelstore", sys.modules)
        self.assertEqual(events, ["parse", "rules", "save", "probe"])

    def test_active_maintenance_defers_but_expiry_and_clock_backfill_do_not(self):
        from unittest.mock import patch
        import lvduel as D
        calls = []
        link = NS(sh=NS(web=NS(busy=1), clock=NS(known=lambda: True, epoch_ms=lambda: 123000)), duel_due=100)
        def maintain(name, lk, value):
            calls.append(name)
            if name == "sweep":
                return True
            self.assertEqual(name, "reconcile_all")
            value = value["g"][0]
            t = 123 if lk.sh.clock.known() else None
            changed = value.get("t") is None and t is not None
            if changed:
                value["t"] = t
            return changed
        with patch.object(D, "maint_call", maintain):
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": 123}]}))
            self.assertEqual(calls, ["reconcile_all"])
            self.assertEqual(link.duel_due, 0)
            game = {"s": "active", "t": None}
            self.assertTrue(D.sweep(link, {"g": [game]}))
            self.assertEqual(game["t"], 123)
            self.assertEqual(calls, ["reconcile_all"] * 2)
            link.sh.clock.known = lambda: False
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": None}]}))
            for state, stamp in (("draft", 123), ("wait", 123), ("invited", 123)):
                self.assertTrue(D.sweep(link, {"g": [{"s": state, "t": stamp}]}))
            self.assertEqual(calls, ["reconcile_all"] * 3 + ["sweep"] * 3)
            link.sh.web.busy = 0
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": 123}]}, True))
            self.assertEqual(calls, ["reconcile_all"] * 3 + ["sweep"] * 3 + ["reconcile_all"])
            self.assertTrue(D.sweep(link, {"g": [{"s": "active", "t": 123}]}))
            self.assertEqual(calls, ["reconcile_all"] * 3 + ["sweep"] * 3 + ["reconcile_all", "sweep"])

    def test_ack_maintenance_retries_after_http_releases_snapshot(self):
        import tempfile
        from unittest.mock import patch
        import lvduel as D
        import lvlivein as I
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            (Path(tmp) / "duel.json").touch()
            link = NS(sh=NS(web=NS(busy=1), data=tmp), duel_due=100)
            with patch.object(I, "duel_maintain") as maintain:
                I.duels(link)
                maintain.assert_not_called()
                self.assertEqual(link.duel_due, 0)
                link.sh.web.busy = 0
                link.ble = NS(state="sync")
                I.duels(link)
                maintain.assert_not_called()
                link.ble.state = "idle"
                I.duels(link)
                maintain.assert_called_once_with(link)

    def test_poll_releases_item_module_before_core_receive(self):
        import weakref
        from types import ModuleType
        import lvlive

        def install():
            module = ModuleType("lvlivein")
            module.duels = lambda lk: None
            module.dial = lambda *args: None
            sys.modules["lvlivein"] = module
            return weakref.ref(module)

        previous = sys.modules.pop("lvlivein", None)
        try:
            for maintenance in (True, False):
                with self.subTest(maintenance=maintenance):
                    ref = install()
                    checked = []

                    def receive(now):
                        self.assertNotIn("lvlivein", sys.modules)
                        self.assertIsNone(ref(), "a dropped item module still roots its code during receive")
                        checked.append(now)

                    link = NS(ble=NS(state="idle"), duel_due=0 if maintenance else 200,
                              web_busy=lambda: False, out=[] if maintenance else [1],
                              due=0, want=lambda now: True, poll0=receive, hx=None)
                    lvlive.Link.poll(link, 100)
                    self.assertEqual(checked, [100])
        finally:
            sys.modules.pop("lvlivein", None)
            if previous is not None:
                sys.modules["lvlivein"] = previous

    def test_live_snapshot_operations_are_released_before_streaming(self):
        from unittest.mock import patch
        import lvliveapi
        import lvliveops
        snapshot = ([], [], [], [], None, {"duel": [], "on": True})
        writes = []
        owner = self

        class Writer:
            def write(self, data):
                owner.assertNotIn("lvliveops", sys.modules)
                writes.append(data)

            async def drain(self):
                owner.assertNotIn("lvliveops", sys.modules)

        web = NS(ship=NS(clock=NS(learn_headers=lambda h: False)),
                 get_phone=lambda: NS(who=lambda req: 0))
        wire = NS(head=lambda *args: b"header", probe=None)
        req = NS(header=lambda name: None)
        with patch.object(lvliveops, "_prep", lambda *args: snapshot):
            asyncio.run(lvliveapi.live(wire, web, req, Writer(), True))
        self.assertEqual(writes[0], b"header")
        self.assertTrue(json.loads(b"".join(writes[1:]))["on"])

    def test_signature_injection_skips_settings_self_check(self):
        from unittest.mock import patch
        calls = []
        link = NS(n={"held": 0, "in": 0})
        def take(session, frame, offset):
            calls.append(frame)
            link.n["held"] += 1
        link.take = take
        probe = lambda: None
        scope = dict(gc=NS(mem_alloc=lambda: 1), base=0, sys=sys, DUEL=False,
                     kpeak={}, peak=[2], HAIL_M=[b"frame"], hail_sig=[],
                     ship=NS(live=link), stream_sample=probe,
                     HailSes=lambda: NS(acks=[]))
        functions(ROOT / "tests/mp_sync_heap.py", {"sample"}, scope)
        with patch.dict(sys.modules, {"lvsig": NS(probe=None)}):
            scope["sample"]()
            self.assertEqual(calls, [])
            self.assertEqual(scope["hail_sig"], [])
            sys.modules["lvsig"].probe = probe
            scope["sample"]()
            self.assertEqual(calls, [b"frame"])
            self.assertEqual(scope["hail_sig"], [(1, 0, 0, "lvlivein" in sys.modules)])
            scope["sample"]()
            self.assertEqual(calls, [b"frame"])

    def test_seed_is_three_long_legal_games_with_durable_obligations(self):
        import tempfile
        import lvduel as D
        from lvlivein import load
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            import os
            os.mkdir(tmp + "/peer")
            def link(ship, data):
                clock = NS(known=lambda: True, epoch_ms=lambda: 1793000000000, date=lambda: 20261026)
                return NS(sh=NS(data=data, clock=clock, fk=b"heap-fixture-key"),
                          node=NS(ship=ship), out=[], inb=[], v=0, seq=0, ep=1,
                          nx={}, due=0, n={"out": 0}, hw={}, lc=[None, 0], duel_times={}, f=data + "/livebox.json")
            own, peer = link(0, tmp), link(1, tmp + "/peer")
            scope = functions(ROOT / "tests/mp_sync_heap.py", {"seed_duels"}, {})
            scope["seed_duels"](own, peer)
            box = load(tmp + "/duel.json")
            games = box["g"]
            self.assertEqual(len(box.get("e", [])), 7)
            self.assertEqual(len(box["r"]), 7)
            # The largest stub shape (review 0.3.1-9 #2), not one-END rejections.
            for g in box["e"]:
                self.assertEqual((g["s"], g["o"], g["rj"][1]), ("done", 1, 5))
                self.assertTrue(all(D.allowed(g, z[0]) for z in g["q"]))
                self.assertEqual([z[0] for z in g["q"]], [6, 7, 8])
                self.assertTrue(all(len(bytes.fromhex(z[1])) == 11 for z in g["q"]))
            self.assertEqual([g["to"] for g in games], [1, 2, 3])
            self.assertEqual([g["n"] for g in games], [68, 70, 70])
            for g in games:
                self.assertEqual(g["s"], "active")
                self.assertEqual(len(g["h"]), 2 * g["n"])
                self.assertTrue(g["q"])
                for kind, body in g["q"]:
                    self.assertEqual(kind, 9)
                    self.assertEqual(len(bytes.fromhex(body)), 11)
                fired = {False: [], True: []}
                layout = bytes.fromhex(g["l"])
                for n, cell, result in D.history(g):
                    side = D.mine(own, g, n)
                    self.assertNotIn(cell, fired[side])
                    self.assertEqual(result, D.result(layout, fired[side], cell))
                    self.assertFalse(result & 8)
                    fired[side].append(cell)
            self.assertEqual(len(own.out), 24)  # naturally ACKed receipts, not discarded fillers
            self.assertTrue(all(o[0] == 1 and o[1][0] == 2 for o in own.out))
            remote = load(tmp + "/peer/duel.json")["g"][0]
            self.assertEqual(remote["n"], 68)
            self.assertEqual(remote["h"], games[0]["h"])
            import lvduelview
            import lvliveapi
            snapshot = lvduelview.view(own)
            # Three long games, then the four stubs of crewmates with no game here, which
            # the page shows too (review 0.3.1-9 #1): the streamed snapshot carries them.
            self.assertEqual([g["to"] for g in snapshot], [1, 2, 3, 4, 5, 6, 7])
            self.assertTrue(all("history" in g and "shots" not in g for g in snapshot[:3]))
            self.assertTrue(all(g["stub"] and g["pending"] and "history" not in g for g in snapshot[3:]))
            # Exactly what tests/phone_heap.py's duel_phone insists on for these stubs.
            self.assertEqual([(set(g), g["s"], g["record"]) for g in snapshot[3:]],
                             [({"to", "id", "s", "stub", "pending", "record"}, "done", [123, 123])] * 4)
            # A later durable radio update cannot change a response already counted.
            before = "".join(lvliveapi.parts([], [], [], [], None, {"duel": snapshot, "on": True}))
            games[0]["h"] += "Ia"
            games[0]["n"] += 1
            D.save(tmp + "/duel.json", box)
            after = "".join(lvliveapi.parts([], [], [], [], None, {"duel": snapshot, "on": True}))
            self.assertEqual(before, after)
            self.assertEqual(json.loads(after)["duel"][3:], snapshot[3:])
            for g, source in zip(json.loads(after)["duel"], snapshot[:3]):
                shots = list(D.history({"h": source["history"]}))
                self.assertEqual(g["shots"], [list(z) for z in shots if z[0] % 2 == 0])
                self.assertEqual(g["incoming"], [list(z) for z in shots if z[0] % 2])
                self.assertNotIn("history", g)
                self.assertNotIn("even", g)

    def test_receive_rules_are_released_before_durable_save(self):
        import tempfile
        from unittest.mock import patch
        import lvduel as D
        import lvship
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            clock = NS(known=lambda: True, epoch_ms=lambda: 1793000000000)
            link = NS(sh=NS(data=tmp, clock=clock), node=NS(ship=0),
                      duel_times={}, v=0, out=[], ble=NS(peers={}))
            game = dict(id="4801", to=1, i=0, s="active", n=68, h="Aa" * 68,
                        p=None, t=1793000000, l="000c23", q=[])
            box = dict(g=[game], r={})
            stages = []

            def save(path, obj):
                stages.append(path)
                self.assertNotIn("lvduelrx", sys.modules)
                self.assertNotIn("lvduelmaint", sys.modules)
                self.assertNotIn("lvduelother", sys.modules)
                self.assertIs(obj, box)
                self.assertEqual(obj["g"][0]["n"], 69)

            def score(*args):
                self.assertNotIn("lvduelother", sys.modules)
                return 0

            import lvlivein as I
            import lvduelstore as S
            with patch.object(D, "box", lambda lk: box), \
                    patch.object(I, "save", save), \
                    patch.object(S, "flush", lambda *args: None), \
                    patch.object(D, "result", score), \
                    patch.object(lvship, "free", lambda: 0):
                self.assertTrue(D.take(link, 1, 5, bytes((0x48, 1, 69, 34)) + bytes(7)))
            self.assertEqual(len(stages), 1)
            self.assertEqual(game["h"][-2:], "ca")

    def test_failed_unknown_reply_does_not_consume_its_retry_window(self):
        from unittest.mock import patch
        import lvduel as D
        import lvship
        clock = NS(known=lambda: False)
        link = NS(sh=NS(clock=clock), node=NS(ship=0), duel_times={},
                  duel_unknown=123, out=[], cfg={})
        with patch.object(D, "box", lambda lk: dict(g=[], r={})), \
                patch.object(D, "store", side_effect=OSError("save failed")), \
                patch.object(lvship, "ticks_ms", lambda: 3600124):
            with self.assertRaises(OSError):
                D.take(link, 1, 5, bytes((0x48, 1, 1, 0)) + bytes(7))
        self.assertEqual(link.duel_unknown, 123)
        self.assertNotIn("lvduelrx", sys.modules)

    def test_recovery_enqueues_reclaim_between_persistence_phases(self):
        from unittest.mock import patch
        import lvduel as D
        import lvlivein as I
        import lvship
        events = []
        link = NS(out=[], sh=NS(data="unused"))
        game = dict(to=1, q=[[9, "00" * 11], [6, "00" * 11]])
        box = dict(g=[game])
        with patch.object(lvship, "free", lambda: events.append("admit")), \
                patch.object(D, "queued", lambda *args: False), \
                patch.object(I, "send", lambda *args: events.append("enqueue")), \
                patch.object(D, "save", lambda *args: events.append("save")):
            D.flush(link, box)
        self.assertEqual(events, ["admit", "enqueue", "admit", "enqueue", "admit", "save"])
        self.assertEqual(game["q"], [])

    def test_save_streams_probes_and_rejects_corrupt_readback(self):
        import gc
        import tempfile
        import builtins
        from io import BytesIO
        from unittest.mock import patch
        import lvlivein as I
        import lvship
        stages = []
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            path = tmp + "/box.json"
            old = {"g": ["old"]}
            I.save(path, old)
            new = {"g": ["Aa" * 71] * 3}
            with patch.object(lvship, "heap_probe", lambda: stages.append(lvship.heap_stage), create=True), \
                 patch.object(gc, "collect", side_effect=AssertionError("probe collected")):
                I.save(path, new)
                self.assertEqual(I.load(path), new)
            self.assertIn("serialize", stages)
            self.assertIn("parse", stages)  # inside the input read, not only after json.load
            self.assertIn("save", stages)
            real_open = builtins.open
            buffers = []

            class Readback(BytesIO):
                def read(self, *args):
                    raise AssertionError("readback must reuse its buffer")

                def readinto(self, buffer):
                    buffers.append(id(buffer))
                    return super().readinto(buffer)

            def reusable(p, mode="r", *args, **kwargs):
                if p == path + ".new" and mode == "rb":
                    with real_open(p, mode) as f:
                        return Readback(f.read())
                return real_open(p, mode, *args, **kwargs)

            with patch.object(builtins, "open", reusable):
                I.save(path, new)
            self.assertGreater(len(buffers), 2)
            self.assertEqual(len(set(buffers)), 1)

            def opened(p, mode="r", *args, **kwargs):
                if p == path + ".new" and mode == "rb":
                    return BytesIO(b"corrupted")
                return real_open(p, mode, *args, **kwargs)
            with patch.object(builtins, "open", opened):
                with self.assertRaisesRegex(OSError, "read back"):
                    I.save(path, old)
            self.assertEqual(I.load(path), new)  # never rename an unverified new file

    def test_phone_checks_all_three_and_waits_for_new_moves(self):
        scope = functions(ROOT / "tests/phone_heap.py", {"duel_phone"}, {"json": json, "asyncio": asyncio, "time": time, "PHONE_TIME": "1793000000000"})
        games = [dict(to=to, n=n, p=None, s="active", shots=[], incoming=[], turn=False, pending=False)
                 for to, n in ((1, 68), (2, 70), (3, 70))]
        for g in games:
            g["shots"] = [[n, 0, 0] for n in range(2, g["n"] + 1, 2)]
            g["incoming"] = [[n, 0, 0] for n in range(1, g["n"] + 1, 2)]
        polls, failures, logs = [], [], []
        async def req(method, path, body, headers):
            if path == "/api/login":
                return 200, {}, b'{"token":"test"}'
            polls.append(path)
            if len(polls) == 2:
                games[0]["n"] = 71
                games[0]["shots"].append([70, 34, 0])
                games[0]["incoming"].append([69, 34, 0])
                games[0]["incoming"].append([71, 35, 10])
                games[0]["s"] = "done"
            if len(polls) == 3:
                games[0].update(n=0, s="draft", shots=[], incoming=[])
            return 200, {}, json.dumps({"duel": games}).encode()
        # The page lists the seeded owed stubs of crewmates 4-7 after the games, as
        # lvduelview.view does since review 0.3.1-9 #1. Fix round 11: the phone check
        # still wanted exactly three entries, which a stale build/board-fw hid.
        stubs = [dict(to=to, id="52%02x" % to, s="done", stub=1, pending=True, record=[123, 123])
                 for to in (4, 5, 6, 7)]
        asyncio.run(scope["duel_phone"](req, 4, False, failures.append, logs.append))
        self.assertEqual(len(failures), 1)
        self.assertIn("owed stubs", failures[0])
        polls[:], failures[:], logs[:] = [], [], []
        games += stubs
        asyncio.run(scope["duel_phone"](req, 4, False, failures.append, logs.append))
        self.assertEqual(failures, [])
        self.assertGreaterEqual(len(polls), 3)  # never stop at the seeded state or n=70
        self.assertTrue(logs)

    def test_board_build_stamp_goes_stale_when_any_source_changes(self):
        # Fix round 0.3.1-11: phone_heap.py measured a build/board-fw from before a
        # lvduelview change for half an hour. Its stamp must follow every source.
        import os
        import tempfile
        sys.path.insert(0, str(ROOT / "tools/fw"))
        import src_stamp
        with tempfile.TemporaryDirectory() as tmp:
            for p in src_stamp.FILES + ("board/lvduelview.py", "lv/clock.py", "content/a.txt",
                                        "web/duel.js", "tools/fw/gen_lvfrozen.py"):
                os.makedirs(os.path.dirname(os.path.join(tmp, p)), exist_ok=True)
                with open(os.path.join(tmp, p), "w") as f:
                    f.write(p)
            self.assertFalse(src_stamp.fresh(tmp))           # never built
            os.makedirs(tmp + "/build")
            with open(os.path.join(tmp, src_stamp.STAMP), "w") as f:
                f.write(src_stamp.stamp(tmp) + "\n")
            self.assertTrue(src_stamp.fresh(tmp))
            os.makedirs(tmp + "/board/__pycache__")
            with open(tmp + "/board/__pycache__/x.pyc", "w") as f:
                f.write("bytecode")
            self.assertTrue(src_stamp.fresh(tmp))            # caches are not sources
            for p in ("board/lvduelview.py", "web/duel.js", "tools/board_build.sh"):
                with open(os.path.join(tmp, p), "a") as f:
                    f.write("#")
                self.assertFalse(src_stamp.fresh(tmp), p)
                with open(os.path.join(tmp, src_stamp.STAMP), "w") as f:
                    f.write(src_stamp.stamp(tmp))
            with open(tmp + "/board/lvnew.py", "w") as f:
                f.write("")
            self.assertFalse(src_stamp.fresh(tmp))           # a new module too

    def test_phone_check_insists_on_exactly_the_owed_stubs(self):
        scope = functions(ROOT / "tests/phone_heap.py", {"duel_phone"}, {"json": json, "asyncio": asyncio, "time": time, "PHONE_TIME": "1793000000000"})
        def long_games():
            out = [dict(to=to, n=n, p=None, s="active", shots=[], incoming=[], turn=False, pending=False)
                   for to, n in ((1, 68), (2, 70), (3, 70))]
            for g in out:
                g["shots"] = [[n, 0, 0] for n in range(2, g["n"] + 1, 2)]
                g["incoming"] = [[n, 0, 0] for n in range(1, g["n"] + 1, 2)]
            return out
        def stub(to, **kw):
            return dict(dict(to=to, id="52%02x" % to, s="done", stub=1, pending=True, record=[123, 123]), **kw)
        bad = ([stub(4), stub(5), stub(6)],                                   # one missing
               [stub(1), stub(4), stub(5), stub(6), stub(7)],                 # a stub over a game
               [stub(4), stub(5), stub(6), stub(7, pending=False)],
               [stub(4), stub(5), stub(6), stub(7, record=[0, 0])],
               [stub(4), stub(5), stub(6), stub(7, n=70)])
        for extra in bad:
            failures = []
            async def req(method, path, body, headers, extra=extra):
                if path == "/api/login":
                    return 200, {}, b'{"token":"test"}'
                return 200, {}, json.dumps({"duel": long_games() + extra}).encode()
            asyncio.run(scope["duel_phone"](req, 4, False, failures.append, lambda s: None))
            self.assertEqual(len(failures), 1, extra)
            self.assertIn("owed stubs", failures[0])

    def test_measurement_requires_live_obligations_not_just_seeded_history(self):
        from unittest.mock import patch
        class Session:
            to = 1
        games = [dict(n=n, h="Aa" * n, s="active", q=[[9, "00" * 11]])
                 for n in (69, 70, 70)]
        stub = lambda: dict(o=1, rj=["0000", 5], q=[[6, "00" * 11], [7, "00" * 11], [8, "00" * 11]])
        box = dict(g=games, e=[stub() for _ in range(7)],
                   r={str(n): [123, 123] for n in range(1, 8)})
        sampled = []
        scope = dict(duel_injecting=[False], duel_held=[True], duel_worst=[None],
                     peer_link=NS(sh=NS(web=NS(radio_hold=True))),
                     ship=NS(live=NS(out=[[1, bytes((2,))]] * 24), ble=NS(sess=Session())),
                     lvlive=NS(Session=Session), w=NS(links=[1]), web=NS(busy=0, radio_hold=False), sys=sys,
                     sample=lambda: sampled.append(True))
        functions(ROOT / "tests/mp_sync_heap.py", {"critical_duel"}, scope)
        with patch.dict(sys.modules):
            sys.modules.pop("lvliveapi", None)
            sys.modules.pop("lvduel", None)
            scope["critical_duel"](box)
            self.assertEqual(scope["duel_worst"][0], ((69, 70, 70), 24, 24))
            self.assertEqual(sampled, [True])
            scope["duel_worst"][0] = None
            with patch.dict(sys.modules, {"lvduel": NS()}):
                with self.assertRaises(AssertionError):
                    scope["critical_duel"](box)
            with patch.dict(sys.modules, {"lvduelrx": NS()}):
                with self.assertRaises(AssertionError):
                    scope["critical_duel"](box)
            for change, undo in (
                (lambda: games[1].update(q=[]), lambda: games[1].update(q=[[9, "00" * 11]])),
                (lambda: box["e"].pop(), lambda: box["e"].append(stub())),
                # A one-END rejection no longer stands in for a stub (review 0.3.1-9 #2).
                (lambda: box["e"][3].update(q=[[8, "00" * 11]]), lambda: box["e"][3].update(stub())),
                (lambda: box["e"][3].pop("rj"), lambda: box["e"][3].update(stub())),
                (lambda: setattr(scope["web"], "radio_hold", True), lambda: setattr(scope["web"], "radio_hold", False)),
                (lambda: setattr(scope["ship"].ble, "sess", NS(to=1)),
                 lambda: setattr(scope["ship"].ble, "sess", Session())),
                (lambda: scope["ship"].live.out.pop(),
                 lambda: scope["ship"].live.out.append([1, bytes((2,))])),
            ):
                scope["duel_worst"][0] = None
                change()
                with self.assertRaises(AssertionError):
                    scope["critical_duel"](box)
                undo()

    def test_complete_live_response_is_valid_json_with_long_histories(self):
        from unittest.mock import patch
        import lvliveapi as api
        top = {"on": True, "duel": [dict(to=to, history="Aa" * 71, even=False, n=71)
                        for to in (1, 2, 3)]}
        outgoing = [["%06x" % n, 2, n % 8, 1793000000000, 2] for n in range(6)]
        incoming = [["%06x" % n, 2, n % 8, 1793000000000, 0, 1, 2, None] for n in range(6)]
        snapshot = ([(1, 0, 1, 0, 0)], outgoing, [2] * 6, incoming, 1793000000000, top)
        chunks, drains = [], []
        async def drain():
            drains.append(True)
        writer = NS(write=lambda b: chunks.append(bytes(b)), drain=drain)
        wire = NS(head=lambda status, kind, n: str(n).encode(), probe=None)
        web = NS(ship=NS(clock=NS(learn_headers=lambda h: False)),
                 get_phone=lambda: NS(who=lambda req: 0))
        with patch.object(api, "_prep", return_value=snapshot):
            asyncio.run(api.live(wire, web, NS(header=None), writer, True))
        body = b"".join(chunks[1:])
        self.assertEqual(int(chunks[0]), len(body))
        self.assertEqual(json.loads(body), json.loads("".join(api.parts(*snapshot))))
        self.assertEqual(len(drains), len(chunks) - 1)
        self.assertTrue(all(len(b) <= api.PIECE for b in chunks[1:]))
        self.assertTrue(all(len(g["shots"]) + len(g["incoming"]) == 71
                            for g in json.loads(body)["duel"]))

        async def sockets():
            import lvweb
            errors = []

            async def serve(reader, writer):
                try:
                    await reader.readline()
                    await api.live(lvweb, web, NS(header=None), writer, True)
                except Exception as error:
                    errors.append(error)
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_server(serve, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                for _ in range(3):
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.write(b"GET /api/live HTTP/1.0\r\n")
                    await writer.drain()
                    header = await reader.readuntil(b"\r\n\r\n")
                    length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                                  if line.lower().startswith(b"content-length:"))
                    response = await reader.read()
                    self.assertEqual(len(response), length)
                    self.assertEqual(json.loads(response), json.loads(body))
                    writer.close()
                    await writer.wait_closed()
                self.assertEqual(errors, [])
            finally:
                server.close()
                await server.wait_closed()

        with patch.object(api, "_prep", return_value=snapshot):
            asyncio.run(sockets())

    def test_live_stream_splits_large_utf8_tokens_without_changing_bytes(self):
        from unittest.mock import patch
        import lvliveapi as api
        chunks = []
        async def drain():
            pass
        writer = NS(write=lambda b: chunks.append(bytes(b)), drain=drain)
        wire = NS(head=lambda status, kind, n: str(n).encode(), probe=None)
        web = NS(ship=NS(clock=NS(learn_headers=lambda h: False)),
                 get_phone=lambda: NS(who=lambda req: 0))
        tokens = ('{"value":"', '\u00e9' * 600, '"}')
        with patch.object(api, "_prep", return_value=()), \
                patch.object(api, "parts", side_effect=lambda: iter(tokens)):
            asyncio.run(api.live(wire, web, NS(header=None), writer, True))
        body = b"".join(chunks[1:])
        self.assertEqual(body, "".join(tokens).encode())
        self.assertEqual(len(body), int(chunks[0]))
        self.assertTrue(all(len(chunk) <= api.PIECE for chunk in chunks[1:]))
        self.assertEqual(json.loads(body)["value"], '\u00e9' * 600)

    def test_reveal_replay_decodes_once_and_checks_every_answer(self):
        from unittest.mock import patch
        import lvduellayout as layout
        from lvduelaction import encode
        raw = encode([[0, 0], [12, 0], [35, 0]])
        h = ""
        for n in range(1, 72):
            cell = (n - 1) // 2
            r = layout.result(raw, list(range(cell)), cell)
            h += chr(65 + cell) + chr(97 + r)
        for even in (True, False):
            with patch.object(layout, "fleet", wraps=layout.fleet) as decode:
                self.assertTrue(layout.replay(raw, h, even))
                decode.assert_called_once_with(raw)
            offset = 2 if even else 0
            bad = h[:offset + 1] + "a" + h[offset + 2:]
            self.assertFalse(layout.replay(raw, bad, even))
            # Duplicate cells and malformed layouts still invalidate verification.
            duplicate = h[:offset + 4] + h[offset:offset + 2] + h[offset + 6:]
            self.assertFalse(layout.replay(raw, duplicate, even))
        with self.assertRaises(ValueError):
            layout.replay(bytes((255, 255, 255)), h, True)

    def test_operation_probes_never_collect_or_deliver_directly(self):
        from unittest.mock import Mock
        gc = NS(mem_alloc=lambda: 125000, collect=Mock(side_effect=AssertionError("collection")))
        scope = dict(gc=gc, base=1000, HAIL_M=[None], sys=NS(modules={}),
                     kpeak={}, peak=[0], where=[""], PER_USE=(), duel_injecting=[False], DUEL=False)
        functions(ROOT / "tests/mp_sync_heap.py", {"sample"}, scope)
        self.assertEqual(scope["sample"](), 124000)
        self.assertEqual(scope["peak"], [124000])
        gc.collect.assert_not_called()
        tree = ast.parse((ROOT / "tests/mp_sync_heap.py").read_text())
        stream = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "stream_sample")
        calls = [n for n in ast.walk(stream) if isinstance(n, ast.Call)]
        self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == "take" for n in calls))
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == "poll" for n in calls))

    def test_32_bit_cap_is_strict_and_fails_at_110000(self):
        from contextlib import redirect_stdout
        from io import StringIO
        tree = ast.parse((ROOT / "tests/mp_sync_heap.py").read_text())
        cap = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CAP" for t in n.targets))
        gate = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ok" for t in n.targets))
        code = compile(ast.Module(body=[cap, gate], type_ignores=[]), "heap gate", "exec")
        for board, expected in ((109999, True), (110000, False), (110001, False), (0, False)):
            scope = dict(synced=True, http_ok=[True], led_ok=True, base=1, BITS=32, board=board)
            exec(code, scope)
            self.assertEqual(scope["CAP"], 110000)
            self.assertEqual(scope["ok"], expected)
            result = compile(ast.Module(body=tree.body[-2:],
                                        type_ignores=[]), "heap result", "exec")
            scope["sys"] = sys
            out = StringIO()
            with redirect_stdout(out):
                if expected:
                    exec(result, scope)
                else:
                    with self.assertRaises(SystemExit) as failure:
                        exec(result, scope)
                    self.assertEqual(failure.exception.code, 1)
            self.assertEqual(out.getvalue().strip(), "RESULT " + ("PASS" if expected else "FAIL"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
