"""The answer key's GitHub opens, checks and merges pull requests on the rig's bare origin.

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
from fixtures.fakegh import LOGGED_OUT, GitHub
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

    def test_a_pr_is_opened_once_from_a_pushed_branch_and_viewed_by_url_or_branch(self):
        body = self.home.write("body.md", "Fixes the api.\n")
        url = self.call("pr", "create", "--base", "main", "--head", "fix-api", "--title",
                        "Fix api", "--body-file", str(body)).strip()
        self.assertEqual(url, "https://github.com/acme/widgets/pull/1")
        self.assertEqual(self.rig.origin("rev-parse", "refs/pull/1/head"), self.sha)
        self.assertIn(url, self.call("pr", "create", "--head", "fix-api", "--title", "again",
                                     "--body", "", code=1))
        self.assertEqual(json.loads(self.call("pr", "list", "--json", "number,headRefName")),
                         [{"number": 1, "headRefName": "fix-api"}])
        view = json.loads(self.call("pr", "view", "fix-api", "--json",
                                    "number,body,headRefOid,mergeStateStatus,state"))
        self.assertEqual(view, {"number": 1, "body": "Fixes the api.\n", "headRefOid": self.sha,
                                "mergeStateStatus": "CLEAN", "state": "OPEN"})
        self.assertEqual(self.call("pr", "view", url, "--json", "url", "-q", ".url"), url + "\n")
        self.assertEqual(json.loads(self.call("api", "repos/acme/widgets/pulls/1"))["head"],
                         {"ref": "fix-api", "sha": self.sha, "repo": {
                             "full_name": "acme/widgets", "clone_url": str(self.rig.bare)}})

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

    def test_a_required_check_holds_the_merge_until_it_passes(self):
        url = self.gh.open_pr(self.rig, "fix-api")
        self.gh.require("acme/widgets", "main", "build")
        self.gh.check(self.sha, "build", conclusion="failure")
        rules = json.loads(self.call("api", "--paginate", "repos/acme/widgets/rules/branches/main"))
        self.assertEqual(rules[0]["parameters"]["required_status_checks"], [{"context": "build"}])
        self.assertIn('"build"', self.call("pr", "merge", url, "--merge", code=1))
        self.gh.check(self.sha, "build")
        runs = json.loads(self.call("api", f"repos/acme/widgets/commits/{self.sha}/check-runs"))
        self.assertEqual([run["conclusion"] for run in runs["check_runs"]], ["failure", "success"])
        self.call("pr", "merge", url, "--merge")
        self.assertEqual(self.rig.origin("rev-parse", "main^2"), self.sha)
        self.assertEqual(self.rig.branches(), ["fix-api", "main"])

    def test_reviews_and_comments_keep_their_text_and_search_finds_the_viewer_s_prs(self):
        url = self.gh.open_pr(self.rig, "fix-api", author="beta")
        review = self.home.write("review.md", "Looks right.\n")
        self.call("api", "repos/acme/widgets/pulls/1/reviews", "--method", "POST", "-f",
                  f"commit_id={self.sha}", "-f", "event=COMMENT", "-F", f"body=@{review}")
        self.call("pr", "comment", url, "--body", "thanks")
        pr = self.gh.pr(1)
        self.assertEqual([(r["author"]["login"], r["state"], r["body"], r["commit"]["oid"])
                          for r in pr["reviews"]], [("acme", "COMMENTED", "Looks right.\n",
                                                     self.sha)])
        self.assertEqual([c["body"] for c in pr["comments"]], ["thanks"])
        self.assertEqual(self.call("api", "user", "-q", ".login"), "acme\n")
        found = json.loads(self.call("api", "search/issues?q=is:pr+is:open+author:@me"))
        self.assertEqual(found["items"], [])
        self.gh.edit(1, author={"login": "acme"})
        found = json.loads(self.call("api", "search/issues?q=is:pr+is:open+author:@me"))
        self.assertEqual([item["pull_request"]["html_url"] for item in found["items"]], [url])

    def test_without_push_rights_a_fork_carries_the_branch_and_keeps_it_after_a_merge(self):
        upstream = Rig(self.home, "gadgets", owner="beta")
        upstream.branch("fix-api", {"api.py": "x = 3\n"}, push=False)
        repo = json.loads(self.call("repo", "view", "--json", "nameWithOwner,viewerPermission",
                                    cwd=upstream.path))
        self.assertEqual(repo, {"nameWithOwner": "beta/gadgets", "viewerPermission": "READ"})
        self.call("repo", "fork", "--remote", "--remote-name", "fork", cwd=upstream.path)
        self.home.run("git", "-C", str(upstream.path), "push", "-q", "fork", "fix-api")
        url = self.call("pr", "create", "--repo", "beta/gadgets", "--head", "acme:fix-api",
                        "--title", "Fix api", "--body", "", cwd=upstream.path).strip()
        self.assertEqual(self.gh.pr(1, "beta/gadgets")["head"], "acme/gadgets:fix-api")
        self.call("pr", "merge", url, "--rebase", "--delete-branch")
        self.assertIn("api.py", upstream.files())
        fork = self.home.root / "remotes/acme/gadgets.git"
        self.assertTrue(self.home.run("git", "-C", str(fork), "rev-parse", "fix-api").out)

    def test_a_scripted_reply_comes_first_and_every_call_is_logged(self):
        self.gh.reply("", err=LOGGED_OUT, code=4, times=1)
        self.assertEqual(self.call("api", "user", code=4), LOGGED_OUT)
        self.assertEqual(json.loads(self.call("api", "user")), {"login": "acme"})
        self.assertIn("unexpected", self.call("release", "list", code=1))
        self.assertEqual(self.home.calls("gh"), [["api", "user"], ["api", "user"],
                                                 ["release", "list"]])


if __name__ == "__main__":
    unittest.main()
