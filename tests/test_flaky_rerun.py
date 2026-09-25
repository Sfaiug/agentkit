"""A done-when line that fails once and passes on its re-run is a flake, not a failed round.

Baseline: a temporary HOME, a run record whose repository is only a path, and short shell
commands that count their own runs in a file; nothing touches the real ~/.agentkit.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

ACME = "/home/fixture/code/acme"        # the main checkout as the record names it; never opened
RUN_ID = "20260101-0900-flaky-fixture"


class FlakyRerun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".flaky-rerun-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which the gate's end sweeps;
        # AK_MAX_RUNS=0 takes no gate turn, which test_gate_turns covers
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        config.RUNS.mkdir(parents=True)
        self.run_dir = config.RUNS / RUN_ID
        self.run_dir.mkdir()
        self.state = {"run_id": RUN_ID, "title": "flaky", "state": "running", "verdict": None,
                      "repo": ACME, **run.process_owner(), "started_at": time.time(),
                      "round_summaries": []}
        run.save_state(self.run_dir, self.state)
        self.runs = self.root / "runs.txt"      # one line per run of a command
        self.runs.touch()
        self.followups = config.HOME / "followups" / "acme.md"

    def check(self, then):
        """A command that fails its first run with a line of its own, and does `then` after."""
        q = shlex.quote
        return (f"echo ran >> {q(str(self.runs))}; if test -f {q(str(self.root / 'seen'))}; "
                f"then {then}; else touch {q(str(self.root / 'seen'))}; echo starting; "
                f"echo; echo 'FAIL: too slow under load'; exit 1; fi")

    def gate(self, cmds):
        logs = []
        ok, text = run.run_done_when(cmds, self.root, self.run_dir / "donewhen.log", set(),
                                     limit=60, log=logs.append, run_dir=self.run_dir)
        return ok, text, logs

    def count(self):
        return len(self.runs.read_text().splitlines())

    def test_a_fail_then_a_pass_passes_with_a_flaky_note_and_one_followup(self):
        cmd = self.check("echo all good")
        ok, text, logs = self.gate([cmd, "true"])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        self.assertIn(f"$ {cmd}\n[exit 0]\nall good\n\n"
                      f"flaky: {cmd} failed, then passed on its re-run\n"
                      "starting\nFAIL: too slow under load\n\n$ true\n[exit 0]", text)
        self.assertEqual(run.done_when_counts(text, [cmd, "true"]), (2, 2))
        self.assertEqual(run.failing_checks(text), [])
        self.assertEqual(logs, [f"done-when: flaky: {cmd} failed, then passed on its re-run"])
        lines = self.followups.read_text().splitlines()
        self.assertEqual(len(lines), 1, lines)
        day = time.strftime("%Y-%m-%d", time.localtime())
        self.assertEqual(lines[0], f"- {day} run {RUN_ID}: flaky: {cmd} failed, then passed "
                                   "on its re-run; its first failure ended: "
                                   "FAIL: too slow under load")

    def test_a_second_failure_fails_and_runs_exactly_twice(self):
        cmd = self.check("echo 'FAIL: still broken'; exit 1")
        ok, text, logs = self.gate([cmd])
        self.assertFalse(ok)
        self.assertEqual(self.count(), 2)
        self.assertEqual(text, f"$ {cmd}\n[exit 1]\nFAIL: still broken")
        self.assertEqual(run.failing_checks(text), [[cmd, "FAIL: still broken"]])
        self.assertEqual(logs, [])
        self.assertFalse(self.followups.exists())

    def test_a_pass_runs_once(self):
        cmd = f"echo ran >> {shlex.quote(str(self.runs))}; echo fine"
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 1)
        self.assertEqual(text, f"$ {cmd}\n[exit 0]\nfine")
        self.assertEqual(logs, [])
        self.assertFalse(self.followups.exists())

    def test_a_stop_during_the_rerun_ends_the_gate_as_a_stop_mid_list_does(self):
        # the re-run marks the record stopped, as `ak run stop` does, and is killed by it
        stopped = self.root / "stopped.json"
        stopped.write_text(json.dumps({**self.state, "state": "stopped"}))
        record = self.run_dir / "run.json"
        cmd = self.check(f"cp {shlex.quote(str(stopped))} {shlex.quote(str(record))}; exit 143")
        after = f"echo after >> {shlex.quote(str(self.runs))}"
        with self.assertRaises(run.StopRequested):
            self.gate([cmd, after])
        self.assertEqual(self.runs.read_text(), "ran\nran\n")
        self.assertFalse(self.followups.exists())

    def test_a_stop_during_the_first_run_starts_no_rerun(self):
        stopped = self.root / "stopped.json"
        stopped.write_text(json.dumps({**self.state, "state": "stopped"}))
        cmd = (f"echo ran >> {shlex.quote(str(self.runs))}; "
               f"cp {shlex.quote(str(stopped))} {shlex.quote(str(self.run_dir / 'run.json'))}; "
               "exit 143")
        with self.assertRaises(run.StopRequested):
            self.gate([cmd])
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
