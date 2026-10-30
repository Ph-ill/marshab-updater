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
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            games = [dict(n=n, h="Aa" * n, s="active", q=[[9, "00" * 11]])
                     for n in (69, 70, 70)]
            with open(tmp + "/duel.json", "w") as f:
                json.dump({"g": games}, f)
            active, sampled = [], []
            link = NS(n={"in": 0}, out=[None] * 24)
            scope = dict(DUEL=True, DUEL_M=[b"shot"], duel_taken=[False], duel_injecting=[False],
                         duel_worst=[None], DATA=tmp, sys=sys, ship=NS(live=link), HailSes=lambda: None,
                         HAIL_M=[None], kpeak={}, peak=[0], where=[""], PER_USE=(),
                         mem=lambda: sampled.append(bool(active)) or -1)
            def take(*args):
                active.append(True)
                try:
                    scope["sample"]()  # same callback as the real inbound rules
                    link.n["in"] += 1
                finally:
                    active.pop()
            link.take = take
            functions(ROOT / "tests/mp_sync_heap.py", {"sample"}, scope)
            with patch.dict(sys.modules, {"lvliveapi": NS(), "lvduel": NS()}):
                scope["sample"]()
                self.assertEqual(scope["duel_worst"][0], ((69, 70, 70), 3, 24))
                self.assertTrue(scope["duel_taken"][0])
                self.assertIn(True, sampled)
                # A fixture that flushes/discards its intents before the measured
                # rules call is not accepted, even with all three long histories.
                games[1]["q"] = []
                with open(tmp + "/duel.json", "w") as f:
                    json.dump({"g": games}, f)
                scope["duel_taken"][0] = False
                scope["duel_worst"][0] = None
                with self.assertRaises(AssertionError):
                    scope["sample"]()

    def test_32_bit_cap_remains_inclusive_and_fails_above_100000(self):
        tree = ast.parse((ROOT / "tests/mp_sync_heap.py").read_text())
        cap = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HEAP_CAP" for t in n.targets))
        gate = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ok" for t in n.targets))
        code = compile(ast.Module(body=[cap, gate], type_ignores=[]), "heap gate", "exec")
        for board, expected in ((100000, True), (100001, False), (0, False)):
            scope = dict(synced=True, http_ok=[True], led_ok=True, base=1, BITS=32, board=board)
            exec(code, scope)
            self.assertEqual(scope["HEAP_CAP"], 100000)
            self.assertEqual(scope["ok"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
