"""A task with `repo: none` works in a workspace of its own and delivers the files it leaves.

Not every job lives in a repository: a scratch task gets an empty workspace under
HOME/.agentkit/work, named for its run, instead of a checkout, so there is no branch to push,
no PR to open and nothing to merge.  When its work passes review, the files in that workspace
are the delivery: the run ends `PASS, delivered` and result.md lists each file as a link a
person can open.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a task from taskfile.py and scripted harnesses from
fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home


class ScratchRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, "none", "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.workspace = cls.home.path / ".agentkit/work" / cls.run_dir.name

    def test_the_run_ends_pass_delivered_and_says_where_its_result_is(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, delivered -> {self.run_dir / 'result.md'}"), last)
        self.assertEqual((self.state.get("state"), self.state.get("verdict")), ("pass", "PASS"))

    def test_the_work_is_done_in_a_workspace_of_its_own_with_no_checkout(self):
        self.assertEqual({key: self.state.get(key) for key in (
            "scratch", "repo", "worktree", "branch", "pr", "merged")}, {
            "scratch": True, "repo": None, "worktree": str(self.workspace), "branch": None,
            "pr": None, "merged": False})
        self.assertEqual(sorted(path.name for path in self.workspace.iterdir()), ["retry.txt"])
        self.assertFalse((self.home.path / ".agentkit/wt" / self.run_dir.name).exists())
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))
        # retry.txt is only in the workspace, so the check passing says it ran there.
        checks = (self.run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ test -f retry.txt", checks)
        self.assertIn("[exit 0]", checks)

    def test_result_md_lists_the_workspace_files_as_the_deliverables(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# PASS, delivered — Add retry file")
        self.assertIn("VERDICT: PASS", lines)
        heading = lines.index("## Deliverables")
        self.assertEqual(lines[heading + 1], f"- [retry.txt]({self.workspace / 'retry.txt'})")

    def test_nothing_is_asked_of_github(self):
        self.assertEqual(self.home.calls("gh"), [])


if __name__ == "__main__":
    unittest.main()
