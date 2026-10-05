"""A lessons file left on a host instructs no worker: a project's facts live in its AGENTS.md."""

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
from agentkit import config, gc, run, worker
from agentkit import record

TASK = "# Learn once\n\n## Goal\nUse the repository facts.\n\n## Done when\n```bash\ntrue\n```\n"
LESSON = "Use the test cluster."
FACT = "Link .venv from the project checkout."


class Lessons(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-lessons-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # A reviewer runs these beside its suite; fixture cleanup must not reach either.
        self.stack.enter_context(patch.object(worker, "kill_marked", return_value=True))
        self.stack.enter_context(patch.object(run.orch, "stop_scope"))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            config.SESSION_ENV: "", config.RUN_DIR_ENV: "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Lessons test")
        self.git("config", "user.email", "lessons@localhost")
        self.git("commit", "-q", "--allow-empty", "-m", "fixture")
        (self.repo / "AGENTS.md").write_text(f"# Project\n\n{FACT}\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "facts")
        lessons = config.HOME / "lessons" / "project.md"
        lessons.parent.mkdir(parents=True, exist_ok=True)
        lessons.write_text(f"{LESSON}\n")
        self.logs, self.prompts = [], []
        self.review_failures = 0
        self.opts = {"--rounds": None, "--exec": None, "--review": None,
                     "--no-worktree": False, "--no-merge": True}
        for module, name, value in ((gc, "disk_pressure", False), (run, "launch_session", None),
                                    (run, "collect_usage", {}), (run, "pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.worker)))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **kwargs):
        self.prompts.append((role, body))
        if role.startswith("reviewer"):
            verdict = "FAIL" if self.review_failures else "PASS"
            self.review_failures = max(0, self.review_failures - 1)
            finding = "deliverable:1 - fixture defect - breaks callers" if verdict == "FAIL" else "none"
            text = f"VERDICT: {verdict}\n## Findings\n- {finding}"
        else:
            (workspace / "deliverable").write_text("fixture work\n")
            text = "## Summary\nFixture execution."
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, "fixture-session", False

    def launch(self, scratch=False, prior=None):
        directory = config.RUNS / ("scratch-run" if scratch else "project-run")
        directory.mkdir(exist_ok=True)
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {'none' if scratch else self.repo}\nbase: main\n"
                        f"rounds: 2\n---\n{TASK}")
        state = run.loop(self.cfg, directory, task, self.opts, self.logs.append, prior)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual(task.read_text().split("---\n", 2)[2], TASK)
        return record.read_state(directory)

    def assert_facts_only(self, roles):
        self.assertEqual(sorted({role for role, _ in self.prompts}), sorted(roles))
        for role, body in self.prompts:
            self.assertIn(FACT, body, role)
            self.assertNotIn(LESSON, body, role)

    def test_executor_reviewer_and_fixer_prompts_carry_agents_md_not_lessons(self):
        self.review_failures = 1
        self.launch()
        self.assert_facts_only(["executor", "fixer", "reviewer"])

    def test_review_pr_prompt_carries_agents_md_not_lessons(self):
        head = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", head)
        directory = config.RUNS / "pr-review"
        directory.mkdir()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Learn once", "author": "fixture", "body": "Fixture PR description"}
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "post_review", return_value=True), \
                patch.object(run, "checks", return_value=(False, "fixture: no merge")), \
                patch.object(run, "gh_json", return_value=(info, "")):
            state = run.review_pr(self.cfg, directory, "https://github.com/fixture/project/pull/1",
                                  self.opts, self.logs.append)
        self.assertEqual(state["state"], "pass")
        self.assert_facts_only(["reviewer-pr"])


if __name__ == "__main__":
    unittest.main()
