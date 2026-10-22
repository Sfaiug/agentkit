"""The answer key's GitHub opens and merges pull requests on the rig's bare origin, and a
passing run opens its PR, squash-merges the reviewed commit and cleans up.

What ak opened and merged is read off tests/fixtures/fakegh.py's state and the origin, so both
hold only if the fake answers each call as GitHub does and merges what GitHub would.  The run's
executor writes retry.txt and its reviewer passes it, through tests/fixtures/retry's adapters
with no model behind them.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from fixtures.akbin import AK, Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "retry"


class PullRequests(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig, self.gh = Rig(self.home, "widgets"), GitHub(self.home)
        self.sha = self.rig.branch("fix-api", {"api.py": "x = 2\n"})

    def call(self, *args, code=0, cwd=None):
        done = self.home.run("gh", *args, cwd=cwd or self.rig.path)
        self.assertEqual(done.code, code, done.err)
        return done.out if code == 0 else done.err

    def test_a_squash_merge_lands_one_commit_at_the_matched_head_and_deletes_the_branch(self):
        url = self.gh.open_pr(self.rig, "fix-api", title="Fix api", author="beta")
        rest = json.loads(self.call("api", "repos/acme/widgets/pulls/1"))
        self.assertEqual((rest["state"], rest["base"]["ref"], rest["head"]["sha"]),
                         ("open", "main", self.sha))
        self.assertEqual(json.loads(self.call("repo", "view", "--json", "viewerPermission")),
                         {"viewerPermission": "ADMIN"})
        self.assertIn("Head branch was modified",
                      self.call("pr", "merge", url, "--squash", "--match-head-commit", "0" * 40,
                                code=1))
        self.call("pr", "merge", url, "--squash", "--delete-branch", "--match-head-commit",
                  self.sha)
        merge = self.gh.pr(1)["merge"]
        self.assertEqual((merge["method"], merge["head"], merge["deleted"]),
                         ("squash", self.sha, True))
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.origin("log", "-1", "--format=%s|%an|%P", "main"),
                         f"Fix api (#1)|beta|{self.rig.head('main^')}")
        self.assertEqual(json.loads(self.call("pr", "view", "1", "--json", "state,mergeCommit")),
                         {"state": "MERGED", "mergeCommit": {"oid": self.rig.head()}})
        self.assertIn("is merged", self.call("pr", "merge", url, "--merge", code=1))


class PassingRun(unittest.TestCase):
    def test_the_reviewed_commit_is_squash_merged_and_its_branch_and_worktree_go(self):
        home = Home()
        self.addCleanup(home.close)
        rig, gh = Rig(home, "widgets"), GitHub(home)
        akconfig.write(home, ["opus", "astra"])
        task = taskfile.write(home, rig.path, front={"rounds": 1})
        done = home.ak("run", str(task), "--exec", "opus", "--review", "astra",
                       env={"AGENTKIT_ADAPTER_DIR": str(ADAPTERS), "AK_BIN": AK}, timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)

        [pr] = gh.prs()
        run = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((pr["state"], pr["baseRefName"], pr["headRefName"]),
                         ("MERGED", "main", run["branch"]))
        merge = pr["merge"]
        self.assertEqual((merge["method"], merge["match"], merge["head"], merge["deleted"]),
                         ("squash", run["review"]["head_sha"], merge["match"], True))
        self.assertEqual(rig.origin("rev-parse", f"{merge['head']}^{{tree}}"),
                         rig.origin("rev-parse", "main^{tree}"))
        self.assertEqual((rig.head(), rig.origin("show", "main:retry.txt")),
                         (merge["commit"], "hello"))
        self.assertEqual(rig.branches(), ["main"])
        self.assertFalse(Path(run["worktree"]).exists())
        self.assertNotIn(run["branch"], rig.branches(remote=False))


if __name__ == "__main__":
    unittest.main()
