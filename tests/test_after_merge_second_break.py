"""A break on a later merge is told even while an earlier told break is in the window.

Offline: a temporary HOME, fake run records, faked check statuses and fake seats.
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
from agentkit import config, orch, run, watch
from agentkit import record

PR = "https://github.com/acme/widget/pull/"
NOW = 2000000
A, B = "a" * 40, "b" * 40


class SecondBreak(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-after-merge-second-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root)}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        config.ensure_dirs()
        self.checks = {}
        self.typed = []
        self.rows = [{"name": seat, "created": 100, "exited": False}
                     for seat in ("fix-api", "fix-ui")]
        stack.enter_context(patch.object(
            watch, "after_merge_status",
            lambda owner, repo, host, sha, log: self.checks.get(sha, ("pending", None, None))))
        stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        stack.enter_context(patch.object(orch, "find", lambda name: next(
            (seat for seat in self.rows if seat["name"] == name), None)))
        stack.enter_context(patch.object(
            watch, "type_at_prompt",
            lambda seat, line, log, **_kw: self.typed.append((seat["name"], line)) or True))

    def merged(self, name, sha, number, seat, age):
        directory = config.RUNS / name
        directory.mkdir()
        record.save_state(directory, {
            "run_id": name, "state": "pass", "merged": True, "pr": f"{PR}{number}",
            "merge_sha": sha, "target": "origin/main", "launched_session": seat,
            "started_at": NOW - age - 60, "finished_at": NOW - age})

    def test_later_break_is_told_after_the_earlier_commit_goes_green(self):
        state = {}
        self.merged("run-a", A, 1, "fix-api", age=1800)
        self.checks[A] = ("failed", "gate-a", PR + "1/checks")
        watch.after_merge_checks(state, False, lambda line: None, now=NOW)
        self.assertEqual([seat for seat, _ in self.typed], ["fix-api"])

        self.checks[A] = ("passed", None, None)
        self.merged("run-b", B, 2, "fix-ui", age=600)
        self.checks[B] = ("failed", "gate-b", PR + "2/checks")
        watch.after_merge_checks(state, False, lambda line: None, now=NOW)
        self.assertEqual(len(self.typed), 2, self.typed)
        seat, line = self.typed[1]
        self.assertEqual(seat, "fix-ui")
        self.assertIn("gate-b", line)

    def test_a_pending_notice_ends_when_its_own_commit_goes_green(self):
        state = {}
        self.merged("run-a", A, 1, "fix-api", age=1800)
        self.checks[A] = ("failed", "gate-a", PR + "1/checks")

        def stuck(seat, line, log, receipt, **_kw):
            receipt("mark")
            self.typed.append((seat["name"], line))
            return False

        with patch.object(watch, "type_at_prompt", stuck):
            watch.after_merge_checks(state, False, lambda line: None, now=NOW)
        self.assertEqual([seat for seat, _ in self.typed], ["fix-api"])

        self.checks[A] = ("passed", None, None)
        self.merged("run-b", B, 2, "fix-ui", age=600)
        self.checks[B] = ("failed", "gate-b", PR + "2/checks")
        watch.after_merge_checks(state, False, lambda line: None, now=NOW)
        self.assertEqual(len(self.typed), 2, self.typed)
        seat, line = self.typed[1]
        self.assertEqual(seat, "fix-ui")
        self.assertIn("gate-b", line)


if __name__ == "__main__":
    unittest.main()
