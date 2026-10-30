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
            scope["critical_duel"](box)
            self.assertEqual(scope["duel_worst"][0], ((69, 70, 70), 10, 24))
            self.assertEqual(sampled, [True])
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
