"""Clipped repository rules reach the launching seat in the run's ending."""

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

TASK = "# Acme rules\n\n## Goal\nUse the repository rules.\n\n## Done when\n```bash\ntrue\n```\n"
WARNING = "AGENTS.md over 8 KB; truncated"
NOTICE = "reached the workers cut short at its 8 KB cap: tighten it."


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
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "acme")
        self.git("config", "user.email", "acme@localhost")
        self.path = self.repo / "AGENTS.md"
        self.logs, self.prompts = [], []
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
        self.prompts.append(body)
        text = ("VERDICT: PASS\n## Findings\n- none\n" if role.startswith("reviewer")
                else "## Summary\nAcme work.\n")
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

    def test_run_records_the_cut_and_tells_the_seat_after_resume(self):
        self.commit_rules("---\nusers: none\n---\n" + "x" * run.RULES_CAP + "OMITTED")
        state, directory = self.launch()
        self.assertTrue(state["rules_truncated"])
        self.assertEqual(len(self.prompts), 2)
        for prompt in self.prompts:
            self.assertIn("x" * run.RULES_CAP, prompt)
            self.assertNotIn("OMITTED", prompt)
        # Worker edits and a shorter live file cannot undo what the base commit supplied.
        (Path(state["worktree"]) / "AGENTS.md").write_text("Short rules.\n")
        self.path.write_text("Short rules.\n")
        state, directory = self.launch(prior=state)
        self.assertEqual(self.logs.count(WARNING), 1)
        line = run.handback_line(state, directory, self.cfg)
        self.assertEqual(line.count(NOTICE), 1)
        self.assertIn(f" {self.path} {NOTICE} Decide the next step.", line)

    def test_rules_and_lessons_share_the_notice(self):
        ref = self.commit_rules("x" * (run.RULES_CAP + 1))
        state = {"repo": str(self.repo), "state": "blocked", "error": "acme ending"}
        lessons = config.HOME / "lessons" / "acme.md"
        lessons.parent.mkdir(parents=True)
        lessons.write_text("x" * (run.LESSONS_CAP + 1))
        run.project_lessons(self.repo, state, self.logs.append)
        run.repo_rules(self.repo, ref, state, self.logs.append)
        line = run.handback_line(state, config.RUNS / "acme-run", self.cfg)
        self.assertIn(f" {self.path} {NOTICE}", line)
        self.assertIn(f" {lessons} {NOTICE.replace('8 KB', '4 KB')}", line)
        lessons.write_text("Short lessons.\n")
        line = run.handback_line(state, config.RUNS / "acme-run", self.cfg)
        self.assertIn(f" {self.path} {NOTICE}", line)
        self.assertNotIn(str(lessons), line)

    def test_cap_counts_only_body_bytes_and_accepts_the_exact_limit(self):
        ref = self.commit_rules("---\nnotes: " + "x" * run.RULES_CAP + "\n---\n"
                                + "é" * (run.RULES_CAP // 2) + "\n")
        state = {"repo": str(self.repo), "state": "blocked", "error": "acme ending"}
        section = run.repo_rules(self.repo, ref, state, self.logs.append)
        self.assertIn("é" * (run.RULES_CAP // 2), section)
        self.assertNotIn("notes:", section)
        self.assertNotIn("rules_truncated", state)
        self.assertEqual(self.logs, [])
        self.assertNotIn(NOTICE, run.handback_line(state, config.RUNS / "acme-run", self.cfg))

    def test_cut_omits_partial_utf8_character(self):
        ref = self.commit_rules("a" * (run.RULES_CAP - 1) + "éOMITTED")
        state = {}
        section = run.repo_rules(self.repo, ref, state, self.logs.append)
        self.assertTrue(section.endswith("a" * (run.RULES_CAP - 1) + "\n"))
        self.assertNotIn("é", section)
        self.assertNotIn("OMITTED", section)
        self.assertTrue(state["rules_truncated"])

    def test_missing_or_empty_rules_add_no_notice(self):
        for text in ("", "---\nusers: none\n---\n"):
            ref = self.commit_rules(text)
            state = {}
            self.assertEqual(run.repo_rules(self.repo, ref, state, self.logs.append), "")
            self.assertNotIn("rules_truncated", state)
        state = {}
        self.assertEqual(run.repo_rules(self.repo, None, state, self.logs.append), "")
        self.assertEqual(run.repo_rules(self.repo, "missing-ref", state, self.logs.append), "")
        self.assertNotIn("rules_truncated", state)
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main()
