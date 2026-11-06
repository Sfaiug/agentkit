"""Two milestones claiming neighbouring keys merge cleanly, each claim kept, and a key claimed on
two lines runs once.

go/keys.txt holds one claim a line. This repository's own .gitattributes, in a repository of
its own, merges two branches through `git merge-tree` with both claims kept.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from suite_shares import claims

REPO = Path(__file__).resolve().parents[1]


def git(where, *argv):
    return subprocess.run(["git", "-C", str(where), "-c", "user.name=t", "-c", "user.email=t@t",
                           *argv], capture_output=True, text=True, check=False)


class NeighbouringClaims(unittest.TestCase):
    def test_both_stay_and_nothing_conflicts(self):
        with tempfile.TemporaryDirectory() as tree:
            tree = Path(tree)
            git(tree, "init", "-q", "-b", "main")
            shutil.copy(REPO / ".gitattributes", tree)
            keys = tree / "go" / "keys.txt"
            keys.parent.mkdir()
            keys.write_text("test_key_a\ntest_key_z\n")
            git(tree, "add", ".")
            git(tree, "commit", "-qm", "base")
            for branch, claim in (("one", "test_key_b"), ("two", "test_key_c")):
                git(tree, "checkout", "-q", "-b", branch, "main")
                keys.write_text(f"test_key_a\n{claim}\ntest_key_z\n")
                git(tree, "commit", "-qam", claim)
            done = git(tree, "merge-tree", "--write-tree", "one", "two")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            merged = git(tree, "show", f"{done.stdout.split()[0]}:go/keys.txt").stdout.split()
            self.assertEqual(sorted(merged),
                             ["test_key_a", "test_key_b", "test_key_c", "test_key_z"])

    def test_a_key_claimed_on_two_lines_runs_once(self):
        with tempfile.TemporaryDirectory() as tree:
            keys = Path(tree, "go", "keys.txt")
            keys.parent.mkdir()
            keys.write_text("test_key_a A.test_x\ntest_key_b B\ntest_key_a\ntest_key_b C B\n"
                            "test_key_c C.test_y\ntest_key_c C\n")
            self.assertEqual(claims(tree), [["test_key_a"], ["test_key_b", "B", "C"], ["test_key_c", "C"]])


if __name__ == "__main__":
    unittest.main()
