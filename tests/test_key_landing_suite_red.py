"""A repository suite red at landing gets one fixer turn and a fresh review, then the merge.

The `tests:` suite in a repository's AGENTS.md runs only at landing, on the commit about to be
merged, after the work already passed review.  When it fails there, the run does not end FAIL
and does not merge red work: the executor is handed the suite's failing output in a fixer
turn that spends no task round, a fresh review judges the fixed work, and the suite runs again
on the fixed commit before the run joins the landing line and merges it.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses
from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# The output is upper case so that it cannot be read off the command, which every prompt names.
SUITE = "test ! -f bad.txt || { echo bad.txt is still here | tr a-z A-Z; false; }"
SAID = "BAD.TXT IS STILL HERE"
WORK = {"write": {"retry.txt": "hello\n", "bad.txt": "stale\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
FIX = {"sh": "git rm -q bad.txt", "commit": "remove bad.txt",
       "final": "## Summary\nremoved bad.txt", "hand_in": [["done"]]}


def seen(directory, n):
    """A review that passes, keeping the commit and the files it was shown."""
    keep = shlex.quote(str(directory / f"review-{n}"))
    return {"sh": f"git rev-parse HEAD >{keep}.sha; ls >{keep}.ls", "final": "Handed in.",
            "hand_in": [["done"]]}


class LandingSuiteRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets",
                      files={"AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n"})
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.kept = cls.home.root / "adapters"
        cls.fakes = fakeadapter.install(cls.home, claude=[WORK, FIX],
                                        codex=[seen(cls.kept, 1), seen(cls.kept, 2)])
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def review(self, n):
        """The commit review `n` was shown and the files at its top."""
        return ((self.kept / f"review-{n}.sha").read_text().strip(),
                (self.kept / f"review-{n}.ls").read_text().split())

    def test_the_run_ends_pass_merged_and_the_fix_spends_no_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, merged -> {self.run_dir / 'result.md'}"), last)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "merged")},
                         {"state": "pass", "verdict": "PASS", "merged": True})
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        self.assertIn("rounds: 1 of 3", (self.run_dir / "result.md").read_text().splitlines())

    def test_one_fixer_turn_is_handed_the_suite_output_of_the_commit_it_failed_on(self):
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer"])
        fixer = self.run_dir / "round-1/final-fixer"
        self.assertTrue(fixer.is_dir(), sorted(p.name for p in fixer.parent.iterdir()))
        prompt = (fixer / "prompt.md").read_text()
        reviewed, _files = self.review(1)
        self.assertIn(SAID, prompt)
        self.assertIn(reviewed, prompt)
        self.assertNotIn(SAID, (self.run_dir / "round-1/executor/prompt.md").read_text())

    def test_a_fresh_review_judges_the_fixed_work(self):
        self.assertEqual(self.fakes["codex"].n, 2)
        first, before = self.review(1)
        second, after = self.review(2)
        self.assertIn("bad.txt", before)
        self.assertNotIn("bad.txt", after)
        self.assertIn("retry.txt", after)
        self.assertNotEqual(first, second)
        self.assertEqual(self.state["review"]["head_sha"], second)

    def test_the_line_has_passed_evidence_for_the_fixed_tree_and_none_for_the_red_tree(self):
        first, _files = self.review(1)
        fixed, _files = self.review(2)
        path, = self.run_dir.parent.glob(".merge-*.green")
        trees = json.loads(path.read_text())["trees"]
        self.assertNotIn(self.rig.git("rev-parse", f"{first}^{{tree}}"), trees)
        tree = self.rig.git("rev-parse", f"{fixed}^{{tree}}")
        self.assertEqual(trees[tree]["tested"], tree)

    def test_the_suite_reruns_green_on_the_fixed_commit_and_that_commit_is_merged(self):
        reviewed, _files = self.review(2)
        delivered = self.state["delivery_sha"]
        self.assertEqual(delivered, reviewed)
        self.assertEqual({key: self.state["final_check"].get(key) for key in (
            "outcome", "where", "sha", "suite")}, {
            "outcome": "passed", "where": "landing", "sha": delivered, "suite": SUITE})
        self.assertIn(f"final check: passed at landing on {delivered}",
                      (self.run_dir / "result.md").read_text().splitlines())
        self.assertNotIn("bad.txt", self.rig.files(delivered))
        self.assertEqual(self.gh.pr(1)["merge"]["head"], delivered)
        self.assertEqual(self.rig.origin("rev-parse", "main^{tree}"),
                         self.rig.origin("rev-parse", f"{delivered}^{{tree}}"))
        self.assertEqual(sorted(self.rig.files()), [".keep", "AGENTS.md", "retry.txt"])


if __name__ == "__main__":
    unittest.main()
