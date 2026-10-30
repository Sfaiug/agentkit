"""Without push rights on the origin, passed work goes to a fork and waits for the maintainer.

An account that may only read a repository cannot push a branch to it or merge into it, so a
run that passes forks the repository, pushes its branch to the fork, opens the PR upstream from
there and stops: merging is the maintainer's decision, and the run ends PASS, not merged, and
not a failure.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, where
the viewer `beta` has READ on `acme/widgets`, with scripted harnesses from fakeadapter.py.
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

BRANCH = "ak/add-retry-file"
NOTE = "waiting for the maintainer"


class ForkDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", owner="acme")
        cls.base = cls.rig.head()
        cls.gh = GitHub(cls.home, login="beta")
        cls.gh.grant(cls.rig.slug, "READ")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.fork = cls.home.root / "remotes/beta/widgets.git"

    def fork_head(self, ref):
        done = self.home.run("git", "-C", str(self.fork), "rev-parse", "-q", "--verify",
                             f"refs/heads/{ref}^{{commit}}")
        return done.out.strip() if done.code == 0 else None

    def test_the_run_exits_0_and_says_pass_not_merged_waiting_for_the_maintainer(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, not merged: {NOTE} -> "
                                      f"{self.run_dir / 'result.md'}"), last)
        log = (self.run_dir / "log.txt").read_text()
        self.assertIn("READ permission on acme/widgets; pushing to a fork", log)
        self.assertIn(f"PASS, not merged: {NOTE}", log)

    def test_the_reviewed_branch_is_pushed_to_the_viewer_s_fork_and_not_to_the_origin(self):
        self.assertTrue(self.fork.is_dir(), "no fork of acme/widgets was made")
        self.assertEqual(self.fork_head(BRANCH), self.state["review"]["head_sha"])
        self.assertEqual(self.rig.branches(), ["main"])

    def test_one_pr_is_opened_upstream_from_the_fork_and_left_open(self):
        prs = self.gh.prs()
        self.assertEqual(len(prs), 1, prs)
        pr = prs[0]
        self.assertEqual((pr["repo"], pr["url"], pr["baseRefName"], pr["head"], pr["title"]), (
            "acme/widgets", self.state["pr"], "main", f"beta/widgets:{BRANCH}",
            "Add retry file"))
        self.assertEqual((pr["state"], pr["merge"]), ("OPEN", None))
        self.assertEqual(pr["body"], (self.run_dir / "pr-body.md").read_text())

    def test_nothing_is_merged(self):
        # Merging is the maintainer's call: the run never asks GitHub to merge.
        self.assertFalse([call for call in self.home.calls("gh") if call[:2] == ["pr", "merge"]])
        self.assertEqual(self.rig.head(), self.base)

    def test_the_record_and_result_say_foreign_pass_not_merged(self):
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "merged", "merge_failed", "merge_note", "foreign")}, {
            "state": "pass", "verdict": "PASS", "merged": False, "merge_failed": False,
            "merge_note": NOTE, "foreign": True})
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[4], f"# PASS, not merged: {NOTE} — Add retry file")
        for line in ("VERDICT: PASS", f"pr: {self.state['pr']}", "merged: no",
                     f"merge: {NOTE}"):
            self.assertIn(line, lines)


if __name__ == "__main__":
    unittest.main()
