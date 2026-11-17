"""A directory holding a Git repository that a proof leaves behind goes when the checkout restores.

A review's `--run` proof runs in the run's checkout at the commit being weighed, and afterwards ak
puts the checkout back on the run's branch at its commit, keeping untracked files that were there
before the proof and removing every path the proof created, nested Git repositories included.
Black-box through `AK_BIN`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PROOF = "test -f local-note.txt && git clone -q . proof-clone && false"
WORK = {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt"}
REVIEW = {"final": "One defect from before the task.", "hand_in": [
    ["finding", "existing.txt:1", "old defect", "it matters later", "--run", PROOF],
    ["done"]]}


class ARepositoryAProofLeavesGoesWithIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files={"existing.txt": "before\n"})
        cls.base = rig.head()
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex=REVIEW)
        task = taskfile.write(
            cls.home, rig.path, "Add retry file",
            done_when=("printf 'kept\\n' > local-note.txt && test -f retry.txt",))
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.wt = Path(cls.state["worktree"])

    def git(self, *args):
        done = self.home.run("git", "-C", str(self.wt), *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip()

    def test_the_round_reaches_its_verdict_without_a_restore_error(self):
        hand_ins = self.fakes["codex"].runs()[0]["hand_ins"]
        self.assertEqual([(row["argv"][0], row["code"]) for row in hand_ins],
                         [("finding", 0), ("done", 0)])
        log = (self.run_dir / "log.txt").read_text()
        self.assertNotIn("could not restore the checkout", log + self.done.out + self.done.err)
        self.assertNotIn("did not restore", log)
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([row["verdict"] for row in self.state["round_summaries"]], ["PASS"])
        self.assertIn(self.base, (self.run_dir / "round-1/proof-1-base.log").read_text())

    def test_the_checkout_is_back_on_its_branch_with_the_proof_s_repository_gone(self):
        head = self.git("rev-parse", self.state["branch"])
        self.assertNotEqual(head, self.base)
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), self.state["branch"])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse((self.wt / "proof-clone").exists())
        self.assertNotIn("probe_checkout", self.state)
        self.assertEqual(self.git("ls-files", "--others", "--exclude-standard"), "local-note.txt")
        self.assertEqual((self.wt / "local-note.txt").read_text(), "kept\n")


class ABeforePathInsideAProofsRepositoryStays(unittest.TestCase):
    def test_a_before_file_whose_directory_the_proof_inits_is_not_deleted(self):
        proof = "test -f notes/kept.txt && git init -q notes && git clone -q . proof-clone && false"
        review = {"final": "One defect.", "hand_in": [
            ["finding", "existing.txt:1", "old defect", "it matters later", "--run", proof],
            ["done"]]}
        with Home() as home:
            rig = Rig(home, "widgets", files={"existing.txt": "before\n"})
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude=WORK, codex=review)
            task = taskfile.write(
                home, rig.path, "Add retry file",
                done_when=("mkdir -p notes && printf 'kept\\n' > notes/kept.txt && test -f retry.txt",))
            done = home.ak("run", str(task), "--no-merge", timeout=300)
            state = json.loads((taskfile.only_run(home) / "run.json").read_text())
            wt = Path(state["worktree"])
            self.assertNotEqual(done.code, 0)
            self.assertEqual((wt / "notes/kept.txt").read_text(), "kept\n")
            self.assertFalse((wt / "proof-clone").exists())
            self.assertIn("probe_checkout", state)


if __name__ == "__main__":
    unittest.main()
