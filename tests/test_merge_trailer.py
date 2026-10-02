"""A landed commit names only the tree whose declared suite actually passed.

Offline: real git commits and merges in an acme sandbox; GitHub and models are fakes.
"""

from contextlib import ExitStack, nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, gc, run

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
        if args[0] == "api" and "graphql" in args:
            query = next(arg for arg in args if arg.startswith("query="))
            self.assertIn("viewerMergeBodyText(mergeType:$method)", query)
            for field in ("owner=acme", "name=widget", "number=7"):
                self.assertIn(field, args)
            method = next(arg.removeprefix("method=").lower()
                          for arg in args if arg.startswith("method="))
            self.assertIn(method, ("squash", "merge"))
            self.assertIn(".data.repository.pullRequest.viewerMergeBodyText | tojson", args)
            return 0, json.dumps(self.default_body(method))
        self.assertEqual(args[:2], ("pr", "merge"))
        self.calls.append(args)
        head = args[args.index("--match-head-commit") + 1]
        self.assertEqual(head, self.git("rev-parse", "ak/fix-api"))
        method = "merge" if "--merge" in args else "squash"
        body = (args[args.index("--body") + 1] if "--body" in args
                else self.default_body(method))
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

    def default_body(self, method):
        if method == "merge":
            return "Fix API\n\nThe PR's explanation.\n\nCo-authored-by: Acme <acme@localhost>"
        return self.git("log", f"{self.base}..ak/fix-api", "--format=%B")

    def loop(self, suite=SUITE, method="squash", once=None):
        self.git("update-ref", "refs/heads/main", self.base)
        self.git("reset", "--hard", self.base)
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n" if suite else "# acme\n")
        (self.repo / "work.txt").write_text("work\n")
        self.commit("Fix API\n\nKeep this explanation.\n\nCo-authored-by: Acme <acme@localhost>")
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

    def land(self, lp, url=URL, own=False):
        if lp.state["merge_method"] == "rebase":
            # Exercise push's message preparation, with only the network write faked.
            original = run.git_out

            def git_out(cwd, *args, **_kw):
                return (0, "") if args[0] == "push" else original(cwd, *args, **_kw)

            with patch.object(run, "git_out", side_effect=git_out):
                self.assertTrue(run.push(lp))
        if own:
            lp.state["own_orchestrator"] = "opus"
            self.assertTrue(run.merge_own_pr(lp, url, lp.state["delivery_sha"]))
        else:
            self.assertTrue(run.do_merge(lp, url, "origin/main"))
        return self.git("log", "-1", "--format=%B")

    def test_squash_after_passing_final_check_names_checked_tree(self):
        lp = self.loop()
        (self.repo / "work.txt").write_text("more work\n")
        self.commit("Follow up\n\nKeep the second explanation.")
        lp.state["review"].update(run.commit_identity(self.repo))
        lp.state["delivery_sha"] = self.git("rev-parse", "HEAD")
        default = self.default_body("squash")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assertTrue(run.final_check(lp, "origin/main"))
        message = self.land(lp)
        self.assertIn(f"\nSuite-Passed-Tree: {tree}", message)
        self.assertIn(default + "\nSuite-Passed-Tree:", message)
        self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Co-authored-by)"),
                         "Co-authored-by: Acme <acme@localhost>")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)

    def test_merge_and_rebase_name_checked_tree(self):
        for method in ("merge", "rebase"):
            with self.subTest(method=method):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(method=method)
                default = self.default_body(method)
                tree = self.git("rev-parse", "HEAD^{tree}")
                self.assertTrue(run.final_check(lp, "origin/main"))
                message = self.land(lp)
                self.assertIn(f"\nSuite-Passed-Tree: {tree}", message)
                self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
                if method == "rebase":
                    self.assertIn("Keep this explanation.", message)
                else:
                    self.assertIn(default + "\nSuite-Passed-Tree:", message)
                self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Co-authored-by)"),
                                 "Co-authored-by: Acme <acme@localhost>")

    def test_enterprise_merges_read_the_default_body_on_the_pr_host(self):
        url = URL.replace("github.com", "ghe.acme.test")
        for method, own in (("squash", False), ("merge", False), ("squash", True)):
            with self.subTest(method=method, own=own):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(method=method)
                self.assertTrue(run.final_check(lp, "origin/main"))
                reads = []

                def gh(cwd, *args, **_kw):
                    if args[0] == "api":
                        reads.append(args)
                        self.assertEqual(args[:4], ("api", "--hostname", "ghe.acme.test", "graphql"))
                    return self.gh(cwd, *args, **_kw)

                with patch.object(run, "gh", side_effect=gh):
                    message = self.land(lp, url, own=own)
                self.assertEqual(len(reads), 1)
                self.assertEqual(self.calls[-1][2], url)
                self.assertIn("Suite-Passed-Tree:", message)
                self.assertIn(self.default_body(method), message)

    def test_unavailable_default_body_merges_with_the_default_message(self):
        for method, own in (("squash", False), ("merge", False), ("squash", True)):
            for answer in ((1, "HTTP 502"), (0, "not JSON"), (None, "timed out")):
                with self.subTest(method=method, own=own, answer=answer):
                    self.git("checkout", "-q", "ak/fix-api")
                    lp = self.loop(method=method)
                    self.assertTrue(run.final_check(lp, "origin/main"))
                    reads = []

                    def gh(cwd, *args, **_kw):
                        if args[0] == "api" and "graphql" in args:
                            reads.append(args)
                            return answer
                        return self.gh(cwd, *args, **_kw)

                    with patch.object(run, "gh", side_effect=gh):
                        message = self.land(lp, own=own)
                    self.assertEqual(len(reads), 1)
                    self.assertTrue(lp.state["merged"])
                    self.assertFalse(lp.state.get("merge_failed"))
                    self.assertNotIn("--body", self.calls[-1])
                    self.assertNotIn("Suite-Passed-Tree:", message)
                    self.assertIn(self.default_body(method), message)

    def test_without_declared_suite_has_no_trailer_even_with_once_check(self):
        for method, once in (("squash", None), ("squash", "true"), ("rebase", "true")):
            with self.subTest(method=method, once=once):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(suite=None, method=method, once=once)
                self.assertTrue(run.final_check(lp, "origin/main"))
                self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_failed_or_unrun_suite_has_no_trailer(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                self.git("checkout", "-q", "ak/fix-api")
                lp = self.loop(suite="false" if failed else SUITE)
                if failed:
                    with patch.object(run, "target_fails", return_value="red target"), \
                            patch.object(run, "park_waiting", return_value=False):
                        self.assertFalse(run.final_check(lp, "origin/main"))
                self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_suite_pass_on_another_commit_has_no_trailer(self):
        lp = self.loop()
        self.assertTrue(run.final_check(lp, "origin/main"))
        (self.repo / "work.txt").write_text("changed\n")
        self.commit("Change after check")
        lp.state["review"].update(run.commit_identity(self.repo))
        lp.state["delivery_sha"] = self.git("rev-parse", "HEAD")
        self.assertNotIn("Suite-Passed-Tree:", self.land(lp))

    def test_landing_checks_a_new_tree_before_certifying_it(self):
        lp = self.loop()
        lp.rnd = 1
        self.assertTrue(run.final_check(lp, "origin/main"))
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("checkout", "-q", "main")
        (self.repo / "other.txt").write_text("other work\n")
        self.commit("Advance target")
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        self.git("checkout", "-q", "ak/fix-api")
        with patch.object(run, "fetch", return_value=(0, "")):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertEqual(lp.state["final_check"]["tree_sha"], tree)
        self.assertNotEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.assertTrue(run.final_check(lp, "origin/main"))
        lp.state["delivery_sha"] = self.git("rev-parse", "HEAD")
        checked = self.git("rev-parse", "HEAD^{tree}")
        self.assertIn(f"Suite-Passed-Tree: {checked}", self.land(lp))

    def review_pr(self, suite, own=True):
        lp = self.loop(suite=suite)
        head, tree = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}")
        lp.state.update(head_sha=head, own_pr=own, own_orchestrator="opus" if own else None)
        lp.save()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Fix API", "author": "acme", "body": "Fix the API"}

        original_json = run.gh_json

        def gh_json(cwd, *args, **_kw):
            return (info, "") if args[:2] == ("pr", "view") else original_json(cwd, *args, **_kw)

        with ExitStack() as mocks:
            for name, value in (("pr_view", info), ("launch_session", "fix-api"),
                                ("own_pr_orchestrator", (own, "opus" if own else None)),
                                ("checkout_for", self.repo),
                                ("fetch", (0, "")), ("make_worktree", (self.repo, "ak/fix-api")),
                                ("collect_usage", {}), ("post_review", True),
                                ("checks", (True, "")),
                                ("join_session_project", None), ("project_lessons", "")):
                mocks.enter_context(patch.object(run, name, return_value=value))
            mocks.enter_context(patch.object(gc, "disk_pressure", return_value=False))
            mocks.enter_context(patch.object(run, "gh_json", side_effect=gh_json))
            mocks.enter_context(patch.object(run, "call_retrying", side_effect=submitting((
                0, "VERDICT: PASS\n## Findings\n- none", "fixture-session", False))))
            # One round: a failed own-PR review now waits for the seat to push fixes.
            state = run.review_pr_round(self.cfg, self.directory, URL,
                                        {"--review": "astra"}, lambda line: None)
        return state, tree

    def test_own_pr_pass_names_the_suite_tree(self):
        state, tree = self.review_pr(SUITE)
        self.assertTrue(state["merged"])
        message = self.git("log", "-1", "--format=%B")
        self.assertIn(f"\nSuite-Passed-Tree: {tree}", message)
        self.assertIn(self.default_body("squash") + "\nSuite-Passed-Tree:", message)
        self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Co-authored-by)"),
                         "Co-authored-by: Acme <acme@localhost>")

    def test_own_pr_without_suite_has_no_trailer(self):
        state, _ = self.review_pr(None)
        self.assertTrue(state["merged"])
        self.assertNotIn("Suite-Passed-Tree:", self.git("log", "-1", "--format=%B"))

    def test_own_pr_suite_on_dirty_files_does_not_certify_the_commit(self):
        state, _ = self.review_pr("printf 'changed\\n' > work.txt")
        self.assertTrue(state["merged"])
        self.assertNotIn("Suite-Passed-Tree:", self.git("log", "-1", "--format=%B"))

    def test_failed_pr_reviews_do_not_name_a_nonexistent_once_log(self):
        for own in (True, False):
            with self.subTest(own=own):
                state, _ = self.review_pr("false", own=own)
                self.assertEqual(state["state"], "running" if own else "fail")
                self.assertFalse(state["merged"])
                self.assertNotIn("final_check", state)
                self.assertNotIn("once.log", run.handback_line(state, self.directory, self.cfg))
                self.assertTrue((self.directory / "round-1/donewhen.log").exists())
                self.assertFalse((self.directory / "round-1/once.log").exists())
                result = (self.directory / "result.md").read_text()
                self.assertIn("final check: none (no once-commands)", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
