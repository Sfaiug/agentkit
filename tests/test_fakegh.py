"""The answer key's GitHub opens and merges pull requests on the rig's bare origin.

A delivery test judges what ak opened and merged by reading tests/fixtures/fakegh.py's state
and the origin, so both hold only if the fake answers each call as GitHub does and merges
what GitHub would.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


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



if __name__ == "__main__":
    unittest.main()
