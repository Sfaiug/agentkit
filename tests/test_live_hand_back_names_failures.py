"""A red live check hands its failures and closing summary to the seat, in one bounded line.

Offline: a temporary HOME and check output; both Git and the receiving seat are fakes.
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
from agentkit import config, update, watch

COMMIT = "abcdef0123456789" * 2 + "abcdef01"
FAILURES = [
    "FAIL  4 ak run: exit=0 rundir=fixture delivery-exit=1",
    "      command=python3 tests/verify_delivery.py",
    "      exit=1 log=fixture/delivery.log",
    "FAIL  6 acme meter: missing reading",
    "      expected a usage window",
]
SUMMARY = "113 passed, 2 failed, 0 skipped"
ENDING = ["----", SUMMARY, "acceptance: FAILED (see fixture)", "[exit 1]"]
PASSES = [f"PASS  {n} acme check" for n in range(20, 60)]


class LiveHandBackNamesFailures(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-live-hand-back-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.check = self.root / "check"
        self.check.mkdir()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", config.HOME / "state"))
        stack.enter_context(patch.object(update, "_git", return_value=(
            0, "https://github.com/acme/agentkit.git")))
        self.deliver = stack.enter_context(patch.object(watch, "after_merge_deliver",
                                                       return_value=True))
        self.logs = []

    def hand_back(self, lines, code=1):
        output = "output.tmp" if code is None else "output"
        (self.check / output).write_text("\n".join(lines) + "\n")
        update.live_hand_back(COMMIT, self.check, code, self.logs.append)
        self.deliver.assert_called_once()
        line = self.deliver.call_args.args[3]
        self.assertNotIn("\n", line)
        return line

    def test_each_failure_and_its_diagnostics_precede_the_summary_past_the_tail(self):
        line = self.hand_back([*FAILURES, *PASSES, *ENDING])
        previous = -1
        for failure in FAILURES:
            self.assertIn(failure, line)
            position = line.index(failure)
            self.assertGreater(position, previous)
            self.assertLess(position, line.index(SUMMARY))
            previous = position
        self.assertIn("acceptance: FAILED (see fixture) / [exit 1]", line)

    def test_failures_in_the_tail_are_not_repeated(self):
        line = self.hand_back([*PASSES, *FAILURES, *ENDING])
        for failure in FAILURES:
            self.assertEqual(line.count(failure), 1)
        self.assertLess(line.index(FAILURES[0]), line.index(SUMMARY))

    def test_an_unfinished_check_keeps_failures_and_says_it_was_stopped(self):
        line = self.hand_back([*FAILURES, *PASSES, "live: waiting"], code=None)
        for failure in FAILURES:
            self.assertIn(failure, line)
        self.assertTrue(line.endswith("[stopped before it finished]. Fix main."))

    def test_without_fail_lines_the_last_ten_nonblank_lines_still_explain_the_exit(self):
        output = [*PASSES, "", "live: runner could not start", "[exit 1]"]
        line = self.hand_back(output)
        tail = [part for part in output if part.strip()][-10:]
        self.assertIn(" / ".join(tail), line)
        self.assertNotIn(PASSES[0], line)

    def test_many_failures_are_bounded_and_omissions_are_named_before_the_summary(self):
        failures = [part for n in range(80) for part in (
            f"FAIL  {n} acme check", "      diagnostic " + "x" * 1000)]
        summary = "0 passed, 80 failed, 0 skipped"
        line = self.hand_back([*failures, *PASSES, summary, "[exit 1]"])
        self.assertLessEqual(len(line), 4500)
        self.assertIn("FAIL  0 acme check", line)
        self.assertIn("[70 more failed checks omitted]", line)
        self.assertLess(line.index("[70 more failed checks omitted]"), line.index(summary))
        self.assertIn("[exit 1]", line)

    def test_long_diagnostics_and_tail_are_bounded_without_losing_the_summary(self):
        line = self.hand_back([
            FAILURES[0], "      " + "x" * 10000,
            *(f"PASS  {n} " + "y" * 3000 for n in range(20)), *ENDING])
        self.assertLessEqual(len(line), 4500)
        self.assertIn(FAILURES[0], line)
        self.assertIn("[output truncated]", line)
        self.assertIn(SUMMARY, line)
        self.assertIn("[exit 1]", line)


if __name__ == "__main__":
    unittest.main()
