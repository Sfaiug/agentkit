"""Workers get whole base rules; growing AGENTS.md past what a harness reads fails the round."""

from contextlib import ExitStack
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
            text = f"VERDICT: {verdict}\n## Findings\n- {finding}\n"
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
        state = {"base": "main", "base_sha": self.git("rev-parse", "HEAD"), "rounds": 1,
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

    def test_handback_ignores_legacy_cut_state_for_both_files(self):
        self.commit_rules("x" * (OLD_CUT + 1))
        state = {"repo": str(self.repo), "state": "blocked", "error": "acme ending",
                 "rules_truncated": True, "lessons_truncated": True}
        lessons = config.HOME / "lessons" / "acme.md"
        lessons.parent.mkdir(parents=True)
        lessons.write_text("x" * (4096 + 1))
        line = run.handback_line(state, config.RUNS / "acme-run", self.cfg)
        self.assertNotIn("cut short", line)
        self.assertNotIn(str(self.path), line)
        self.assertNotIn(str(lessons), line)

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
        front = "---\nnotes: x\n---\n"
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
        real = run.tool_run

        def timing_out(argv, **kwargs):
            return (None, "", "timed out") if "cat-file" in argv else real(argv, **kwargs)

        with patch.object(run, "tool_run", side_effect=timing_out), self.assertRaises(run.Stopped):
            run.rules_cap(lp)

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
