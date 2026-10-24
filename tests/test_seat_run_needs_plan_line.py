"""A seat's own launch, of a task or of a PR review, waits for an open line in its plan: the plan
is what its bar counts and what a review of its pull request checks against, so a seat with no
plan, or one whose every line is done, is refused and told to `ak plan add` first.  Any open line
lets it go, a deferred follow-up's too.  A launch from no seat, or from inside a run (a queued
child `spawn_bg` starts under the seat's name), goes ahead plan or no plan.

Offline: the bin/ak entry point with a temporary HOME and launch effects mocked out.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, plan

AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]
SEAT = "fix-api"
PR = "https://github.com/acme/widget/pull/7"
OPEN = plan.compose("The api answers", "check: `python3 tests/test_api.py`", "acme", False,
                    "2026-10-23 09:00", "1234567")
DEFERRED = plan.compose("The api retries", "check: `python3 tests/test_retry.py`", "acme", True,
                        "2026-10-23 09:00", "1234567")
DONE = OPEN.replace("- [ ] ", "- [x] ", 1) + " · done 89abcde 2026-10-23 10:00"


class SeatRunNeedsPlanLine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seat-plan-line-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", config.SESSION_ENV: SEAT,
            config.RUN_DIR_ENV: "", "AK_RUN_ROLE": ""}))
        config.ensure_dirs()
        config.save_session(config.load(), SEAT, "opus", ["opus"], {"reviewers": ["astra"]})
        # the first step past the refusals, where a launch that goes ahead stops here
        self.ahead = stack.enter_context(patch.object(box, "check", side_effect=config.Error("ahead")))
        self.task = self.root / "fix-api.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the api\n\n## Done when\n```bash\ntrue\n```\n")

    def launch(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", *map(str, args)]), \
                redirect_stdout(out), redirect_stderr(err):
            code = AK_MAIN()
        return code, err.getvalue()

    def test_a_seat_with_no_open_line_is_refused(self):
        for lines in ([], [DONE]):
            plan.write(SEAT, lines)
            for args in ((self.task,), ("--review-pr", PR)):
                with self.subTest(lines=lines, launch=args[0]):
                    code, err = self.launch(*args)
                    self.assertEqual(code, 2, err)
                    self.assertIn("ak plan add \"<outcome>\" --check '<command>'", err)
                    self.assertIn("what your bar counts", err)
        self.ahead.assert_not_called()

    def test_an_open_line_or_a_deferred_one_lets_the_seat_launch(self):
        for lines in ([DONE, OPEN], [DONE, DEFERRED]):
            plan.write(SEAT, lines)
            with self.subTest(lines=lines):
                for args in ((self.task,), ("--review-pr", PR)):
                    self.assertEqual(self.launch(*args), (2, "ak run: ahead\n"))

    def test_no_seat_and_a_run_s_child_launch_with_no_plan(self):
        for env in ({config.SESSION_ENV: ""}, {config.RUN_DIR_ENV: str(config.RUNS / "a-run")}):
            for args in ((self.task,), ("--review-pr", PR)):
                with self.subTest(env=env, launch=args[0]), patch.dict(os.environ, env):
                    self.assertEqual(self.launch(*args), (2, "ak run: ahead\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
