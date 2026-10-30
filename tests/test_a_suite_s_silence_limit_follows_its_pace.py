"""A suite whose last 20 runs never went quiet for long is stopped sooner at its own pace, and
what that stops goes once more, alone, with the rest of the silence limit: a hang waits no
longer than one window did, and a piece that hung once passes on its second go while its
siblings run on.

Offline: temporary HOME, injected host readings, the check box faked except where one real
command shows the watchdog measuring its quiet.
"""

from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, gitcall, helper, record, worker

ROOM = {"cpus": 4, "load": 0, "free_mb": 820,
        "slice_cpu_quota": 4, "slice_cpu_used": 0,
        "slice_memory_high_mb": 820, "slice_memory_used_mb": 0}
SUITE = 'printf "piece %s\\n" "${AK_SHARD:-all}"'
WHOLE = "echo whole"
HERE = "suite runs here: command is not sent to the suite helper (does not name AK_SHARD)"
NOBODY = 2 ** 22 + 1    # past any pid_max: a stopped command with no children to name


class SilenceLimitFollowsItsPace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-quiet-pace-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_HOST_READINGS": json.dumps(ROOM), "AK_CGROUP_FILE": str(self.root / "no-cgroup")}))
        config.ensure_dirs()
        self.run_dir = config.RUNS / "fixture"
        self.run_dir.mkdir()
        record.save_state(self.run_dir, {"run_id": "fixture", "state": "running"})

    def paced(self, command, quiet):
        path = gate.suite_cost(command, self.root, self.run_dir)[0]
        gate.write_suite_cost(path, {"quiet": quiet})
        return path

    def pieces(self, first, second=None, later=900):
        """The suite in two pieces whose first go of 1/2 says `first` ("silence" or an exit),
        and whose second go, if any, says `second`: the calls, the stops the caller was told
        of, the result, and whether 2/2 saw its siblings cancelled once 1/2 had stopped."""
        calls, told, cancelled, stopped, begun = [], [], [], threading.Event(), threading.Event()
        self.markers = {}

        def boxed(cmd, limit, env, output, silence=None, on_timeout=None, abort=None, quiet=None,
                  **_kw):
            shard = env["AK_SHARD"]
            calls.append((shard, silence))
            self.markers[shard] = env.get(worker.RUN_MARKER)
            output.write(f"piece {shard}\n".encode())
            if shard == "2/2":
                begun.set()
                stopped.wait(10)
                cancelled.append(abort())
                if quiet is not None:
                    quiet.append(100)
                return 0, "", False
            said = first if len([c for c in calls if c[0] == "1/2"]) == 1 else second
            if said == "silence":
                begun.wait(10 if later is None else 0)    # its stop cancels a running sibling
                on_timeout("silence", NOBODY)
                stopped.set()
                return worker.TIMEOUT, "", True
            stopped.set()
            if quiet is not None:
                quiet.append(350)
            return said, "", False

        with patch.object(worker, "boxed", side_effect=boxed), \
                patch.object(worker, "limited", side_effect=boxed):     # a piece on the helper
            result = gate.run_suite(
                SUITE, 3600, cwd=self.root, activity=self.run_dir / "live.log", output=BytesIO(),
                run_dir=self.run_dir, silence=300, later=later,
                on_timeout=lambda why, _pid: told.append(why))
        return calls, told, result, cancelled

    def test_a_piece_its_pace_stopped_goes_again_alone_while_its_siblings_run_on(self):
        calls, told, (code, text, killed), cancelled = self.pieces("silence", 0)
        self.assertEqual(sorted(calls[:2]), [("1/2", 300), ("2/2", 300)])
        self.assertEqual(calls[2:], [("1/2", 900)])
        self.assertEqual((code, killed, told, cancelled), (0, False, [], [False]))
        self.assertIn(f"flaky: {SUITE} (AK_SHARD=1/2) was stopped after 5 min of silence, then "
                      "passed on its re-run", text)
        # the second go's quiet joins the pace, so a pace the suite outgrew retires
        path = gate.suite_cost(SUITE, self.root, self.run_dir)[0]
        self.assertEqual(gate.read_suite_cost(path)["quiet"], [350])

    def test_a_piece_its_pace_stopped_on_the_helper_goes_again_here_on_a_turn(self):
        turns = []
        with patch.object(gate._GATE_HELD, "away", SimpleNamespace(count=1), create=True), \
                patch.object(gate._GATE_HELD, "home", lambda _: turns.append(1), create=True), \
                patch.object(gitcall, "_RUN_CONTEXT", SimpleNamespace(state={"run_id": "fixture"})), \
                patch.object(helper, "piece", lambda _away, _shard, _command: ["true"]):
            calls, told, (code, text, killed), _ = self.pieces("silence", 0)
        self.assertEqual((calls[2:], turns, code, killed, told),
                         ([("1/2", 900)], [1], 0, False, []))
        self.assertIn(f"flaky: {SUITE} (AK_SHARD=1/2) was stopped after 5 min of silence", text)
        # a piece's stop ends its own processes, never its running sibling's; the run's end, all
        run = worker.run_marker("fixture") + "/"
        self.assertNotEqual(self.markers["1/2"], self.markers["2/2"])
        self.assertTrue(all(marker.startswith(run) for marker in self.markers.values()))

    def test_pieces_stopped_on_the_helper_go_again_here_one_at_a_time_and_that_go_decides(self):
        calls, running, together = [], set(), []

        def limited(cmd, limit, env, output, on_timeout, **_kw):
            output.write(b"stopped on the helper\n")
            on_timeout("silence", NOBODY)
            return worker.TIMEOUT, "", True

        def boxed(cmd, limit, env, output, silence=None, **_kw):
            shard = env["AK_SHARD"]
            running.add(shard)
            together.append(len(running))
            calls.append((shard, silence))
            output.write(b"second go\n")
            running.discard(shard)
            return (1 if shard == "1/2" else 0), "", False

        hold = SimpleNamespace(slots=[1, 2], pieces=2, alone=lambda: None,
                               take=lambda stopped: True, give=lambda slot: None)
        with patch.object(gate._GATE_HELD, "away", SimpleNamespace(count=1), create=True), \
                patch.object(gate._GATE_HELD, "hold", None, create=True), \
                patch.object(gate._GATE_HELD, "home", lambda _: hold, create=True), \
                patch.object(helper, "piece", lambda _away, _shard, _command: ["true"]), \
                patch.object(worker, "limited", side_effect=limited), \
                patch.object(worker, "boxed", side_effect=boxed):
            code, text, killed = gate.run_suite(
                SUITE, 3600, cwd=self.root, activity=self.run_dir / "live.log", output=BytesIO(),
                run_dir=self.run_dir, silence=300, later=900)
        self.assertEqual((calls, together, code, killed),
                         ([("1/2", 900), ("2/2", 900)], [1, 1], 1, False))
        self.assertIn(f"flaky: {SUITE} (AK_SHARD=2/2) was stopped after 5 min of silence", text)

    def test_a_piece_silent_on_its_second_go_too_stops_the_suite(self):
        calls, told, (code, text, killed), _ = self.pieces("silence", "silence")
        self.assertEqual(calls[2:], [("1/2", 900)])
        self.assertEqual((code, killed, told), (worker.TIMEOUT, True, ["silence"]))
        self.assertIn("--- AK_SHARD=1/2 ---\n[killed at the limit]", text)

    def test_without_a_pace_a_silent_piece_stops_its_siblings_and_goes_no_more(self):
        calls, told, (code, _, killed), cancelled = self.pieces("silence", later=None)
        self.assertEqual(len(calls), 2)
        self.assertEqual((code, killed, told, cancelled),
                         (worker.TIMEOUT, True, ["silence"], [True]))

    def test_a_failed_piece_s_retry_has_the_rest_of_the_limit(self):
        calls, told, (code, _, killed), _ = self.pieces(1, 0)
        self.assertEqual(calls[2:], [("1/2", 900)])
        self.assertEqual((code, killed, told), (0, False, []))

    def test_a_whole_command_its_pace_stopped_goes_again_with_the_rest(self):
        self.paced(WHOLE, [100] * gate.QUIET_RUNS)
        for second, ok in ((0, True), ("silence", False)):
            with self.subTest(second=second):
                silences, logs = [], []

                def boxed(cmd, limit, env, output, silence=None, on_timeout=None, **_kw):
                    silences.append(silence)
                    output.write(b"working\n")
                    if len(silences) == 1 or second == "silence":
                        on_timeout("silence", NOBODY)
                        return worker.TIMEOUT, "", True
                    return 0, "", False

                with patch.object(worker, "boxed", side_effect=boxed):
                    passed, text = gate.run_done_when(
                        [WHOLE], self.root, self.root / "gate.log", set(), 3600, logs.append,
                        silence=1200, run_dir=self.run_dir, heavy=True)
                self.assertEqual((passed, silences), (ok, [300, 900]))
                self.assertEqual(logs[:2], [HERE, HERE])
                if ok:
                    self.assertIn(f"flaky: {WHOLE} was stopped after 5 min of silence, then "
                                  "passed on its re-run", text)
                else:
                    self.assertEqual(logs[2:], [
                        "done-when: stopped after 15 min of silence on its second go (5 on its "
                        f"first, at its suite's pace): {WHOLE} (last output: working)"])

    def test_the_pace_is_three_times_the_longest_quiet_of_the_last_20_runs(self):
        for quiet, silence, window in (([10] * 19, 1200, None),            # no pace yet
                                       ([10] * 20, 1200, 300),             # five minutes at least
                                       ([10] * 19 + [150], 1200, 450),
                                       ([10] * 19 + [250], 1200, None),    # does not fit twice
                                       ([10] * 20, 300, None)):            # nor in a short limit
            with self.subTest(quiet=quiet[-1], silence=silence):
                self.paced(SUITE, quiet)
                self.assertEqual(gate.quiet_window(SUITE, self.root, self.run_dir, silence), window)

    def test_a_finished_suite_keeps_the_longest_quiet_of_its_pieces_for_its_last_20_runs(self):
        path = self.paced(SUITE, list(range(25)))
        measured = gate._SuiteMeasure(self.run_dir)
        measured.quiet.extend([4.5, 9.5])
        measured.paced(path, 2)
        self.assertEqual(gate.read_suite_cost(path)["quiet"], list(range(6, 25)) + [9.5])
        measured = gate._SuiteMeasure(self.run_dir)
        measured.quiet.append(60)       # one piece measured of two: no pace from it
        measured.paced(path, 2)
        self.assertEqual(gate.read_suite_cost(path)["quiet"][-1], 9.5)

    def test_the_watchdog_measures_the_longest_a_command_went_quiet(self):
        activity, quiet = self.root / "check.log", []
        with activity.open("wb") as out, patch.object(worker, "ACTIVITY_POLL", .05):
            code, _, killed = worker.limited(["bash", "-c", "echo a; sleep 1; echo b"], 30,
                                             silence=30, activity=activity, stdout=out,
                                             stderr=subprocess.STDOUT, quiet=quiet)
        self.assertEqual((code, killed, len(quiet)), (0, False, 1))
        self.assertGreater(quiet[0], .9)
        self.assertLess(quiet[0], 10)


if __name__ == "__main__":
    unittest.main()
