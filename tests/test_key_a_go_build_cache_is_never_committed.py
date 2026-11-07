"""A Go build cache an executor's command made inside the checkout is never committed with its work.

ak commits what an executor leaves uncommitted, so the reviewer sees a real diff.  A check that
points GOCACHE inside the checkout leaves thousands of cache files there under whatever name it
chose, and committing them refused a run on its size before any review.  So the leftover commit
leaves out every directory holding the README Go writes at a build cache's root, with everything
below it, names it in the run's log with the other junk, and leaves it in place, unstaged.
The log names it even when the project's .gitignore does, which hides it from Git's list of
untracked files.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with scripted harnesses from fakeadapter.py.
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
# What Go writes at the root of every build cache, whatever GOCACHE names it.
README = ("This directory holds cached build artifacts from the Go build system.\n"
          'Run "go clean -cache" if the directory is getting too large.\n'
          'Run "go clean -fuzzcache" to delete the fuzz cache.\n'
          "See golang.org to learn more about Go.\n")
# A cache under a name of the check's own, laid out as Go lays one out.
CACHE = {"tools/warm/README": README, "tools/warm/trim.txt": "1793046000",
         "tools/warm/3f/3f9a0c-a": "v1 3f9a0c 1d2e 1793046000\n",
         "tools/warm/3f/3f9a0c-d": "compiled\n"}
# Writes its work beside the cache, and commits neither.
LEFTOVER = {"write": {"retry.txt": "hello\n", **CACHE},
            "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}


class AGoBuildCacheIsNeverCommitted(unittest.TestCase):
    PROJECT = {}                        # what the project's main holds besides the rig's own

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files=cls.PROJECT)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude=LEFTOVER, codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_branch_holds_the_work_and_not_the_cache(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual(self.rig.files(BRANCH, remote=False),
                         sorted([".keep", "AGENTS.md", "retry.txt", *self.PROJECT]))

    def test_the_log_names_the_cache_as_left_out(self):
        lines = {line.split("] ", 1)[-1]
                 for line in (self.run_dir / "log.txt").read_text().splitlines()}
        self.assertIn(f"left {len(CACHE)} untracked sandbox files uncommitted: "
                      + ", ".join(sorted(CACHE)[:3]), lines)

    def test_the_cache_stays_in_the_checkout_unstaged(self):
        worktree = Path(self.state["worktree"])
        for relative, text in CACHE.items():
            self.assertEqual((worktree / relative).read_text(), text)
        self.assertEqual(self.home.run("git", "-C", str(worktree), "ls-files", "--stage",
                                       "--", "tools").out, "")


class AnIgnoredGoBuildCacheIsNamedToo(AGoBuildCacheIsNeverCommitted):
    PROJECT = {".gitignore": "tools/warm/\n"}


if __name__ == "__main__":
    unittest.main()
