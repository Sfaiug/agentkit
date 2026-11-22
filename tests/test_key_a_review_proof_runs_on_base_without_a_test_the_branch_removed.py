"""A review's proof runs with the branch's tests laid over, a test the branch removed left out.

Black-box through AK_BIN, akbin, gitrig and fakeadapter: the branch removes one test base holds
and changes another.  The second round's reviewer hands in a finding outside the fix delta, so
its command runs on base and on the commit the first review judged, which no longer holds the
removed test either: git refused to restore it from the head there, and every retry of such a
run ended in error.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# it fails on every commit, so it never blocks; it says so only where the overlay is right
PROOF = "test ! -e tests/test_old.py && grep -qx branch tests/test_kept.py && echo laid over; false"


class ReviewProofWithoutARemovedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = rig = Rig(home, "widgets", files={"tests/test_old.py": "old\n",
                                                    "tests/test_kept.py": "base\n"})
        akconfig.write(home, ["opus", "astra"])
        work = {"write": {"feature.txt": "one\ntwo\n", "tests/test_kept.py": "branch\n"},
                "sh": "rm tests/test_old.py", "commit": "Add feature",
                "final": "## Summary\nAdded feature.", "hand_in": [["done"]]}
        fix = {"write": {"fixed.txt": "fixed\n"}, "commit": "Fix feature",
               "final": "## Summary\nFixed feature.", "hand_in": [["done"]]}
        first = {"final": "Found one.", "hand_in": [
            ["finding", "feature.txt:1", "feature is unfixed", "it needs a fix",
             "--run", "test -f fixed.txt"], ["done"]]}
        second = {"final": "Found one.", "hand_in": [
            ["finding", "feature.txt:2", "feature is wrong", "the proof says so", "--run", PROOF],
            ["done"]]}
        cls.fakes = fakeadapter.install(home, claude=[work, fix], codex=[first, second])
        task = taskfile.write(home, rig.path, "Add feature", done_when=("test -f feature.txt",))
        cls.done = home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_ends_with_the_reviews_verdict(self):
        log = (self.run_dir / "log.txt").read_text()
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err + log)
        self.assertEqual([[row["code"] for row in run["hand_ins"]]
                          for run in self.fakes["codex"].runs()], [[0, 0], [0, 0]])
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"), log)
        # the second finding fails on the commit the first review judged too: outside the fix delta
        self.assertEqual([(row["verdict"], row["finding_count"])
                          for row in self.state["round_summaries"]], [("FAIL", 1), ("PASS", 0)])

    def test_the_proof_ran_on_base_without_the_removed_test_and_with_the_changed_one(self):
        for name, commit in (("base", self.rig.head()), ("since", None)):
            with self.subTest(name=name):
                lines = (self.run_dir / f"round-2/proof-1-{name}.log").read_text().splitlines()
                if commit:
                    self.assertEqual(lines[0], f"$ {PROOF} (on {commit})")
                self.assertIn("laid over", lines)
                self.assertEqual(lines[-1], "[exit 1]")

    def test_the_checkout_is_back_on_its_branch_the_removed_test_still_gone(self):
        wt = Path(self.state["worktree"])
        self.assertFalse((wt / "tests/test_old.py").exists())
        self.assertEqual((wt / "tests/test_kept.py").read_text(), "branch\n")
        for args, out in ((("status", "--porcelain"), ""),
                          (("symbolic-ref", "--short", "HEAD"), self.state["branch"])):
            done = self.home.run("git", "-C", str(wt), *args)
            self.assertEqual((done.code, done.out.strip()), (0, out), done.err)


if __name__ == "__main__":
    unittest.main()
