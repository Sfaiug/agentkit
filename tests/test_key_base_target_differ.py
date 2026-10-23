"""A task's `base:` is the branch its work starts from and `target:` the branch its PR merges into.

Work often builds on a branch that has not landed yet: `base: feature` cuts the run's branch
from `feature`, while `target: main` opens the PR into `main` and merges it there, with the
method `merge:` names, at the very commit that was reviewed and whose tree the final check
tested.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with
scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class BaseTargetDiffer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.main = cls.rig.head()
        cls.feature = cls.rig.branch("feature", {"feature.txt": "beta\n"})
        cls.gh = GitHub(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file", front={
            "base": "feature", "target": "main", "merge": "merge"})
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_passes_merged_and_records_its_base_and_target(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "merged", "base", "target")}, {
            "state": "pass", "verdict": "PASS", "merged": True, "base": "feature",
            "target": "main"})

    def test_the_work_starts_from_the_base_branch(self):
        delivered = self.state["delivery_sha"]
        self.assertEqual(self.rig.origin("rev-parse", f"{delivered}^"), self.feature)
        self.assertEqual(self.rig.head("feature"), self.feature)

    def test_the_pr_targets_main_and_is_merged_there_with_a_merge_commit(self):
        prs = self.gh.prs()
        self.assertEqual(len(prs), 1, prs)
        pr = prs[0]
        self.assertEqual((pr["url"], pr["baseRefName"], pr["head"]), (
            self.state["pr"], "main", f"{self.rig.slug}:ak/add-retry-file"))
        merge = pr["merge"]
        self.assertEqual(merge["method"], "merge")
        self.assertEqual(self.rig.head(), merge["commit"])
        parents = self.rig.origin("rev-parse", "main^1", "main^2").split()
        self.assertEqual(parents, [self.main, self.state["delivery_sha"]])
        self.assertEqual(sorted(self.rig.files()), [".keep", "feature.txt", "retry.txt"])
        self.assertEqual(self.rig.branches(), ["feature", "main"])

    def test_it_merges_the_reviewed_commit_whose_tree_the_final_check_tested(self):
        delivered = self.state["delivery_sha"]
        self.assertEqual(delivered, self.state["review"]["head_sha"])
        self.assertEqual(self.gh.pr(1)["merge"]["match"], delivered)
        check = self.state["final_check"]
        self.assertEqual(check["outcome"], "passed")
        self.assertEqual(check["tree_sha"], self.rig.origin("rev-parse", f"{delivered}^{{tree}}"))


if __name__ == "__main__":
    unittest.main()
