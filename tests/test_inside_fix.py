"""A finding sits inside the fix where its line is one the fix wrote: the new side of git's diff
from the commit the last review judged, renames followed.  A pure removal writes no line, so its
surviving neighbours are outside; a renamed file's unchanged lines are outside too.  Offline: a
real git repository, read by `prompts.inside_fix`.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import prompts


class InsideFix(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-inside-fix-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "acme")
        self.git("config", "user.email", "acme@example.invalid")
        (self.root / "words.txt").write_text("alpha\nbeta\ngamma\ndelta\n")
        self.reviewed = self.commit("the reviewed commit")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def inside(self, path, lines, head, since=None):
        lp = SimpleNamespace(wt=self.root)
        return [prompts.inside_fix(lp, {"path": path, "line": line}, since or self.reviewed, head)
                for line in lines]

    def test_a_changed_line_is_inside_and_the_rest_outside(self):
        (self.root / "words.txt").write_text("alpha\nBeta\ngamma\ndelta\n")
        self.assertEqual(self.inside("words.txt", (1, 2, 3), self.commit("fix")), [0, 1, 0])

    def test_a_pure_removal_leaves_its_neighbours_outside(self):
        (self.root / "words.txt").write_text("alpha\ngamma\ndelta\n")
        self.assertEqual(self.inside("words.txt", (1, 2, 3), self.commit("fix")), [0, 0, 0])

    def test_a_renamed_file_s_unchanged_lines_are_outside(self):
        self.git("mv", "words.txt", "renamed.txt")
        self.assertEqual(self.inside("renamed.txt", (1, 2), self.commit("rename")), [0, 0])
        (self.root / "renamed.txt").write_text("alpha\nbeta\nGAMMA\ndelta\n")
        self.assertEqual(self.inside("renamed.txt", (2, 3), self.commit("edit")), [0, 1])

    def test_an_added_file_is_inside_and_an_untouched_one_outside(self):
        (self.root / "new.txt").write_text("one\n")
        head = self.commit("add")
        self.assertEqual(self.inside("new.txt", (1,), head) + self.inside("words.txt", (1,), head),
                         [1, 0])

    def test_no_reviewed_commit_no_line_or_an_unreadable_diff_is_unknown(self):
        head = self.git("rev-parse", "HEAD")
        lp = SimpleNamespace(wt=self.root)
        self.assertIsNone(prompts.inside_fix(lp, {"path": "words.txt", "line": 1}, None, head))
        self.assertIsNone(prompts.inside_fix(lp, {"kind": "done"}, self.reviewed, head))
        self.assertEqual(self.inside("words.txt", (1,), head, since="0" * 40), [None])


if __name__ == "__main__":
    unittest.main()
