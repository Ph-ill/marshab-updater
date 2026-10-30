#!/usr/bin/env python3
"""Heap regression: measure three near-limit transcripts and durable reply intents."""
import ast
import asyncio
import json
from pathlib import Path
import sys
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
        with patch.object(D, "maint_call", lambda *args: calls.append(args[0]) or True):
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": 123}]}))
            self.assertEqual(calls, [])
            self.assertEqual(link.duel_due, 0)
            game = {"s": "active", "t": None}
            self.assertTrue(D.sweep(link, {"g": [game]}))
            self.assertEqual(game["t"], 123)
            self.assertEqual(calls, [])
            link.sh.clock.known = lambda: False
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": None}]}))
            for state, stamp in (("draft", 123), ("wait", 123), ("invited", 123)):
                self.assertTrue(D.sweep(link, {"g": [{"s": state, "t": stamp}]}))
            self.assertEqual(calls, ["sweep"] * 3)
            link.sh.web.busy = 0
            self.assertFalse(D.sweep(link, {"g": [{"s": "active", "t": 123}]}, True))
            self.assertEqual(calls, ["sweep"] * 3)
            self.assertTrue(D.sweep(link, {"g": [{"s": "active", "t": 123}]}))
            self.assertEqual(calls, ["sweep"] * 4)

    def test_ack_maintenance_retries_after_http_releases_snapshot(self):
        import tempfile
        from unittest.mock import patch
        import lvduel as D
        import lvlivein as I
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            (Path(tmp) / "duel.json").touch()
            link = NS(sh=NS(web=NS(busy=1), data=tmp), duel_due=100)
            with patch.object(D, "maintain") as maintain:
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
        scope = dict(gc=NS(mem_alloc=lambda: 1), base=0, sys=sys,
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
                          nx={}, due=0, n={"out": 0}, hw={}, lc=[None, 0], f=data + "/livebox.json")
            own, peer = link(0, tmp), link(1, tmp + "/peer")
            scope = functions(ROOT / "tests/mp_sync_heap.py", {"seed_duels"}, {})
            scope["seed_duels"](own, peer)
            box = load(tmp + "/duel.json")
            games = box["g"]
            self.assertEqual(len(box.get("e", [])), 7)
            self.assertEqual(len(box["r"]), 7)
            self.assertTrue(all(g.get("q") and g["q"][0][0] == 8 for g in box["e"]))
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
            self.assertTrue(all("history" in g and "shots" not in g for g in snapshot))
            # A later durable radio update cannot change a response already counted.
            before = "".join(lvliveapi.parts([], [], [], [], None, {"duel": snapshot, "on": True}))
            games[0]["h"] += "Ia"
            games[0]["n"] += 1
            D.save(tmp + "/duel.json", box)
            after = "".join(lvliveapi.parts([], [], [], [], None, {"duel": snapshot, "on": True}))
            self.assertEqual(before, after)
            for g, source in zip(json.loads(after)["duel"], snapshot):
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
        scope = functions(ROOT / "tests/phone_heap.py", {"duel_phone"}, {"json": json, "asyncio": asyncio})
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
                games[0]["n"] = 70
                games[0]["shots"].append([70, 34, 0])
                games[0]["incoming"].append([69, 34, 0])
            return 200, {}, json.dumps({"duel": games}).encode()
        asyncio.run(scope["duel_phone"](req, 4, False, failures.append, logs.append))
        self.assertEqual(failures, [])
        self.assertGreaterEqual(len(polls), 2)  # old >=2 test returned at the seeded state
        self.assertTrue(logs)

    def test_measurement_requires_live_obligations_not_just_seeded_history(self):
        from unittest.mock import patch
        class Session:
            to = 1
        games = [dict(n=n, h="Aa" * n, s="active", q=[[9, "00" * 11]])
                 for n in (69, 70, 70)]
        box = dict(g=games, e=[dict(q=[[8, "00" * 11]]) for _ in range(7)],
                   r={str(n): [123, 123] for n in range(1, 8)})
        sampled = []
        scope = dict(duel_injecting=[True], duel_worst=[None],
                     ship=NS(live=NS(out=[[1, bytes((2,))]] * 24), ble=NS(sess=Session())),
                     lvlive=NS(Session=Session), w=NS(links=[1]), web=NS(busy=1), sys=sys,
                     sample=lambda: sampled.append(True))
        functions(ROOT / "tests/mp_sync_heap.py", {"critical_duel"}, scope)
        with patch.dict(sys.modules, {"lvliveapi": NS()}):
            sys.modules.pop("lvduel", None)
            scope["critical_duel"](box)
            self.assertEqual(scope["duel_worst"][0], ((69, 70, 70), 10, 24))
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
                (lambda: box["e"].pop(), lambda: box["e"].append(dict(q=[[8, "00" * 11]]))),
                (lambda: setattr(scope["web"], "busy", 0), lambda: setattr(scope["web"], "busy", 1)),
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

    def test_operation_probes_never_collect_or_deliver_directly(self):
        from unittest.mock import Mock
        gc = NS(mem_alloc=lambda: 125000, collect=Mock(side_effect=AssertionError("collection")))
        scope = dict(gc=gc, base=1000, HAIL_M=[None], sys=NS(modules={}),
                     kpeak={}, peak=[0], where=[""], PER_USE=(), duel_injecting=[False])
        functions(ROOT / "tests/mp_sync_heap.py", {"sample"}, scope)
        self.assertEqual(scope["sample"](), 124000)
        self.assertEqual(scope["peak"], [124000])
        gc.collect.assert_not_called()
        tree = ast.parse((ROOT / "tests/mp_sync_heap.py").read_text())
        stream = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "stream_sample")
        calls = [n for n in ast.walk(stream) if isinstance(n, ast.Call)]
        self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == "take" for n in calls))
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == "poll" for n in calls))

    def test_32_bit_cap_remains_inclusive_and_fails_above_100000(self):
        from contextlib import redirect_stdout
        from io import StringIO
        tree = ast.parse((ROOT / "tests/mp_sync_heap.py").read_text())
        cap = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HEAP_CAP" for t in n.targets))
        gate = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ok" for t in n.targets))
        code = compile(ast.Module(body=[cap, gate], type_ignores=[]), "heap gate", "exec")
        for board, expected in ((100000, True), (100001, False), (0, False)):
            scope = dict(synced=True, http_ok=[True], led_ok=True, base=1, BITS=32, board=board)
            exec(code, scope)
            self.assertEqual(scope["HEAP_CAP"], 100000)
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
