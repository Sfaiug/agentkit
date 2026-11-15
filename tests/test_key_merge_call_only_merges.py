"""ak's merge call only merges: a head branch GitHub fails to delete never makes it read as
failed.  gh 2.46 exits 1 after a merge that went through whenever `--delete-branch` hears
anything but HTTP 422, and a merge only found done afterwards gets no `## How to revert`.

Black-box: the program `AK_BIN` names runs a task to its squash merge through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py:
one whose every branch delete answers HTTP 500; one whose repository deletes a merged PR's
branch itself, so a delete after the merge answers HTTP 422, beside a branch whose name ends
in the head's; and one whose `gh pr merge` exits 0 having only queued the PR to merge.
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

BRANCH = "ak/add-retry-file"    # the branch ak names for the task "Add retry file"


def refused(gh, _rig):
    gh.fail_branch_deletes()


def gone(gh, rig):
    gh.delete_on_merge()
    rig.branch(f"archive/refs/heads/{BRANCH}")


def queued(gh, rig):
    gh.reply("pr merge", err=f"! Pull request {rig.slug}#1 is already queued to merge\n")


class MergeCallOnlyMerges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for github in (refused, gone, queued):
            home = Home()
            cls.addClassCleanup(home.close)
            rig = Rig(home)
            gh = GitHub(home)
            gh.grant(rig.slug, "WRITE")
            github(gh, rig)
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            task = taskfile.write(home, rig.path, "Add retry file")
            done = home.ak("run", str(task), timeout=300)
            run_dir = taskfile.only_run(home)
            state = json.loads((run_dir / "run.json").read_text())
            warned = [line for line in (run_dir / "log.txt").read_text().splitlines()
                      if "WARN" in line]
            cls.runs[github.__name__] = (rig, gh, done, state, warned)

    def test_the_run_merges_and_its_pr_says_how_to_revert(self):
        for name in ("refused", "gone"):
            with self.subTest(name):
                _rig, gh, done, state, _warned = self.runs[name]
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(state["branch"], BRANCH)
                self.assertTrue(state["merged"], state)
                pr = gh.pr(1)
                self.assertEqual((pr["state"], pr["merge"]["method"]), ("MERGED", "squash"))
                self.assertIn("## How to revert", pr["body"])

    def test_only_a_failed_delete_is_in_the_log(self):
        warned = self.runs["refused"][4]
        self.assertEqual(len(warned), 1, warned)
        self.assertIn("HTTP 500", warned[0])
        self.assertEqual(self.runs["gone"][4], [])

    def test_a_pr_only_queued_to_merge_keeps_its_branch(self):
        rig, gh, _done, _state, _warned = self.runs["queued"]
        self.assertEqual(gh.pr(1)["state"], "OPEN")
        self.assertIn(BRANCH, rig.branches())


if __name__ == "__main__":
    unittest.main()
