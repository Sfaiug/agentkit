"""A change cannot weaken the target's landing suite by rewriting its own tests: line.

Offline: local Git and real checks, isolated state and fake workers and wakes.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import LanderFixture, ONCE, SUITE
from test_repo_suite import RepoSuiteFixture
from agentkit import config, land, run


class FinalCheckFromTarget(RepoSuiteFixture, unittest.TestCase):
    def test_branch_declaring_true_fails_the_targets_landing_check(self):
        self.add_origin()
        self.commit("---\ntests: false\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "main")
        self.git("checkout", "-q", "-b", "fix-api")
        self.commit("---\ntests: true\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "fix-api")
        with patch.object(run, "start_followups", return_value=None):
            state = self.launch("target-suite", ["test -d ."],
                                front="base: fix-api\ntarget: main\n", expected="waiting")
        self.assertEqual(self.finals(), [["test -d ."], ["false"]], self.gates)
        self.assertEqual(state["final_check"]["outcome"], "failed")
        self.assertEqual(state["final_check"]["where"], "landing")

    def test_final_check_and_evidence_use_the_integrated_target_tip(self):
        suite = "test -f AGENTS.md"
        self.add_origin()
        self.commit(f"---\ntests: {suite}\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "main")
        self.git("checkout", "-q", "-b", "fix-api")
        (self.repo / "work.txt").write_text("work\n")
        self.git("add", "work.txt")
        self.git("commit", "-q", "-m", "work")

        def integrated_check(lp):
            self.assertTrue(run.integrate(lp, "origin/main"))
            self.git("checkout", "-q", "main")
            self.commit("---\ntests: test -f later.txt\n---\n# acme\n")
            self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
            self.assertTrue(run.final_check(lp, "origin/main"))
            self.assertEqual(lp.state["final_check"]["suite"], suite)
            self.assertEqual(run.merge_body(lp, lp.state["final_check"]["sha"]),
                             ["--body", f"Suite-Passed-Tree: {lp.state['final_check']['tree_sha']}"])

        with patch.object(run, "merge", side_effect=integrated_check), \
                patch.object(run, "fix_final_check", return_value=False), \
                patch.object(run, "start_followups", return_value=None):
            self.launch("pinned-final", ["test -d ."], from_branch="fix-api")
        self.assertEqual(self.finals(), [["test -d ."], [suite]], self.gates)

    def test_review_pr_uses_the_target_tip_fetched_before_checkout(self):
        suite = "test -f AGENTS.md"
        self.commit(f"---\ntests: {suite}\n---\n# acme\n")
        target = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", target)
        self.commit("---\ntests: true\n---\n# acme\n")
        head = self.git("rev-parse", "HEAD")
        directory = config.RUNS / "pinned-pr"
        directory.mkdir()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Mend the fence", "author": "fixture", "body": "Fixture PR"}
        checkout = run.make_worktree

        def another_runs_fetch(*args, **kwargs):
            result = checkout(*args, **kwargs)
            self.commit("---\ntests: test -f later.txt\n---\n# acme\n")
            self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
            return result

        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "make_worktree", side_effect=another_runs_fetch), \
                patch.object(run, "post_review", return_value=True), \
                patch.object(run, "checks", return_value=(False, "fixture: no merge")), \
                patch.object(run, "gh_json", return_value=(info, "")):
            state = run.review_pr(self.cfg, directory, "https://github.com/acme/acme/pull/1",
                                  {**self.opts, "--no-merge": True}, self.logs.append)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual(self.rounds(), [[suite]])


class StackedSuiteFromTarget(LanderFixture, unittest.TestCase):
    def test_branch_declaring_true_cannot_skip_the_stack_check(self):
        directory = self.member(once="true", **{
            "AGENTS.md": "---\ntests: true\n---\n",
            "broken.txt": "branch breakage\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        self.assertIn(SUITE, self.wait(directory)["fix"]["line"])
        self.assertEqual(self.checks[0][0], ["true", SUITE])
        self.assert_cleaned()

    def test_stacks_and_rebuilds_use_the_pinned_targets_line(self):
        first = self.member("api", **{"api.txt": "api\n"})
        red = self.member("client", joined=2, **{"broken.txt": "branch breakage\n"})
        self.member("later", joined=3, **{"later.txt": "later\n"})
        self.advance()
        stack = land._stack_member
        moved = []

        def another_runs_fetch(*args, **kwargs):
            result = stack(*args, **kwargs)
            if not moved:
                (self.repo / "AGENTS.md").write_text("---\ntests: test -f later.txt\n---\n# acme\n")
                self.commit("later line")
                run.git(self.repo, "push", "origin", "main")
                run.fetch(self.repo, "origin")
                moved.append(True)
            return result

        with patch.object(land, "_stack_member", side_effect=another_runs_fetch):
            land.check_line(self.turn)
        self.assertTrue(all(cmds == [ONCE, SUITE] for cmds, _, _ in self.checks), self.checks)
        self.assertIn("land", self.wait(first))
        self.assertIn("fix", self.wait(red))
        self.assertTrue(any("later.txt" in run.git(self.repo, "ls-tree", "--name-only", tree)
                            and "broken.txt" not in run.git(self.repo, "ls-tree", "--name-only", tree)
                            for tree in land._trees(self.turn)[1]))
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main()
