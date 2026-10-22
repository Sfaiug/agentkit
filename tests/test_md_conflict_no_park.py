"""Markdown-only conflicts wait for landing; any other conflicted path parks the younger.

Offline: temporary repository, worktrees and HOME from the lease fixture.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import leases, stop


class MarkdownConflictNoPark(LiveRuns):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(stop, "marker_pids", return_value=[]))
        (self.repo / "docs").mkdir()
        (self.repo / "docs/guide.md").write_text("The base guide.\n")
        (self.repo / "docs/notes.md").write_text("The base notes.\n")
        self.git(self.repo, "add", "docs")
        self.git(self.repo, "commit", "-qm", "Guides")
        self.base = self.git(self.repo, "rev-parse", "HEAD")

    def conflicting_runs(self, *paths):
        older = self.run_on(OLDER, 900, step="executor", rounds=0)
        younger = self.run_on(YOUNGER, 1000, step="executor", rounds=0)
        for path in paths:
            self.edit(older, path, 1, "The older version.", commit=True)
            self.edit(younger, path, 1, "The younger version.")
        # Prove git reports actual conflicts, even with the sentence merge driver.
        runs = leases.live(self.repo)
        trees = {each["run"]: leases.tree(each["worktree"], each["artifacts"]) for each in runs}
        self.assertEqual(leases.collide(self.repo, *runs, trees), sorted(paths))
        return older, younger

    def assert_running(self):
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        self.assertEqual(leases.read(self.repo), {})
        for name in (OLDER, YOUNGER):
            self.assertEqual(self.state(name)["state"], "running")
            self.assertNotIn("lease_wait", self.state(name))

    def test_a_markdown_conflict_leaves_both_runs_running(self):
        older, younger = self.conflicting_runs("docs/guide.md")
        # Code in the diffs is harmless when it is not among the conflicted paths.
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 25, "younger's line 25")
        self.assert_running()

    def test_several_markdown_conflicts_leave_both_runs_running(self):
        self.conflicting_runs("docs/guide.md", "docs/notes.md")
        self.assert_running()

    def test_a_markdown_and_python_conflict_still_park_the_younger(self):
        self.conflicting_runs("docs/guide.md", "api.py")
        files = ["api.py", "docs/guide.md"]
        self.assertEqual(leases.scan(self.repo, now=2000), {
            YOUNGER: {"waits_on": OLDER, "files": files, "since": 2000}})
        self.assertEqual(self.state(OLDER)["state"], "running")
        younger = self.state(YOUNGER)
        self.assertEqual(younger["state"], "stopped")
        self.assertEqual(younger["lease_wait"], {"on": OLDER, "files": files, "since": 2000})
        self.assertTrue(younger["stop_kept"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
