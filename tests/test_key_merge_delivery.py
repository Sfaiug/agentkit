"""A task whose work passes review is delivered: its PR is opened, squash-merged and cleaned up.

Merging is the job: without --no-merge, a run that passes pushes its branch, opens a PR into
the target with the run's own title and description, reads which checks the target requires
before it merges, merges with --squash at the very commit that was tested and reviewed, and
then removes its worktree, with run.json and result.md saying it merged.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, against the bare
origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
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


class MergeDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.base = cls.rig.head()
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # enough to push and merge without a fork
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_ends_pass_merged_and_says_where_its_result_is(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, merged -> {self.run_dir / 'result.md'}"), last)
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# PASS, merged — Add retry file")
        for line in ("VERDICT: PASS", f"pr: {self.state['pr']}", "merged: yes"):
            self.assertIn(line, lines)

    def test_one_pr_is_opened_from_the_run_branch_with_its_title_and_description(self):
        prs = self.gh.prs()
        self.assertEqual(len(prs), 1, prs)
        pr = prs[0]
        self.assertEqual((pr["url"], pr["baseRefName"], pr["head"], pr["title"]), (
            self.state["pr"], "main", f"{self.rig.slug}:ak/add-retry-file", "Add retry file"))
        body = (self.run_dir / "pr-body.md").read_text()
        self.assertEqual(pr["body"], body)
        for line in ("- verdict: PASS", "- rounds: 1 of 3", "- executor: opus, reviewer: astra",
                     f"- run: {self.run_dir.name}"):
            self.assertIn(line, body.splitlines())

    def test_it_squash_merges_the_reviewed_commit_and_deletes_the_branch(self):
        reviewed = self.state["review"]["head_sha"]
        self.assertEqual(self.state["delivery_sha"], reviewed)
        merge = self.gh.pr(1)["merge"]
        self.assertEqual({key: merge[key] for key in ("method", "head", "match", "deleted")},
                         {"method": "squash", "head": reviewed, "match": reviewed,
                          "deleted": True})
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), merge["commit"])
        self.assertEqual(self.rig.origin("rev-parse", "main^"), self.base)
        self.assertEqual(self.rig.origin("rev-parse", "main^{tree}"),
                         self.rig.origin("rev-parse", f"{reviewed}^{{tree}}"))
        self.assertIn("retry.txt", self.rig.files())

    def test_the_target_s_required_checks_are_read_before_the_merge(self):
        calls = [" ".join(call) for call in self.home.calls("gh")]
        merged = next(i for i, call in enumerate(calls) if call.startswith("pr merge"))
        opened = next(i for i, call in enumerate(calls) if call.startswith("pr create"))
        rules = [i for i, call in enumerate(calls)
                 if call.startswith("api") and "/rules/branches/main" in call]
        classic = [i for i, call in enumerate(calls)
                   if call.startswith("api graphql") and "branchProtectionRule" in call]
        self.assertTrue(rules and classic, calls)
        self.assertLess(opened, min(rules + classic))
        self.assertLess(max(rules + classic), merged)

    def test_the_record_says_merged_and_the_worktree_is_gone(self):
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "merged", "no_merge")}, {
            "state": "pass", "verdict": "PASS", "merged": True, "no_merge": False})
        self.assertEqual({key: self.state["final_check"].get(key) for key in (
            "outcome", "where", "sha")}, {
            "outcome": "passed", "where": "landing", "sha": self.state["delivery_sha"]})
        self.assertFalse((self.home.path / ".agentkit/wt" / self.run_dir.name).exists())
        self.assertFalse(Path(self.state["worktree"]).exists())


if __name__ == "__main__":
    unittest.main()
