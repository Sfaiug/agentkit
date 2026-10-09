"""Workers get whole base rules; growing AGENTS.md past what a harness reads fails the round."""

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, gc, record, run, worker

LIMIT = 64          # the test harness's read limit, far below any real one
OLD_CUT = 8 * 1024  # where workers' rules used to be cut
TASK = "# Acme rules\n\n## Goal\nUse the repository rules.\n\n## Done when\n```bash\ntrue\n```\n"


class RulesCapTold(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-rules-cap-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, self.root / key.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", config.SESSION_ENV: "",
            config.RUN_DIR_ENV: "", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text(f"[instructions]\nread_limit = {LIMIT}\n")
        stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "acme")
        self.git("config", "user.email", "acme@localhost")
        self.git("commit", "-q", "--allow-empty", "-m", "acme base")
        self.path = self.repo / "AGENTS.md"
        self.logs, self.prompts = [], []
        self.review_failures = 0
        self.review_extra = ""
        for module, name, value in (
                (gc, "disk_pressure", False), (run, "launch_session", None),
                (run, "collect_usage", {}), (run, "pick_models", ("opus", "astra")),
                (run.usage, "pick_order", ["opus", "astra"]),
                (worker, "kill_marked", True), (run.orch, "stop_scope", None)):
            stack.enter_context(patch.object(module, name, return_value=value))
        stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.worker)))
        stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit_rules(self, text):
        self.path.write_text(text, encoding="utf-8")
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "acme rules")
        return self.git("rev-parse", "HEAD")

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **_kw):
        self.prompts.append((role, body))
        if role.startswith("reviewer"):
            verdict = "FAIL" if self.review_failures else "PASS"
            self.review_failures = max(0, self.review_failures - 1)
            finding = "deliverable:1 - acme defect - breaks callers" if verdict == "FAIL" else "none"
            text = f"VERDICT: {verdict}\n## Findings\n- {finding}\n{self.review_extra}"
        else:
            text = "## Summary\nAcme work.\n"
        (workspace / "deliverable").write_text("acme\n")
        return 0, text, "acme-session", False

    def launch(self, prior=None):
        directory = config.RUNS / "acme-run"
        directory.mkdir(exist_ok=True)
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\nbase: main\n---\n{TASK}")
        opts = {"--rounds": None, "--exec": None, "--review": None,
                "--no-worktree": False, "--no-merge": True}
        state = run.loop(self.cfg, directory, task, opts, self.logs.append, prior)
        self.assertEqual(state["state"], "pass", self.logs)
        return record.read_state(directory), directory

    def loop(self, cmds=("true",)):
        directory = config.RUNS / "rules-check"
        directory.mkdir()
        (directory / "task.md").write_text(TASK)
        state = {"title": "fix api", "base": "main", "base_sha": self.git("rev-parse", "HEAD"), "rounds": 1,
                 "executor": "opus", "reviewer": "astra", "round_summaries": []}
        lp = run.Loop(self.cfg, directory, state, {}, self.logs.append,
                      self.repo, TASK, list(cmds), TASK, [])
        lp.rnd = 1
        lp.round_dir.mkdir()
        return lp

    def test_workers_get_whole_base_rules_across_rounds_and_resume(self):
        body = "x" * OLD_CUT + "éLAST RULE"
        self.commit_rules("---\nusers: none\n---\n" + body)
        self.review_failures = 1
        state, directory = self.launch()
        self.assertEqual([role for role, _ in self.prompts],
                         ["executor", "reviewer", "fixer", "reviewer"])
        for role, prompt in self.prompts:
            self.assertIn(body, prompt, role)
            self.assertNotIn("users: none", prompt)
        self.assertNotIn("rules_truncated", state)
        # A shorter live file cannot undo what the base commit supplied.
        (Path(state["worktree"]) / "AGENTS.md").write_text("Short rules.\n")
        self.path.write_text("Short rules.\n")
        state, directory = self.launch(prior=state)
        self.assertIn(body, run.repo_rules(Path(state["worktree"]), state["base_sha"]))
        self.assertFalse(any("truncated" in line for line in self.logs))
        self.assertNotIn("cut short", run.handback_line(state, directory, self.cfg))

    def test_handback_ignores_legacy_cut_state(self):
        self.commit_rules("x" * (OLD_CUT + 1))
        state = {"repo": str(self.repo), "state": "blocked", "error": "acme ending",
                 "rules_truncated": True, "lessons_truncated": True}
        line = run.handback_line(state, config.RUNS / "acme-run", self.cfg)
        self.assertNotIn("cut short", line)
        self.assertNotIn(str(self.path), line)

    def test_added_oversized_body_fails_checks_and_resume_in_any_repo(self):
        lp = self.loop()
        self.path.write_text("é" * (LIMIT // 2) + "x")
        ok, text = run.verify_work(lp)
        failure = f"AGENTS.md is {LIMIT + 1} bytes, past the {LIMIT} bytes acme reads of it: tighten it."
        self.assertFalse(ok, text)
        self.assertIn("[exit 0]", text)
        self.assertEqual(text.splitlines()[-1], failure)
        self.assertEqual(run.first_failure(text), failure)
        self.assertEqual((lp.round_dir / "donewhen.log").read_text(), text)
        self.assertEqual(self.git("status", "--porcelain"), "")
        lp.state["step"] = "reviewer"
        self.assertEqual(run.settled_gate(lp), (False, text))

    def test_front_matter_change_must_leave_an_oversized_file_within_the_ceiling(self):
        body = "x" * LIMIT
        self.commit_rules("---\nusers: none\n---\n" + body)
        lp = self.loop()
        changed = "---\nusers: all\n---\n" + body
        self.path.write_text(changed)
        ok, text = run.verify_work(lp)
        self.assertFalse(ok, text)
        self.assertIn(f"AGENTS.md is {len(changed)} bytes", text)

    def test_ceiling_counts_the_whole_file_and_accepts_the_exact_limit(self):
        lp = self.loop()
        front = "---\nusers: x\n---\n"
        accents = (LIMIT - len(front)) // 2
        exact = front + "é" * accents + "x" * (LIMIT - len(front) - 2 * accents)
        self.assertEqual(len(exact.encode("utf-8")), LIMIT)
        self.path.write_text(exact, encoding="utf-8")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.path.write_text(exact + "x", encoding="utf-8")
        ok, text = run.verify_work(lp)
        self.assertFalse(ok, text)
        self.assertIn(f"AGENTS.md is {LIMIT + 1} bytes", text)

    def test_no_harness_limit_means_no_ceiling(self):
        lp = self.loop()
        self.path.write_text("x" * OLD_CUT * 4)
        with patch.object(config, "manifests", return_value=iter([("acme", {})])):
            ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)

    def test_the_smallest_declared_read_limit_wins(self):
        found = [("big", {"instructions": {"read_limit": 4096}}), ("none", {}),
                 ("odd", {"instructions": {"read_limit": True}}),
                 ("zero", {"instructions": {"read_limit": 0}}),
                 ("small", {"instructions": {"read_limit": 512}})]
        with patch.object(config, "manifests", return_value=iter(found)):
            self.assertEqual(config.instruction_ceiling(), (512, "small"))
        # the shipped adapters: Codex's own reader is the smallest today
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: ""}):
            self.assertEqual(config.instruction_ceiling(), (32768, "codex"))

    def assert_round_fails_with(self, line):
        ok, text = run.verify_work(self.loop_)
        self.assertFalse(ok, text)
        self.assertEqual(text.splitlines()[-1], line)

    def test_a_front_matter_line_ak_does_not_read_fails_the_round(self):
        # a misspelled `tests:` would silently run no suite at landing
        self.commit_rules("---\nusers: none\n---\nAcme.\n")
        self.loop_ = self.loop()
        self.path.write_text("---\nusers: none\ntest: make check\npreview: make serve\n---\nAcme.\n")
        self.assert_round_fails_with(
            "AGENTS.md front matter has lines ak does not read: `test: make check`, "
            "`preview: make serve` (it reads tests, health, cleanup, users, features): "
            "remove them, or fix the misspelled name.")

    def test_unread_lines_in_any_line_ending_or_after_a_blank_line_fail(self):
        for text in (b"---\rtest: make check\r---\rAcme.\r",
                     b"---\r\ntest: make check\r\n---\r\nAcme.\r\n",
                     b"\n---\ntest: make check\n---\nAcme.\n"):
            with self.subTest(text=text):
                self.commit_rules("---\nusers: none\n---\nAcme.\n")
                self.loop_ = self.loop()
                self.path.write_bytes(text)
                ok, out = run.verify_work(self.loop_)
                self.assertFalse(ok, out)
                self.assertIn("`test: make check`", out)
                shutil.rmtree(self.loop_.run_dir)

    def test_a_changed_agents_md_must_not_go_through_a_filter(self):
        self.commit_rules("---\nusers: none\n---\nAcme.\n")
        self.git("config", "filter.acme.smudge", "cat")
        self.git("config", "filter.acme.clean", "cat")
        (self.repo / ".gitattributes").write_text("AGENTS.md filter=acme\n")
        self.loop_ = self.loop()
        self.path.write_text("---\nusers: real\n---\nAcme.\n")
        self.assert_round_fails_with(
            "AGENTS.md must not go through a Git filter: ak reads its front matter as committed.")

    def test_unread_lines_already_on_base_block_only_a_change_to_agents_md(self):
        self.commit_rules("---\npreview: make serve\ntests: make check\n---\nAcme.\n")
        lp = self.loop()
        (self.repo / "deliverable").write_text("acme\n")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.path.write_text("---\ntests: make check\n# kept as a note\n---\nAcme.\n")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)

    def test_untouched_oversized_base_file_passes_checks(self):
        self.commit_rules("x" * (LIMIT + 1))
        lp = self.loop()
        (self.repo / "deliverable").write_text("acme\n")
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        self.assertNotIn("AGENTS.md is", text)

    def test_a_size_read_that_never_answered_stops_the_check(self):
        # a timed-out read is no deleted file: the oversized file must not pass as 0 bytes
        lp = self.loop()
        self.commit_rules("x" * (LIMIT + 1))
        real = subprocess.run

        def timing_out(argv, **kwargs):
            if "cat-file" in argv:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return real(argv, **kwargs)

        with patch.object(run.subprocess, "run", side_effect=timing_out), \
                self.assertRaises(run.Stopped):
            run.rules_check(lp)

    def test_the_size_is_the_file_as_checked_out(self):
        # with CRLF line ends on checkout, a blob at the limit is past it where a harness reads it
        (self.repo / ".gitattributes").write_text("AGENTS.md text eol=crlf\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-q", "-m", "attributes")
        lp = self.loop()
        self.commit_rules("x\n" * (LIMIT // 2))
        self.assertEqual(self.git("cat-file", "-s", "HEAD:AGENTS.md"), str(LIMIT))
        self.assertIn(f"AGENTS.md is {LIMIT // 2 * 3} bytes", run.rules_check(lp))

    def test_a_pr_review_with_no_suite_checks_agents_md_and_says_why(self):
        # own PRs run no suite in review, nor do others' PRs with no `tests:`; a PASS merges
        self.commit_rules("Acme rules.\n")
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        self.commit_rules("x" * (LIMIT + 1))
        head = self.git("rev-parse", "HEAD")
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Grow the rules", "author": "fixture", "body": "Fixture PR description"}
        opts = {"--rounds": None, "--exec": None, "--review": None, "--no-worktree": False,
                "--no-merge": True}
        published = []

        def github(run_dir, *args):
            published.append(Path(args[-1].removeprefix("body=@")).read_text())
            return 0, ""

        # a long report: its kept tail no longer reaches the top
        self.review_extra = "## Follow-ups\n- acme.py:1 - " + "acme detail " * 1000 + "\n"
        for own in (False, True):
            with self.subTest(own=own), \
                    patch.object(run, "own_pr_orchestrator", return_value=(own, "opus" if own else None)), \
                    patch.object(run, "pr_view", return_value=info), \
                    patch.object(run, "checkout_for", return_value=self.repo), \
                    patch.object(run, "fetch", return_value=(0, "")), \
                    patch.object(run, "gh", side_effect=github), \
                    patch.object(run, "checks", return_value=(True, "")), \
                    patch.object(run.watch, "ask_inbox", return_value=0), \
                    patch.object(run, "merge_own_pr", side_effect=AssertionError("merged")), \
                    patch.object(run, "fix_own_pr", return_value=False), \
                    patch.object(run, "gh_json", return_value=(info, "")):
                directory = config.RUNS / f"pr-review-{own}"
                directory.mkdir()
                state = run.review_pr(self.cfg, directory, "https://github.com/acme/rules/pull/1",
                                      opts, self.logs.append)
                why = f"AGENTS.md is {LIMIT + 1} bytes"
                self.assertEqual(state["verdict"], "FAIL")
                self.assertIn(why, published[-1])
                self.assertIn(why, (directory / "result.md").read_text())
                self.assertIn(why, run.handback_reason(state))

    def test_a_linked_agents_md_is_refused_never_read_as_rules(self):
        (self.repo / "acme-rules.md").write_text("Acme rules.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "rules beside no AGENTS.md")
        lp = self.loop()
        self.path.symlink_to("acme-rules.md")
        self.git("add", ".")
        self.git("commit", "-qm", "linked AGENTS.md")
        with self.subTest(case="added"):
            failure = run.rules_check(lp)
            self.assertTrue(failure.startswith("AGENTS.md is a link"), failure)
            self.assertTrue(run.LOOP_NOTE.match(failure))
            self.assertEqual(run.repo_rules(self.repo, "HEAD"), "")
        with self.subTest(case="added, no harness limit"), \
                patch.object(config, "manifests", return_value=iter([("acme", {})])):
            ok, text = run.verify_work(lp)
            self.assertFalse(ok, text)
            self.assertIn("AGENTS.md is a link", text)
        lp.state["base_sha"] = self.git("rev-parse", "HEAD")
        (self.repo / "deliverable").write_text("acme\n")
        self.git("add", "deliverable")
        self.git("commit", "-qm", "leave the rules alone")
        with self.subTest(case="untouched"):
            self.assertEqual(run.rules_check(lp), "")
        self.path.unlink()
        self.path.write_text("Acme rules.\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-qm", "rules in AGENTS.md itself")
        with self.subTest(case="made a file"):
            self.assertEqual(run.rules_check(lp), "")
            self.assertTrue(run.repo_rules(self.repo, "HEAD").endswith("Acme rules.\n"))

    def test_a_filtered_agents_md_is_refused_before_any_read(self):
        # a filter, even one that fails, means a checkout may hold other text than the commit
        (self.repo / ".gitattributes").write_text("AGENTS.md filter=broken\n")
        for key, value in (("smudge", "false"), ("clean", "cat"), ("required", "true")):
            self.git("config", f"filter.broken.{key}", value)
        self.git("add", ".gitattributes")
        self.git("commit", "-q", "-m", "attributes")
        lp = self.loop()
        self.commit_rules("x" * (LIMIT + 1))
        failure = run.rules_check(lp)
        self.assertEqual(failure, "AGENTS.md must not go through a Git filter: ak reads its "
                                  "front matter as committed.")
        self.assertTrue(run.LOOP_NOTE.match(failure))

    def test_unavailable_tracked_rules_fail_the_check(self):
        lp = self.loop()
        self.commit_rules("x" * 40000)
        blob = self.git("rev-parse", "HEAD:AGENTS.md")
        (self.repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
        self.assertEqual(self.path.stat().st_size, 40000)
        self.assertEqual(self.git("ls-tree", "--name-only", "HEAD", "--", "AGENTS.md"),
                         "AGENTS.md")
        failure = run.rules_check(lp)
        self.assertTrue(failure.startswith("AGENTS.md could not be read as a checkout holds it"),
                        f"Tracked AGENTS.md with an unavailable blob passed: {failure!r}")
        self.assertIn(f"{LIMIT} bytes acme reads of it is unknown", failure)
        self.assertTrue(run.LOOP_NOTE.match(failure))

    def test_removed_oversized_rules_pass_checks(self):
        self.commit_rules("x" * (LIMIT + 1))
        lp = self.loop()
        self.path.unlink()
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)

    def test_cap_note_preserves_a_failing_commands_output(self):
        cmd = "echo 'acme check failed'; false"
        lp = self.loop(cmds=(cmd,))
        self.path.write_text("x" * (LIMIT + 1))
        ok, text = run.verify_work(lp)
        self.assertFalse(ok, text)
        self.assertIn("AGENTS.md is", text)
        self.assertEqual(run.failing_checks(text), [[cmd, "acme check failed"]])
        self.assertEqual(run.first_failure(text), f"`{cmd}` — acme check failed")

    def test_fixer_gets_cap_failure_and_reviewer_pass_is_overridden(self):
        lp = self.loop()
        lp.rnd = 0
        fixes = []

        def execute(lp, role, text, name, **_kw):
            lp.round_dir.mkdir(exist_ok=True)
            if role == "executor":
                self.path.write_text("x" * (LIMIT + 1))
            else:
                fixes.append(text)
            return "## Summary\nAcme work."

        with patch.object(run, "execute", side_effect=execute), \
                patch.object(run, "pickup_new_code", return_value=False):
            run.rounds(lp)
        self.assertEqual(len(fixes), 1)
        self.assertIn(f"AGENTS.md is {LIMIT + 1} bytes", fixes[0])
        self.assertEqual(lp.state["verdict"], "FAIL")
        self.assertFalse(lp.state["review"]["done_when"])
        self.assertIn("overridden", lp.state["review"])

    def test_whole_rules_preserve_utf8_across_the_old_cut(self):
        ref = self.commit_rules("a" * (OLD_CUT - 1) + "éOMITTED")
        section = run.repo_rules(self.repo, ref)
        self.assertTrue(section.endswith("a" * (OLD_CUT - 1) + "éOMITTED\n"))

    def test_missing_or_empty_rules_add_nothing(self):
        for text in ("", "---\nusers: none\n---\n"):
            ref = self.commit_rules(text)
            self.assertEqual(run.repo_rules(self.repo, ref), "")
        self.assertEqual(run.repo_rules(self.repo, None), "")
        self.assertEqual(run.repo_rules(self.repo, "missing-ref"), "")
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main()
