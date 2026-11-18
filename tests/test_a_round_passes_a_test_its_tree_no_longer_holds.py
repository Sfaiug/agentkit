"""A round's check of its chosen tests hands one its tree no longer holds once: the line fails
naming it not there (`AK_NOT_THERE`) and not as run, then runs without it, and that run's exit
decides, in the gate log as it was, so a review resumed on that log settles as the round did.
What failed beside it fails the run without it too.  A test named as run is left out of none,
nor is one named not there by a run that passed or by a re-run alone; and a test that failed
beside it, then passed, keeps its flaky record, the part no flaky test.

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
# Each run notes the tests it was handed, a line of .git/runs.
RUNNER = ('tr "\\n" " " < "$AK_ONLY" >> .git/runs; echo >> .git/runs; code=0; '
          'while read -r test; do case "$test" in *::dropped) {gone} ;; '
          '*) echo "$test" >> "$AK_RAN"; {then} ;; esac; done < "$AK_ONLY"; {last}')
GONE = 'echo "$test" | tee -a "$AK_FAILED" >> "$AK_NOT_THERE"; code=1'
PASSES = 'echo "PASS  $test (0.1s)"'
ONCE = 'if [ -e .git/tried ]; then {again}; else touch .git/tried; {first}; fi'
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

    def check(self, then=PASSES, gone=GONE, last="exit $code", tests=TESTS):
        """The round's checks with RUNNER as the target's `tests:` line, handed `tests`: (whether
        they passed, their log, the tests each run of the line was handed, the flaky tests each
        command kept)."""
        for marker in ("runs", "tried"):
            (self.repo / ".git" / marker).unlink(missing_ok=True)
        line = RUNNER.format(then=then, gone=gone, last=last)
        with patch.object(roundloop.round_tests, "chosen", return_value=(line, tests)), \
                patch.object(gate.history, "test_reds") as kept:
            ok, text = roundloop.verify_work(self.lp)
            # a review cut off and resumed reads the gate's log, never the gate's answer
            self.lp.state["step"] = "reviewer"
            self.assertEqual(roundloop.settled_gate(self.lp), (ok, text))
        self.assertEqual(prompts.done_when_counts(text, ["true", line]), (1 + ok, 2), text)
        runs = [handed.split() for handed in (self.repo / ".git/runs").read_text().splitlines()]
        # each command's kept under its check; a go's own call names none (`gate.run_suite`)
        return ok, text, runs, [call.args[2] for call in kept.call_args_list if call.args[0]]

    def followups(self, text):
        state = {}
        prompts.record_flakes(state, text)
        return state.get("followups", [])

    def test_the_line_runs_again_without_the_part_not_there_and_that_exit_decides(self):
        ok, text, runs, flaky = self.check()
        self.assertTrue(ok, text)
        self.assertEqual(runs, [TESTS, TESTS[1:]], text)
        self.assertIn("\n[not handed, named as not there (AK_NOT_THERE): tests/parts.py::dropped]",
                      text)
        self.assertEqual((flaky, self.followups(text)), ([[], []], []))

    def test_with_no_test_left_the_line_runs_handed_none(self):
        ok, text, runs, _ = self.check(tests=TESTS[:1])
        self.assertTrue(ok, text)
        self.assertEqual(runs, [TESTS[:1], []], text)

    def test_a_failed_part_of_a_file_handed_whole_fails_the_round(self):
        ok, text, runs, _ = self.check('echo "$test::fix_api" >> "$AK_FAILED"; code=1')
        self.assertFalse(ok, text)
        self.assertEqual(runs, [TESTS, TESTS[1:]], text)

    def test_a_failure_that_names_no_test_fails_the_round(self):
        # as a step after the tests does, or the limit a runner sets itself: by its files that
        # run is the one that failed only by the part not there
        ok, text, runs, _ = self.check(last="echo no coverage; exit 1")
        self.assertFalse(ok, text)
        self.assertIn("\n[exit 1]\n", text)
        self.assertEqual(runs, [TESTS, TESTS[1:], TESTS[1:]], text)
        self.assertEqual(prompts.failing_checks(text)[0][1], "no coverage")
        self.assertTrue(prompts.first_failure(text).endswith("no coverage"), text)

    def test_a_part_named_as_run_too_is_handed_again(self):
        # a file's own re-run found the part and failed it (tests/every_file.py runs one)
        ok, text, runs, _ = self.check(gone=f'{GONE}; echo "$test" >> "$AK_RAN"')
        self.assertFalse(ok, text)
        self.assertEqual(runs, [TESTS, TESTS], text)

    def test_a_run_exiting_0_that_names_the_part_not_there_fails_as_ever(self):
        ok, text, runs, _ = self.check(last="exit 0")
        self.assertFalse(ok, text)
        self.assertIn("\n[not named as run (AK_RAN): tests/parts.py::dropped]", text)
        self.assertEqual(runs, [TESTS, TESTS], text)

    def test_a_test_that_failed_then_is_named_not_there_fails_the_round(self):
        ok, text, runs, flaky = self.check(tests=TESTS[:1], gone=ONCE.format(
            first='echo "$test" | tee -a "$AK_RAN" >> "$AK_FAILED"; code=1', again=GONE))
        self.assertFalse(ok, text)
        self.assertEqual(runs, [TESTS[:1], TESTS[:1]], text)
        self.assertEqual((flaky, self.followups(text)), ([[], []], []))     # it passed no run

    def test_an_unrun_test_named_as_failed_beside_the_part_is_no_flaky_test(self):
        ok, text, runs, flaky = self.check(
            gone=f'{GONE}; echo tests/check.py >> "$AK_FAILED"; exit 1')
        self.assertTrue(ok, text)
        self.assertEqual(runs, [TESTS, TESTS[1:]], text)
        self.assertEqual((flaky, self.followups(text)), ([[], []], []))

    def test_a_test_passing_only_on_the_re_run_keeps_its_flaky_record(self):
        for named, expected in (("$test", "tests/check.py"),
                                ("$test::fix_api", "tests/check.py::fix_api")):
            with self.subTest(named=expected):
                ok, text, runs, flaky = self.check(ONCE.format(
                    first=f'echo "FAIL {named}"; echo "{named}" >> "$AK_FAILED"; code=1',
                    again=PASSES))
                self.assertTrue(ok, text)
                self.assertEqual(runs, [TESTS, TESTS[1:]], text)
                record, = self.followups(text)
                self.assertIn(f"FAIL {expected}", record)
                self.assertEqual(flaky, [[], [expected]])   # the part not there is none


if __name__ == "__main__":
    unittest.main()
