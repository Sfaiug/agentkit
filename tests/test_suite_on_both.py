"""One suite uses the helper's VMs and free local turns together. Offline: fake ssh, gate
turns and piece exits, with a barrier proving each place's first piece starts together.
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
from agentkit import gate, helper, host, worker


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

    def check(self, codes=None, places=5):
        """The suite on `places` places; `codes[place]`: the exits of the first piece run there."""
        self.calls, self.holds, self.turns, self.first = Counter(), [], [], {}
        self.local_turns, self.logs = [], []
        started, outcomes = set(), {}
        barrier, lock = threading.Barrier(places, timeout=10), threading.Lock()

        def execute(place, argv, _limit, *, env, output, **_kw):
            shard = env["AK_SHARD"]
            with lock:
                key = place, shard
                self.calls[key] += 1
                first = shard not in started
                started.add(shard)
                failing = self.first.setdefault(place, shard) == shard
                if place == "here":
                    self.assertEqual(argv, ["bash", "-c", fixture.SUITE])
                    self.assertEqual(env.get("AK_HEAVY_TURN"), "1")
                    self.local_turns.append((shard, len(self.holds[-1].slots)))
            if first and len(started) <= places:
                barrier.wait()
            exits = (codes or {}).get(place, (0,)) if failing else (0,)
            code = exits[min(self.calls[key] - 1, len(exits) - 1)]
            output.write(f"{place} {shard}: exit {code}\n".encode())
            return code, "", False

        with patch.object(worker, "limited", side_effect=lambda *a, **kw: execute(
                "helper", *a, **kw)), patch.object(worker, "boxed", side_effect=lambda *a, **kw:
                execute("here", *a, **kw)), patch.object(helper, "piece", wraps=helper.piece) as sent:
            code, text, killed = gate.run_suite(
                fixture.SUITE, 30, cwd=self.repo, activity=self.root / "live.log",
                output=io.BytesIO(), log=self.logs.append, pieces=outcomes)
        self.count = 2 * places
        self.shards = {f"{i}/{self.count}" for i in range(1, self.count + 1)}
        self.assertEqual(started, self.shards)
        self.assertEqual(outcomes.keys(), self.shards)
        sent = [call.args[1] for call in sent.call_args_list]
        self.assertEqual(sorted(sent), sorted(set(sent)))    # the helper ran each piece once
        self.assertEqual(sum(self.calls.values()), self.count + self.retried())
        self.assertTrue(all(hold.released for hold in self.holds))
        self.assertIsNone(gate._GATE_HELD.hold)
        return code, text, killed, outcomes

    def retried(self):
        return sum(n - 1 for n in Counter(shard for _, shard in self.calls.elements()).values())

    def test_helper_pieces_and_local_pieces_pass_as_one_suite(self):
        code, text, killed, outcomes = self.check()
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(outcomes, dict.fromkeys(self.shards, 0))
        self.assertEqual(self.retried(), 0)
        self.assertEqual(self.turns, [False])
        for place, shard in self.calls:
            self.assertIn(f"AK_SHARD={shard} on acme-mac" if place == "helper" else
                          f"AK_SHARD={shard} runs here: free heavy suite turns", self.logs)
        self.assertIn("every piece passed on the suite helper acme-mac and this host", self.logs)

    def test_helper_failures_and_losses_rerun_here_on_the_turns_already_held(self):
        for failed in (1, helper.LOST):
            with self.subTest(failed=failed):
                code, text, killed, outcomes = self.check({"helper": (failed,)})
                self.assertEqual((code, killed), (0, False), text)
                self.assertTrue(all(code == 0 for code in outcomes.values()))
                shard = self.first["helper"]
                self.assertEqual(self.calls[("here", shard)], 1)
                self.assertEqual(self.retried(), 1)
                self.assertEqual(self.turns, [False])
                self.assertIn((shard, 2), self.local_turns)
                self.assertIn(f"AK_SHARD={shard} runs here: helper acme-mac "
                              f"{helper.failure(failed)}", self.logs)

    def test_local_failure_retries_alone_and_is_not_a_helper_failure(self):
        code, text, killed, _ = self.check({"here": (1, 0)})
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(self.calls[("here", self.first["here"])], 2)
        self.assertEqual(self.retried(), 1)
        self.assertEqual(self.local_turns[-1], (self.first["here"], 1))
        self.assertEqual([line for line in self.logs if line.startswith("WARN")], [])
        self.assertIn("flaky:", text)

    def test_a_local_piece_still_failing_keeps_the_suite_red(self):
        code, text, killed, outcomes = self.check({"here": (1,)})
        self.assertEqual((code, killed), (1, False), text)
        self.assertEqual(outcomes, {shard: int(shard == self.first["here"])
                                    for shard in self.shards})
        self.assertEqual(self.calls[("here", self.first["here"])], 2)

    def test_no_local_turn_runs_every_piece_on_the_helper(self):
        self.local_count = 0
        code, text, killed, _ = self.check(places=3)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual({place for place, _ in self.calls}, {"helper"})
        self.assertEqual(self.turns, [False])
        self.assertEqual(self.holds, [])
        self.assertIn("every piece passed on the suite helper acme-mac", self.logs)

    def test_helper_refusal_runs_only_local_pieces(self):
        with patch.object(helper, "room", return_value=(None, "is on battery")):
            code, text, killed, _ = self.check(places=2)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual({place for place, _ in self.calls}, {"here"})
        self.assertEqual(self.turns, [True])

    def test_a_finished_suite_never_waits_on_the_helper_s_answer(self):
        asked, returned, answered = threading.Event(), threading.Event(), threading.Event()

        def start(*_args):
            if self.turns:    # asked again while a piece waits: the suite ends meanwhile
                asked.set()
                returned.wait(10)
                answered.set()
            return None, "helper acme-mac is on battery"

        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.01))
        with patch.object(helper, "start", side_effect=start), \
                patch.object(Turn, "take", lambda _hold, _stopped: asked.wait(10)):
            code, text, killed, _ = self.check(places=2)
        returned.set()
        self.assertEqual((code, killed, answered.is_set()), (0, False, False), text)

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
