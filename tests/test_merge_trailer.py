"""A landed commit names only the tree whose declared suite actually passed.

Offline: real git commits and merges in an acme sandbox; GitHub and models are fakes.
"""

from contextlib import ExitStack, nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

URL = "https://github.com/acme/widget/pull/7"
SUITE = "test -f work.txt"


class MergeTrailer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-merge-trailer-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Merge test")
        self.git("config", "user.email", "merge@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("checkout", "-q", "-b", "ak/fix-api")
        self.directory = config.RUNS / "merge-test"
        self.directory.mkdir()
        self.calls = []
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run, "merge_turn", side_effect=lambda *a, **_kw: nullcontext()))
        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=self.check))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)

    def check(self, cmds, cwd, log_path, *args, **_kw):
        # Run the declared commands without host admission or touching the worker's processes.
        results = [subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True)
                   for cmd in cmds]
        ok = all(result.returncode == 0 for result in results)
        text = "$ " + "\n$ ".join(cmds) + f"\n[exit {0 if ok else 1}]\n"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(text)
        return ok, text

    def gh(self, cwd, *args, **_kw):
        self.assertEqual(args[:2], ("pr", "merge"))
        self.calls.append(args)
        head = args[args.index("--match-head-commit") + 1]
        self.assertEqual(head, self.git("rev-parse", "ak/fix-api"))
        body = args[args.index("--body") + 1] if "--body" in args else ""
        if "--body-file" in args:
            body = Path(args[args.index("--body-file") + 1]).read_text()
        self.git("checkout", "-q", "main")
        if "--rebase" in args:
            # GitHub replays the commits; merge-body options cannot change their messages.
            self.git("cherry-pick", head)
        elif "--merge" in args:
            self.git("merge", "--no-ff", head, "-m", "Merge fix-api\n\n" + body)
        else:
            self.git("merge", "--squash", head)
            self.git("commit", "-q", "-m", "Fix API\n\n" + body)
        return 0, "merged"

    def loop(self, suite=SUITE, method="squash", once=None):
        self.git("update-ref", "refs/heads/main", self.base)
        self.git("reset", "--hard", self.base)
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n" if suite else "# acme\n")
        (self.repo / "work.txt").write_text("work\n")
        self.commit("Fix API\n\nKeep this explanation.")
        head, tree = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}")
        state = {"run_id": self.directory.name, "title": "Fix API", "state": "running",
                 "verdict": "PASS", "executor": "opus", "reviewer": "astra",
                 "review": {"executor": "opus", "executor_provider": "anthropic",
                            "reviewer": "astra", "reviewer_provider": "openai",
                            "returncode": 0, "verdict": "PASS", "done_when": True,
                            "head_sha": head, "tree_sha": tree},
                 "round_summaries": [], "rounds": 1, "base": "origin/main", "target": "main",
                 "base_sha": self.base, "branch": "ak/fix-api", "worktree": str(self.repo),
                 "repo": str(self.repo), "merge_method": method, "delivery_sha": head,
                 "merged": False, "findings": ""}
        run.save_state(self.directory, state)
        cmds = ["true"] + ([f"{once or suite}  # once"] if once or suite else [])
        return run.Loop(self.cfg, self.directory, state, {}, lambda line: None,
                        self.repo, "", cmds, "", [])

    def land(self, lp):
        if lp.state["merge_method"] == "rebase":
            # Exercise push's message preparation, with only the network write faked.
            original = run.git_out

            def git_out(cwd, *args, **_kw):
                return (0, "") if args[0] == "push" else original(cwd, *args, **_kw)

            with patch.object(run, "git_out", side_effect=git_out):
                self.assertTrue(run.push(lp))
        self.assertTrue(run.do_merge(lp, URL, "origin/main"))
        return self.git("log", "-1", "--format=%B")

    def test_squash_after_passing_final_check_names_checked_tree(self):
        lp = self.loop()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assertTrue(run.final_check(lp, "origin/main"))
        message = self.land(lp)
        self.assertIn(f"\nSuite-Passed-Tree: {tree}", message)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)

    def test_merge_and_rebase_name_checked_tree(self):
        for method in ("merge", "rebase"):
            with self.subTest(method=method):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(method=method)
                tree = self.git("rev-parse", "HEAD^{tree}")
                self.assertTrue(run.final_check(lp, "origin/main"))
                message = self.land(lp)
                self.assertIn(f"\nSuite-Passed-Tree: {tree}", message)
                self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
                if method == "rebase":
                    self.assertIn("Keep this explanation.", message)

    def test_without_declared_suite_has_no_trailer_even_with_once_check(self):
        for once in (None, "true"):
            with self.subTest(once=once):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(suite=None, once=once)
                self.assertTrue(run.final_check(lp, "origin/main"))
                self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_failed_or_unrun_suite_has_no_trailer(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(suite="false" if failed else SUITE)
                if failed:
                    self.assertFalse(run.verify_once(lp)[0])
                self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_suite_pass_on_another_commit_has_no_trailer(self):
        lp = self.loop()
        self.assertTrue(run.final_check(lp, "origin/main"))
        (self.repo / "work.txt").write_text("changed\n")
        self.commit("Change after check")
        lp.state["review"].update(run.commit_identity(self.repo))
        lp.state["delivery_sha"] = self.git("rev-parse", "HEAD")
        self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_own_pr_pass_names_the_suite_tree(self):
        lp = self.loop()
        head, tree = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}")
        lp.state.update(head_sha=head, own_pr=True, own_orchestrator="opus")
        lp.save()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Fix API", "author": "acme", "body": "Fix the API"}

        def review(loop, summary, ok, dw_log, **_kw):
            self.assertTrue(ok)
            loop.state["review"] = lp.state["review"]
            loop.state["verdict"] = "PASS"
            return "PASS"

        with ExitStack() as mocks:
            for name, value in (("pr_view", info), ("launch_session", "fix-api"),
                                ("own_pr_orchestrator", (True, "opus")),
                                ("checkout_for", self.repo), ("disk_pressure", False),
                                ("fetch", (0, "")), ("make_worktree", (self.repo, "ak/fix-api")),
                                ("collect_usage", {}), ("post_review", True),
                                ("checks", (True, "")), ("gh_json", (info, "")),
                                ("join_session_project", None), ("project_lessons", "")):
                mocks.enter_context(patch.object(run, name, return_value=value))
            mocks.enter_context(patch.object(run, "review", side_effect=review))
            mocks.enter_context(patch.object(run, "restore_review_checkout"))
            state = run.review_pr(self.cfg, self.directory, URL,
                                  {"--review": "astra"}, lambda line: None)
        self.assertTrue(state["merged"])
        self.assertIn(f"\nSuite-Passed-Tree: {tree}", self.git("log", "-1", "--format=%B"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
