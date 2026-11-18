"""A round's check of its chosen tests passes a run that failed only by naming one of them not
there (`AK_NOT_THERE`): run once, its exit 0 in the gate log, so a review resumed on that log
settles as the round did.  It fails where the run names anything else as failed, a part of a
file handed whole too, or ends on a signal's status; and a test that failed, then passed on the
re-run beside the part not there keeps its flaky record, the part no flaky test.

Offline, with real Git and shell runners; `round_tests.chosen` stands in for the time record.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, prompts, roundloop, run

# A runner as ak's own (tests/every_file.py) names a handed part its file does not hold: not
# there and failed, never run, failing the run.  Each other test is named as run, then `{then}`.
RUNNER = ('echo run >> .git/runs; code=0; while read -r test; do case "$test" in '
          '*::dropped) echo "$test" | tee -a "$AK_FAILED" >> "$AK_NOT_THERE"; code=1 ;; '
          '*) echo "$test" >> "$AK_RAN"; {then} ;; esac; done < "$AK_ONLY"; exit $code')
PASSES = 'echo "PASS  $test (0.1s)"'
TESTS = ["tests/parts.py::dropped", "tests/check.py"]


class ARoundPassesATestItsTreeNoLongerHolds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-not-there-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(tempfile, "tempdir", str(self.root)))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off"}))
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        run.git(self.repo, "init", "-b", "main")
        run.git(self.repo, "config", "user.name", "fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "api.py").write_text("fixture\n")
        run.git(self.repo, "add", "-A")
        run.git(self.repo, "commit", "-m", "baseline")
        base = run.git(self.repo, "rev-parse", "HEAD")
        run.git(self.repo, "checkout", "-b", "ak/fix-api")
        directory = config.RUNS / "fix-api"
        (directory / "round-1").mkdir(parents=True)
        state = {"title": "fix api", "base": "main", "base_sha": base, "rounds": 1,
                 "executor": "opus", "reviewer": "astra", "round_summaries": []}
        self.lp = run.Loop(config.load(), directory, state, {}, lambda text: None, self.repo,
                           "# Fix the api", ["true"], "context")
        self.lp.rnd = 1

    def check(self, then):
        """The round's checks with RUNNER as the target's `tests:` line, handed TESTS: (whether
        they passed, their log, how often the runner ran, the flaky tests each command kept)."""
        line = RUNNER.replace("{then}", then)
        with patch.object(roundloop.round_tests, "chosen", return_value=(line, TESTS)), \
                patch.object(gate.history, "test_reds") as kept:
            ok, text = roundloop.verify_work(self.lp)
            # a review cut off and resumed reads the gate's log, never the gate's answer
            self.lp.state["step"] = "reviewer"
            self.assertEqual(roundloop.settled_gate(self.lp), (ok, text))
        self.assertEqual(prompts.done_when_counts(text, ["true", line]), (1 + ok, 2), text)
        runs = len((self.repo / ".git/runs").read_text().splitlines())
        # each command's kept under its check; a go's own call names none (`gate.run_suite`)
        return ok, text, runs, [call.args[2] for call in kept.call_args_list if call.args[0]]

    def test_a_run_failing_only_by_the_part_not_there_passes_once(self):
        ok, text, runs, flaky = self.check(PASSES)
        self.assertTrue(ok, text)
        self.assertEqual(runs, 1, text)
        self.assertIn("\n[not there (AK_NOT_THERE), counted as passed: tests/parts.py::dropped]",
                      text)
        self.assertEqual(flaky, [[], []])

    def test_a_failed_part_of_a_file_handed_whole_fails_the_round(self):
        ok, text, runs, _ = self.check('echo "$test::fix_api" >> "$AK_FAILED"; code=1')
        self.assertFalse(ok, text)
        self.assertEqual(runs, 2, text)     # red, its re-run red

    def test_a_run_ended_on_a_signals_status_fails_the_round(self):
        # the test dies of SIGTERM, named as run alone, and its runner exits as a shell says so
        ok, text, runs, _ = self.check("bash -c 'kill -TERM $$' || exit $?")
        self.assertFalse(ok, text)
        self.assertIn("\n[exit 143]\n", text)
        self.assertEqual(runs, 2, text)

    def test_a_test_passing_only_on_the_re_run_keeps_its_flaky_record(self):
        ok, text, runs, flaky = self.check(
            f'if [ -e .git/tried ]; then {PASSES}; else touch .git/tried; '
            'echo "FAIL $test"; echo "$test" >> "$AK_FAILED"; code=1; fi')
        self.assertTrue(ok, text)
        self.assertEqual(runs, 2, text)
        state = {}
        prompts.record_flakes(state, text)
        record, = state["followups"]
        self.assertIn("FAIL tests/check.py", record)
        self.assertEqual(flaky, [[], ["tests/check.py"]])    # the part not there is none


if __name__ == "__main__":
    unittest.main()
