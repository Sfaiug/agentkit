"""A suite the helper has room for runs there and takes no turn here, until something comes back.
Offline: fake ssh, gate turns and piece exits, with a barrier proving each place's first piece
starts together.
"""

from collections import Counter
import contextlib
import io
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from agentkit import config, gate, helper, history, worker


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


class SuiteOnAHelper(unittest.TestCase):
    def setUp(self):
        fixture.SuiteHelper.setUp(self)
        self.pace = 0

    def turn(self, *_args, **_kw):
        self.turns.append(True)
        hold = Turn(2)
        self.holds.append(hold)
        return hold

    def check(self, codes=None, places=3, **suite):
        """The suite on `places` places; `codes[place]`: the exits of the first piece run there;
        `suite`, what else `run_suite` is given."""
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
            time.sleep(self.pace)
            output.write(f"{place} {shard}: exit {code}\n".encode())
            return code, "", False

        with patch.object(worker, "limited", side_effect=lambda *a, **kw: execute(
                "helper", *a, **kw)), patch.object(worker, "boxed", side_effect=lambda *a, **kw:
                execute("here", *a, **kw)), patch.object(helper, "piece", wraps=helper.piece) as sent:
            code, text, killed = gate.run_suite(
                fixture.SUITE, 30, cwd=self.repo, activity=self.root / "live.log",
                output=io.BytesIO(), log=self.logs.append, pieces=outcomes, **suite)
        self.count = 2 * places
        self.shards = {f"{i}/{self.count}" for i in range(1, self.count + 1)}
        self.assertEqual(started, self.shards)
        self.assertEqual(outcomes.keys(), self.shards)
        sent = [call.args[1] for call in sent.call_args_list]
        if helper.FULL not in (codes or {}).get("helper", ()):    # the helper ran each piece once
            self.assertEqual(sorted(sent), sorted(set(sent)))
        self.assertEqual(sum(self.calls.values()), self.count + self.retried())
        self.assertTrue(all(hold.released for hold in self.holds))
        self.assertIsNone(gate._GATE_HELD.hold)
        return code, text, killed, outcomes

    def retried(self):
        return sum(n - 1 for n in Counter(shard for _, shard in self.calls.elements()).values())

    def test_every_piece_runs_on_the_helper_and_no_turn_is_taken(self):
        code, text, killed, outcomes = self.check()
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(outcomes, dict.fromkeys(self.shards, 0))
        self.assertEqual({place for place, _ in self.calls}, {"helper"})
        self.assertEqual((self.turns, self.holds, self.retried()), ([], [], 0))
        for _, shard in self.calls:
            self.assertIn(f"AK_SHARD={shard} on acme-mac", self.logs)
        self.assertIn("every piece passed on the suite helper acme-mac", self.logs)

    def test_helper_failures_and_losses_rerun_here_on_a_turn_taken_then(self):
        for failed in (1, helper.LOST):
            with self.subTest(failed=failed):
                code, text, killed, outcomes = self.check({"helper": (failed,)})
                self.assertEqual((code, killed), (0, False), text)
                self.assertTrue(all(code == 0 for code in outcomes.values()))
                shard = self.first["helper"]
                self.assertEqual(self.calls[("here", shard)], 1)
                self.assertEqual(self.retried(), 1)
                self.assertEqual(self.turns, [True])
                self.assertIn((shard, 2), self.local_turns)
                self.assertIn(f"AK_SHARD={shard} runs here: helper acme-mac "
                              f"{helper.failure(failed)}", self.logs)

    def test_a_piece_run_again_here_is_asked_for_as_its_go_there_ended(self):
        # the turn it waits for here, a minute on the clock, is its row's wait
        run_dir = config.RUNS / "fix-api"
        run_dir.mkdir()
        history.start_run(run_dir.name, repo="acme")
        moved = [0]

        def waited(*args, **kwargs):
            moved[0] += 60
            return self.turn(*args, **kwargs)

        with patch.object(gate.time, "time", lambda: 1000 + moved[0]), \
                patch.object(history, "time", gate.time), \
                patch.object(gate, "_acquire_gate_turn", side_effect=waited):
            self.check({"helper": (1,)}, run_dir=run_dir, checked=(1, "done-when", "a" * 40),
                       asked=1000)
        with contextlib.closing(sqlite3.connect(history.path())) as connection:
            again = connection.execute("SELECT place, requested_at, started_at FROM checks "
                                       "WHERE rerun").fetchall()
        self.assertEqual(again, [(socket.gethostname(), 1000, 1060)])

    def test_a_vm_turned_away_for_room_asks_the_helper_again_no_sooner_than_a_poll(self):
        # One VM's place ends; the other's pieces take a moment, time enough for an ask the piece
        # it turned away wakes.
        self.pace = 0.2
        with patch.object(helper, "room", return_value=((2, 2, 820, 2), "")), \
                patch.object(helper, "start", wraps=helper.start) as asked:
            code, text, killed, _ = self.check({"helper": (helper.FULL,)}, places=2)
        self.assertEqual((code, killed, asked.call_count), (0, False, 1), text)

    def test_local_failure_retries_alone_and_is_not_a_helper_failure(self):
        with patch.object(helper, "room", return_value=(None, "is on battery")):
            code, text, killed, _ = self.check({"here": (1, 0)}, places=2)
        self.assertEqual((code, killed), (0, False), text)
        self.assertEqual(self.calls[("here", self.first["here"])], 2)
        self.assertEqual(self.retried(), 1)
        self.assertEqual(self.local_turns[-1], (self.first["here"], 1))
        self.assertEqual([line for line in self.logs if line.startswith("WARN")], [])
        self.assertIn("flaky:", text)

    def test_a_local_piece_still_failing_keeps_the_suite_red(self):
        with patch.object(helper, "room", return_value=(None, "is on battery")):
            code, text, killed, outcomes = self.check({"here": (1,)}, places=2)
        self.assertEqual((code, killed), (1, False), text)
        self.assertEqual(outcomes, {shard: int(shard == self.first["here"])
                                    for shard in self.shards})
        self.assertEqual(self.calls[("here", self.first["here"])], 2)

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
        self.addCleanup(returned.set)    # the helper answers only once the suite has returned
        with patch.object(helper, "start", side_effect=start), \
                patch.object(Turn, "take", lambda _hold, _stopped: asked.wait(10)):
            code, text, killed, _ = self.check(places=2)
        self.assertEqual((code, killed, answered.is_set()), (0, False, False), text)


if __name__ == "__main__":
    unittest.main()
