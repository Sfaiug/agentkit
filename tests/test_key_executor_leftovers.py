"""What the executor leaves uncommitted is committed for it; sandboxes and dependencies are not.

An executor that writes its work and forgets to commit it would be reviewed on an empty diff,
and a review of nothing still gives a verdict.  So before a round's checks run, ak commits the
dirty files on the run's branch itself and says so in the run's log, leaving out a test's
sandbox (`.ak-test-*`) and a dependency tree (`node_modules`), and it names the usual build
junk in the clone's own exclude file so no run commits it.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, with
scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

BRANCH = "ak/add-retry-file"
# Writes its work beside a dependency tree and a test's sandbox, and commits none of it.
LEFTOVER = {"write": {"retry.txt": "hello\n", "node_modules/x/j.js": "x\n",
                      ".ak-test-sand": "s\n"},
            "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}


class ExecutorLeftovers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude=LEFTOVER, codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_uncommitted_work_is_committed_on_the_run_branch_without_the_junk(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual(self.rig.files(BRANCH, remote=False), [".keep", "retry.txt"])
        self.assertEqual(self.rig.git("rev-list", "--count", f"main..{BRANCH}"), "1")
        self.assertEqual(self.rig.git("log", "-1", "--format=%s", BRANCH), "Add retry file")

    def test_the_log_says_what_was_committed_and_what_was_left_out(self):
        lines = {line.split("] ", 1)[-1]
                 for line in (self.run_dir / "log.txt").read_text().splitlines()}
        for line in ("WARN committed uncommitted executor changes: retry.txt",
                     "left 2 untracked sandbox files uncommitted: .ak-test-sand, "
                     "node_modules/x/j.js"):
            self.assertIn(line, lines)

    def test_the_checkout_is_clean_and_the_dependency_tree_stays_in_place(self):
        worktree = Path(self.state["worktree"])
        self.assertEqual(self.home.run("git", "-C", str(worktree), "status", "--porcelain",
                                       "--untracked-files=no").out, "")
        self.assertEqual((worktree / "node_modules/x/j.js").read_text(), "x\n")

    def test_build_junk_is_named_in_the_clone_s_own_exclude_file(self):
        exclude = (self.rig.path / ".git/info/exclude").read_text().splitlines()
        for pattern in ("node_modules/", "__pycache__/"):
            self.assertIn(pattern, exclude)


if __name__ == "__main__":
    unittest.main()
