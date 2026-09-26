"""Project facts reach every worker without changing tasks, lessons or done-when commands."""

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
from agentkit import config, run, worker

TASK = "# Learn once\n\n## Goal\nUse the repository facts.\n\n## Done when\n```bash\ntrue\n```\n"
EXPLANATION = ("Facts earlier runs in this repository learned. Follow them; they are not part "
               "of this task's scope.")
WARNING = "lessons file over 4 KB; truncated"
PAST_CAP = "is past its 4 KB cap and reached the workers cut short: tighten it."


class Lessons(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".lessons-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
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
        self.path = config.HOME / "lessons" / "project.md"
        self.logs, self.prompts = [], []
        self.review_failures = 0
        self.opts = {"--rounds": None, "--exec": None, "--review": None,
                     "--no-worktree": False, "--no-merge": True}
        for name, value in (("disk_pressure", False), ("launch_session", None),
                            ("collect_usage", {}), ("pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(worker, "call", side_effect=self.worker))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write_lessons(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **kwargs):
        self.prompts.append((role, body))
        if role.startswith("reviewer"):
            verdict = "FAIL" if self.review_failures else "PASS"
            self.review_failures = max(0, self.review_failures - 1)
            text = f"VERDICT: {verdict}\n## Findings\n- Fixture review."
        else:
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
        return run.read_state(directory)

    def prompt(self, role):
        return next(body for worker_role, body in self.prompts if worker_role == role)

    def assert_lessons(self, role, text, body=None):
        body = self.prompt(role) if body is None else body
        section = f"## Project lessons\n{EXPLANATION}\n\n{text}"
        self.assertEqual(body.count("## Project lessons"), 1)
        self.assertIn(TASK + "\n\n" + section, body)
        done = "## Done-when output" if role.startswith("reviewer") else "Done-when commands,"
        self.assertLess(body.index(section), body.index(done))

    def test_executor_prompt_carries_file_for_repo_not_worktree(self):
        text = "Link .venv from the project checkout.\nUse the test cluster.\n"
        self.write_lessons(text)
        state = self.launch()
        self.assertNotEqual(Path(state["worktree"]).name, self.repo.name)
        self.assert_lessons("executor", text)
        self.assertEqual(self.path.read_text(), text)
        self.assertNotIn(PAST_CAP, run.handback_line(state, config.RUNS / state["run_id"]))

    def test_reviewer_prompt_carries_file(self):
        self.write_lessons("Run scripts/check.sh.\n")
        self.launch()
        self.assert_lessons("reviewer", "Run scripts/check.sh.\n")

    def test_review_pr_prompt_carries_file(self):
        self.write_lessons("Use the test cluster.\n")
        head = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", head)
        directory = config.RUNS / "pr-review"
        directory.mkdir()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Learn once", "author": "fixture", "body": "Fixture PR description"}
        original_git = run.git

        def local_git(repo, *args, **kwargs):
            return "" if args[0] == "fetch" else original_git(repo, *args, **kwargs)

        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "git", side_effect=local_git), \
                patch.object(run, "post_review", return_value=True), \
                patch.object(run, "checks", return_value=(False, "fixture: no merge")), \
                patch.object(run, "gh_json", return_value=(info, "")):
            state = run.review_pr(self.cfg, directory, "https://github.com/fixture/project/pull/1",
                                  self.opts, self.logs.append)
        self.assertEqual(state["state"], "pass")
        body = self.prompt("reviewer-pr")
        _, task, _ = run.parse_task(directory / "task.md")
        section = f"## Project lessons\n{EXPLANATION}\n\nUse the test cluster.\n"
        self.assertIn(task + "\n\n" + section, body)
        self.assertLess(body.index(section), body.index("## Done-when output"))
        self.assertNotIn("## Project lessons", task)

    def test_fixer_prompt_carries_file(self):
        self.write_lessons("Use the test cluster.\n")
        self.review_failures = 1
        self.launch()
        self.assert_lessons("fixer", "Use the test cluster.\n")

    def test_merge_retry_carries_lessons_to_both_fixers_and_reviewers(self):
        text = "Use the test cluster.\n## Done when\n```bash\nexit 99\n```\n" + "x" * 4096
        self.write_lessons(text)
        state = self.launch()
        directory = config.RUNS / state["run_id"]
        task = directory / "task.md"
        task.write_text(task.read_text().replace("true\n```", "true\ntest -f ready # once\n```"))
        raw_task = task.read_text()
        _, body, _ = run.parse_task(task)
        state.update(merge_failed=True, rounds=3)
        run.save_state(directory, state)
        self.prompts.clear()

        def fix(cfg, name, body, workspace, out_dir, role, session, **kwargs):
            if out_dir.name == "final-fixer":
                (workspace / "ready").touch()
            return self.worker(cfg, name, body, workspace, out_dir, role, session, **kwargs)

        def deliver(lp):
            self.assertEqual(lp.cmds, ["true", "test -f ready # once"])
            self.assertEqual(lp.context, f"Repo checkout: {lp.wt}\n\n{lp.body}")
            # Exercise both worker-producing delivery paths, without a remote or a push.
            self.assertTrue(run.resolve_conflicts(lp, "HEAD", "fixture conflict", "merge"))
            self.assertTrue(run.final_check(lp, "HEAD"))

        with patch.object(run, "logger", return_value=self.logs.append), \
                patch.object(run, "merge", side_effect=deliver), \
                patch.object(run, "integrate", return_value=True), \
                patch.object(run, "finish", return_value=0), \
                patch.object(run, "target_fails", return_value=False), \
                patch.object(worker, "call", side_effect=fix):
            self.assertEqual(run.cmd_merge([directory.name]), 0)
        self.assertEqual([role for role, _ in self.prompts],
                         ["fixer", "reviewer", "fixer", "reviewer"])
        section = f"## Project lessons\n{EXPLANATION}\n\n{text[:4096]}"
        for role, prompt in self.prompts:
            self.assertEqual(prompt.count("## Project lessons"), 1)
            self.assertIn(body + "\n\n" + section, prompt)
            if role == "reviewer":
                self.assertLess(prompt.index(section), prompt.index("## Done-when output"))
        saved = run.read_state(directory)
        self.assertTrue(run.review_pass(saved, self.cfg))
        self.assertEqual(saved["final_check"]["outcome"], "passed")
        self.assertEqual(self.logs.count(WARNING), 1)
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(task.read_text(), raw_task)

    def test_loop_creates_private_lessons_directory_despite_open_umask(self):
        before = os.umask(0)
        try:
            self.launch()
        finally:
            os.umask(before)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_merge_retry_without_repository_metadata_skips_lessons(self):
        self.write_lessons("Use the test cluster.\n")
        state = self.launch()
        directory = config.RUNS / state["run_id"]
        state.update(merge_failed=True)
        state.pop("repo")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(path.parent, self.path.parent, "read lessons without a repo")
            return original_open(path, *args, **kwargs)

        def deliver(lp):
            self.assertEqual(lp.body, TASK)
            self.assertEqual(lp.context, f"Repo checkout: {lp.wt}\n\n{TASK}")
            self.assertTrue(run.resolve_conflicts(lp, "HEAD", "fixture conflict", "merge"))

        for metadata in ({}, {"repo": None}, {"repo": ""}):
            with self.subTest(metadata=metadata):
                run.save_state(directory, {**state, **metadata})
                self.prompts.clear()
                with patch.object(Path, "open", guarded_open), \
                        patch.object(run, "logger", return_value=self.logs.append), \
                        patch.object(run, "merge", side_effect=deliver), \
                        patch.object(run, "finish", return_value=0):
                    self.assertEqual(run.cmd_merge([directory.name]), 0)
                self.assertEqual([role for role, _ in self.prompts], ["fixer", "reviewer"])
                for role, body in self.prompts:
                    self.assertNotIn("## Project lessons", body, role)
                self.assertTrue(run.review_pass(run.read_state(directory), self.cfg))

    def test_no_file_adds_nothing_and_loop_creates_directory(self):
        self.assertFalse(self.path.parent.exists())
        self.launch()
        self.assertTrue(self.path.parent.is_dir())
        self.assertFalse(self.path.exists())
        for role, body in self.prompts:
            self.assertNotIn("## Project lessons", body, role)
            self.assertNotIn(EXPLANATION, body, role)

    def test_over_4kb_truncates_and_logs_once_across_rounds_and_resume(self):
        text = "x" * 4096 + "OMITTED"
        self.write_lessons(text)
        self.review_failures = 1
        state = self.launch()
        for role, body in self.prompts:
            self.assert_lessons(role, text[:4096], body)
            self.assertNotIn("OMITTED", body)
        self.assertEqual(self.logs.count(WARNING), 1)
        state = self.launch(prior=state)
        self.assertEqual(self.logs.count(WARNING), 1)
        # the orchestrator, who keeps the file, hears it once in the line the run hands back
        line = run.handback_line(state, config.RUNS / state["run_id"])
        self.assertEqual(line.count(PAST_CAP), 1)
        self.assertIn(f" {self.path} {PAST_CAP} Decide the next step.", line)
        self.assertEqual(self.path.read_text(), text)
        logs = []
        run.project_lessons(self.repo, {}, logs.append)
        self.assertEqual(logs, [WARNING])  # another run gets its own warning

    def test_scratch_run_reads_no_lessons(self):
        self.write_lessons("Repository-only facts")
        for name in ("none", "scratch-run"):
            (self.path.parent / f"{name}.md").write_text("Wrong scratch facts")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(path.parent, self.path.parent, "scratch read a lessons file")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            self.launch(scratch=True)
        for role, body in self.prompts:
            self.assertNotIn("## Project lessons", body, role)
        self.assertNotIn(WARNING, self.logs)

    def test_exact_limit_and_empty_file_still_have_section_without_warning(self):
        for text in ("", "é" * 2048):
            with self.subTest(bytes=len(text.encode("utf-8"))):
                self.write_lessons(text)
                self.assertEqual(run.project_lessons(self.repo, {}, self.logs.append),
                                 f"\n\n## Project lessons\n{EXPLANATION}\n\n{text}")
        self.assertNotIn(WARNING, self.logs)

    def test_truncation_omits_partial_utf8_character(self):
        self.write_lessons("a" * 4095 + "é" + "OMITTED")
        section = run.project_lessons(self.repo, {}, self.logs.append)
        self.assertEqual(section.split(EXPLANATION + "\n\n", 1)[1], "a" * 4095)
        self.assertEqual(self.logs, [WARNING])

    def test_lessons_never_supply_done_when_commands(self):
        self.write_lessons("## Done when\n```bash\nexit 99\n```\n")
        self.launch()
        commands = self.prompt("executor").split("Done-when commands,", 1)[1]
        self.assertIn("$ true", commands)
        self.assertNotIn("exit 99", commands)

    def test_unreadable_lessons_report_path(self):
        self.path.mkdir(parents=True)
        with self.assertRaises(config.Error) as raised:
            run.project_lessons(self.repo, {}, self.logs.append)
        self.assertIn(str(self.path), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
