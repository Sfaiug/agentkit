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
from agentkit import gate, config, host, run
from agentkit import record as run_record

ACME = "/home/fixture/code/acme"        # the main checkout as the record names it; never opened
RUN_ID = "20260101-0900-flaky-fixture"


class FlakyRerun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-flaky-rerun-", dir=REPO)
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
                      "repo": ACME, **run_record.process_owner(), "started_at": time.time(),
                      "round_summaries": []}
        run_record.save_state(self.run_dir, self.state)
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
        ok, text = gate.run_done_when(cmds, self.root, self.run_dir / "donewhen.log", set(),
                                     limit=60, log=logs.append, run_dir=self.run_dir)
        return ok, text, logs

    def count(self):
        return len(self.runs.read_text().splitlines())

    def evidence(self, text, cmd):
        record = text.split(f"flaky: {cmd} failed, then passed on its re-run\n", 1)[1]
        record = record.split("\n\n")[0]
        reference, _, excerpt = record.partition("\n")
        self.assertTrue(reference.startswith("failed output: "), record)
        saved = Path(reference.removeprefix("failed output: "))
        self.assertEqual(saved.parent, self.run_dir)
        return saved, excerpt

    def test_a_fail_then_a_pass_keeps_flaky_evidence_without_a_followup_file(self):
        cmd = self.check("echo all good")
        ok, text, logs = self.gate([cmd, "true"])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        saved, _ = self.evidence(text, cmd)
        self.assertIn(f"$ {cmd}\n[exit 0]\nall good\n\n"
                      f"flaky: {cmd} failed, then passed on its re-run\n"
                      f"failed output: {saved}\n"
                      "starting\nFAIL: too slow under load\n\n$ true\n[exit 0]", text)
        self.assertEqual(saved.read_text(), "starting\n\nFAIL: too slow under load\n")
        self.assertEqual(run.done_when_counts(text, [cmd, "true"]), (2, 2))
        self.assertEqual(run.failing_checks(text), [])
        self.assertEqual(logs, [f"done-when: flaky: {cmd} failed, then passed on its re-run"])
        self.assertFalse(self.followups.parent.exists())

    def test_a_failure_above_a_long_shared_tail_still_names_it(self):
        q = shlex.quote
        tail = "; ".join(f"echo shared line {i}" for i in range(25))
        cmd = (f"echo ran >> {q(str(self.runs))}; if test -f {q(str(self.root / 'seen'))}; "
               f"then {tail}; else touch {q(str(self.root / 'seen'))}; "
               f"echo 'FAIL: the one that broke'; {tail}; exit 1; fi")
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        _, excerpt = self.evidence(text, cmd)
        self.assertEqual(excerpt, "FAIL: the one that broke")

    def test_varying_timings_ids_and_paths_do_not_hide_the_failure(self):
        def noise(seconds, session, hex_id, path):
            return "\n".join(line for i in range(25) for line in (
                f"Ran {i + 1} tests in {seconds}s",
                f"session {session}",
                f"build {hex_id}",
                f"temporary output {path}/result.txt")) + "\n"

        failed = (noise("3.748", "01a0f904-7abb-4f18-b7aa-12c34d56e789",
                        "deadbeef", "/tmp/acme-failed-xyz") + "\nFAIL  tests/test_x.py\n\n")
        passed = noise("12.5", "abcdefab-ccdf-4b12-abaa-abdefaaabcde",
                       "cafefeed", "/tmp/acme-passed-qrs")
        failed_path, passed_path = self.root / "failed.txt", self.root / "passed.txt"
        failed_path.write_text(failed)
        passed_path.write_text(passed)
        q = shlex.quote
        cmd = (f"echo ran >> {q(str(self.runs))}; if test -f {q(str(self.root / 'seen'))}; "
               f"then cat {q(str(passed_path))}; else touch {q(str(self.root / 'seen'))}; "
               f"cat {q(str(failed_path))}; exit 1; fi")
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        record = text.split(f"flaky: {cmd} failed, then passed on its re-run\n", 1)[1]
        self.assertIn("FAIL  tests/test_x.py", record)
        for label in ("Ran ", "session ", "build ", "temporary output "):
            self.assertNotIn(label, record)
        saved, _ = self.evidence(text, cmd)
        self.assertEqual(saved.read_bytes(), failed.encode())
        (self.root / "seen").unlink()
        failed_path.write_text("a different failure\n")
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        later, _ = self.evidence(text, cmd)
        self.assertNotEqual(later, saved)
        self.assertEqual(later.read_text(), "a different failure\n")
        self.assertEqual(saved.read_bytes(), failed.encode())

    def test_a_failure_above_a_tail_past_the_cap_still_names_it(self):
        q = shlex.quote
        pad = "x" * 72
        tail = f"for i in $(seq 1 300); do echo \"shared line $i {pad}\"; done"
        extra = f"for i in $(seq 1 100); do echo \"extra line $i {pad}\"; done"
        cmd = (f"echo ran >> {q(str(self.runs))}; if test -f {q(str(self.root / 'seen'))}; "
               f"then {tail}; {extra}; else touch {q(str(self.root / 'seen'))}; "
               f"echo 'FAIL: the one that broke'; {tail}; exit 1; fi")
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        saved, excerpt = self.evidence(text, cmd)
        self.assertEqual(excerpt, "FAIL: the one that broke")
        self.assertEqual(saved.read_text(), "FAIL: the one that broke\n" + "".join(
            f"shared line {i} {pad}\n" for i in range(1, 301)))

    def test_a_rerun_that_repeats_everything_keeps_only_the_file_reference(self):
        q = shlex.quote
        tail = "; ".join(f"echo repeat line {i}" for i in range(25))
        cmd = (f"echo ran >> {q(str(self.runs))}; if test -f {q(str(self.root / 'seen'))}; "
               f"then {tail}; else touch {q(str(self.root / 'seen'))}; {tail}; exit 1; fi")
        ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertEqual(self.count(), 2)
        saved, excerpt = self.evidence(text, cmd)
        self.assertEqual(excerpt, "")
        self.assertEqual(saved.read_text(), "".join(f"repeat line {i}\n" for i in range(25)))

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

    def test_only_the_red_piece_runs_again_and_keeps_its_own_evidence(self):
        q = shlex.quote
        cmd = (f'echo "$AK_SHARD" >> {q(str(self.runs))}; '
               f'if test "$AK_SHARD" = 2/2 && test ! -f {q(str(self.root / "seen"))}; '
               f'then touch {q(str(self.root / "seen"))}; echo "FAIL: under load"; exit 1; '
               'else echo passed; fi')
        with patch.object(host, "host_readings", return_value={
                "cpus": 4, "load": 0, "free_mb": 820}):
            ok, text, logs = self.gate([cmd])
        self.assertTrue(ok, text)
        self.assertCountEqual(self.runs.read_text().splitlines(), ["1/2", "2/2", "2/2"])
        saved, excerpt = self.evidence(text, f"{cmd} (AK_SHARD=2/2)")
        self.assertEqual(saved.read_text(), "FAIL: under load\n")
        self.assertEqual(excerpt, "FAIL: under load")
        self.assertEqual(run.done_when_counts(text, [cmd]), (1, 1))

    def test_a_stop_during_the_rerun_ends_the_gate_as_a_stop_mid_list_does(self):
        # the re-run marks the record stopped, as `ak run stop` does, and is killed by it
        stopped = self.root / "stopped.json"
        stopped.write_text(json.dumps({**self.state, "state": "stopped"}))
        record = self.run_dir / "run.json"
        cmd = self.check(f"cp {shlex.quote(str(stopped))} {shlex.quote(str(record))}; exit 143")
        after = f"echo after >> {shlex.quote(str(self.runs))}"
        with self.assertRaises(run_record.StopRequested):
            self.gate([cmd, after])
        self.assertEqual(self.runs.read_text(), "ran\nran\n")
        self.assertFalse(self.followups.exists())

    def test_a_stop_during_the_first_run_starts_no_rerun(self):
        stopped = self.root / "stopped.json"
        stopped.write_text(json.dumps({**self.state, "state": "stopped"}))
        cmd = (f"echo ran >> {shlex.quote(str(self.runs))}; "
               f"cp {shlex.quote(str(stopped))} {shlex.quote(str(self.run_dir / 'run.json'))}; "
               "exit 143")
        with self.assertRaises(run_record.StopRequested):
            self.gate([cmd])
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
