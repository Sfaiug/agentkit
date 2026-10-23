"""One suite uses the helper's pieces and free local turns together. Offline: fake ssh,
gate turns and piece exits, with a barrier proving both hosts' pieces start together.
"""

from collections import Counter
from contextlib import ExitStack
import fcntl
import io
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from agentkit import config, gate, helper, host, worker


class Turn:
    def __init__(self, count):
        self.slots = [None] * count
        self.pieces, self.waited, self.released = count, False, False

    def take(self, stopped):
        return True

    def give(self, slot):
        pass

    def alone(self):
        self.slots = self.slots[:1]

    def release(self):
        self.slots = []
        self.released = True


class SuiteOnBoth(unittest.TestCase):
    def setUp(self):
        self.acquire = gate._acquire_gate_turn
        fixture.SuiteHelper.setUp(self)
        self.local_count = 2

    def turn(self, *_args, wait=True, **_kw):
        self.turns.append(wait)
        if not wait and not self.local_count:
            return None
        hold = Turn(self.local_count or 1)
        self.holds.append(hold)
        return hold

    def check(self, codes=None, count=5):
        self.calls, self.holds, self.turns = Counter(), [], []
        self.local_turns, self.logs = [], []
        started, finished, outcomes = set(), set(), {}
        barrier, lock = threading.Barrier(count, timeout=10), threading.Lock()

        def execute(place, argv, _limit, *, env, output, **_kw):
            shard = env["AK_SHARD"]
            with lock:
                key = place, shard
                self.calls[key] += 1
                attempt = self.calls[key]
                first = shard not in started
                started.add(shard)
                if place == "here":
                    self.assertEqual(argv, ["bash", "-c", fixture.SUITE])
                    self.assertEqual(env.get("AK_HEAVY_TURN"), "1")
                    self.local_turns.append((shard, len(self.holds[-1].slots)))
            if first:
                barrier.wait()
            exits = (codes or {}).get(key, (0,))
            code = exits[min(attempt - 1, len(exits) - 1)]
            output.write(f"{place} {shard}: exit {code}\n".encode())
            with lock:
                finished.add(shard)
            return code, "", False

        with patch.object(worker, "limited", side_effect=lambda *a, **kw: execute(
                "helper", *a, **kw)), patch.object(worker, "boxed", side_effect=lambda *a, **kw:
                execute("here", *a, **kw)), patch.object(helper, "piece", wraps=helper.piece) as sent:
            code, text, killed = gate.run_suite(
                fixture.SUITE, 30, cwd=self.repo, activity=self.root / "live.log",
                output=io.BytesIO(), log=self.logs.append, pieces=outcomes)
        self.assertEqual(started, {f"{i}/{count}" for i in range(1, count + 1)})
        self.assertEqual(finished, started)
        self.assertEqual(outcomes.keys(), started)
        self.assertCountEqual([call.args[1] for call in sent.call_args_list],
                              [f"{i}/{count}" for i in range(1, sent.call_count + 1)])
        self.assertTrue(all(hold.released for hold in self.holds))
        self.assertIsNone(gate._GATE_HELD.hold)
        return code, text, killed, outcomes

    def initial_calls(self, count=5, remote=3):
        return Counter({("helper" if i <= remote else "here", f"{i}/{count}"): 1
                        for i in range(1, count + 1)})

    def test_three_helper_pieces_and_two_local_pieces_pass_as_one_suite(self):
        code, text, killed, outcomes = self.check()
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(outcomes, {f"{i}/5": 0 for i in range(1, 6)})
        self.assertEqual(self.calls, self.initial_calls())
        self.assertEqual(self.turns, [False])
        for shard in ("1/5", "2/5", "3/5"):
            self.assertIn(f"AK_SHARD={shard} on acme-mac", self.logs)
        for shard in ("4/5", "5/5"):
            self.assertIn(f"AK_SHARD={shard} runs here: free heavy suite turns", self.logs)
        self.assertIn("every piece passed on the suite helper acme-mac and this host", self.logs)

    def test_helper_failures_and_losses_rerun_here_on_the_turns_already_held(self):
        for failed in (1, helper.LOST):
            with self.subTest(failed=failed):
                code, text, killed, outcomes = self.check({("helper", "2/5"): (failed,)})
                self.assertEqual((code, killed), (0, False), text)
                self.assertTrue(all(code == 0 for code in outcomes.values()))
                self.assertEqual(self.calls, self.initial_calls() + Counter({("here", "2/5"): 1}))
                self.assertEqual(self.turns, [False])
                self.assertIn(("2/5", 2), self.local_turns)
                self.assertIn(f"AK_SHARD=2/5 runs here: helper acme-mac {helper.failure(failed)}",
                              self.logs)

    def test_local_failure_retries_alone_and_is_not_a_helper_failure(self):
        code, text, killed, _ = self.check({("here", "4/5"): (1, 0)})
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(self.calls, self.initial_calls() + Counter({("here", "4/5"): 1}))
        self.assertIn(("4/5", 1), self.local_turns)
        self.assertEqual([line for line in self.logs if line.startswith("WARN")], [])
        self.assertIn("flaky:", text)

    def test_a_local_piece_still_failing_keeps_the_suite_red(self):
        code, text, killed, outcomes = self.check({("here", "5/5"): (1,)})
        self.assertEqual((code, killed), (1, False), text)
        self.assertEqual(outcomes, {f"{i}/5": int(i == 5) for i in range(1, 6)})
        self.assertEqual(self.calls, self.initial_calls() + Counter({("here", "5/5"): 1}))

    def test_no_local_turn_runs_all_three_pieces_on_the_helper(self):
        self.local_count = 0
        code, text, killed, _ = self.check(count=3)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(self.calls, self.initial_calls(count=3))
        self.assertEqual(self.turns, [False])
        self.assertEqual(self.holds, [])
        self.assertIn("every piece passed on the suite helper acme-mac", self.logs)

    def test_helper_refusal_runs_only_local_pieces(self):
        with patch.object(helper, "room", return_value=(None, "is on battery")):
            code, text, killed, _ = self.check(count=2)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(self.calls, self.initial_calls(count=2, remote=0))
        self.assertEqual(self.turns, [True])

    def test_local_admission_takes_free_turns_without_waiting_or_passing_an_older_waiter(self):
        for held, older in ((0, False), (2, False), (0, True)):
            with self.subTest(held=held, older=older), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": ""}))
                stack.enter_context(patch.object(gate, "_run_readings", return_value={}))
                stack.enter_context(patch.object(host, "kept_cpu", return_value=None))
                stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))
                stack.enter_context(patch.object(gate, "_gate_waiter_before", return_value=older))
                stack.enter_context(patch.object(gate.time, "sleep", side_effect=AssertionError(
                    "a suite already on the helper must not wait for local turns")))
                for i in range(held):
                    holder = stack.enter_context(gate.gate_lock(None, i).open("a"))
                    fcntl.flock(holder, fcntl.LOCK_EX)
                hold = self.acquire(None, self.root / "gate.log", None, fixture.SUITE,
                                    self.repo, context={"repo": str(self.repo)}, wait=False)
                if not held and not older:
                    self.assertEqual(len(hold.slots), 2)
                    hold.release()
                else:
                    self.assertIsNone(hold)
                self.assertEqual(gate._heavy_running(), held)


if __name__ == "__main__":
    unittest.main()
