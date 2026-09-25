"""agentkit v5q: several task files are one job, independent ones at once. Offline."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run

ADAPTER = '''import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["V5Q_FIXTURE"])
if sys.argv[1] == "usage":
    used = 100 if (root / "meters-full").exists() else 0
    print(json.dumps({"meters": [{"name": "weekly", "used": used}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role}) + "\\n")
if role == "executor":
    deadline = time.monotonic() + 20
    while (root / "hold").exists():
        assert time.monotonic() < deadline, "fixture was not released"
        time.sleep(.02)
    if not (root / "break-donewhen").exists():
        pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
    (out / "final.md").write_text("## Summary\\nFixture work.")
else:
    answer = ("VERDICT: FAIL\\n\\n## Findings\\n- flaw.py:1 - pattern - why it matters\\n"
              if "Failing" in prompt else "VERDICT: PASS\\n\\n## Findings\\n- none\\n")
    (out / "final.md").write_text(answer)
(out / "session_id").write_text("session-" + role)
'''

PASS = "VERDICT: PASS\n\n## Findings\n- none\n"
FAIL = "VERDICT: FAIL\n\n## Findings\n- flaw.py:1 - pattern - why it matters\n"


class JobFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5q-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        # JOBS is deliberately not patched: it follows HOME, which is what keeps job
        # receipts out of the owner's real ~/.agentkit in every other suite too
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "seat-v5q", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "V5Q_FIXTURE": str(self.root), "AK_SLOT_POLL": ".01",
            "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                             "load": 1, "cpus": 8,
                                             "unit_memory_current_mb": 100,
                                             "unit_memory_high_mb": 1000})}))
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.shaped = self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.stack.enter_context(patch.object(orch, "watching", return_value=True))
        self.stack.enter_context(patch.object(run, "JOB_TICK", 0.05))
        self.stack.enter_context(patch.object(run, "JOB_PICKER_INTERVAL", 0))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.reviews(PASS)

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    def task(self, name, title, after=(), rounds=1):
        lines = ["---", "repo: none", f"rounds: {rounds}"]
        for dep in after:
            lines.append(f"after: {dep}")
        lines += ["---", f"# {title}", "", "## Done when", "```bash", "test -f deliverable", "```", ""]
        path = self.root / name
        path.write_text("\n".join(lines))
        return str(path)

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)

    def git_repo(self):
        """A fixture repo with one commit and a local bare `origin`, offline."""
        path = self.root / "repo"
        path.mkdir()
        self.git(path, "init", "-q", "-b", "main")
        self.git(path, "config", "user.email", "fixture@localhost")
        self.git(path, "config", "user.name", "fixture")
        (path / "keep").write_text("seed\n")
        self.git(path, "add", "-A")
        self.git(path, "commit", "-qm", "seed")
        bare = self.root / "repo.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                       capture_output=True)
        self.git(path, "remote", "add", "origin", str(bare))
        self.git(path, "push", "-q", "origin", "main")
        return path

    def repo_task(self, name, title, repo, after=(), rounds=1):
        lines = ["---", f"repo: {repo}", "base: main", f"rounds: {rounds}"]
        for dep in after:
            lines.append(f"after: {dep}")
        lines += ["---", f"# {title}", "", "## Done when", "```bash", "test -f deliverable", "```", ""]
        path = self.root / name
        path.write_text("\n".join(lines))
        return str(path)

    def fake_delivery(self):
        """Stub out only the GitHub half of delivery: review evidence stays real."""
        def delivered(lp):
            run.require_review_pass(lp)
            lp.state.update(merged=True, merge_failed=False, merge_note=None,
                            pr="https://example.invalid/pr/1")
            lp.log("merged (fixture delivery)")
            run.save_state(lp.run_dir, lp.state)
            return True

        return patch.object(run, "merge", side_effect=delivered)

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def job_dirs(self):
        return sorted(d for d in config.JOBS.iterdir() if d.is_dir()) if config.JOBS.exists() else []

    def read_job(self, job_dir):
        return json.loads((job_dir / "job.json").read_text())

    def wait_for(self, predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "job did not reach expected state")
            time.sleep(0.02)

    def test_v5q_three_independent_start_at_once(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        c = self.task("c.md", "Gamma task")
        (self.root / "hold").touch()
        result, job_dir = {}, {}

        def launch():
            with redirect_stdout(io.StringIO()):
                result["rc"] = run.main([a, b, c, "--exec", self.executor,
                                         "--review", self.reviewer])

        thread = threading.Thread(target=launch, daemon=True)
        thread.start()
        try:
            self.wait_for(lambda: self.job_dirs() and
                          sum(1 for t in self.read_job(self.job_dirs()[0])["tasks"]
                              if t["state"] == "running") == 3)
            job = self.read_job(self.job_dirs()[0])
            self.assertEqual({t["state"] for t in job["tasks"]}, {"running"})
        finally:
            (self.root / "hold").unlink(missing_ok=True)
            thread.join(timeout=60)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["rc"], 0)
        job = self.read_job(self.job_dirs()[0])
        self.assertEqual({t["state"] for t in job["tasks"]}, {"passed"})

    def test_v5q_parallel_two_starts_two_then_third(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        c = self.task("c.md", "Gamma task")
        (self.root / "hold").touch()
        result = {}

        def launch():
            with redirect_stdout(io.StringIO()):
                result["rc"] = run.main([a, b, c, "--parallel", "2",
                                         "--exec", self.executor, "--review", self.reviewer])

        thread = threading.Thread(target=launch, daemon=True)
        thread.start()
        try:
            self.wait_for(lambda: self.job_dirs() and
                          sum(1 for t in self.read_job(self.job_dirs()[0])["tasks"]
                              if t["state"] == "running") == 2)
            job = self.read_job(self.job_dirs()[0])
            queued = [t for t in job["tasks"] if t["state"] == "queued"]
            self.assertEqual(len(queued), 1)
        finally:
            (self.root / "hold").unlink(missing_ok=True)
            thread.join(timeout=60)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["rc"], 0)
        job = self.read_job(self.job_dirs()[0])
        self.assertEqual({t["state"] for t in job["tasks"]}, {"passed"})

    def test_v5q_no_budget_waits_queued_then_starts(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        (self.root / "meters-full").touch()  # every fake meter reads 100% used
        result = {}

        def launch():
            # no --exec/--review: the picker itself must find budget, or Exhausted
            with redirect_stdout(io.StringIO()):
                result["rc"] = run.main([a, b])

        thread = threading.Thread(target=launch, daemon=True)
        thread.start()
        try:
            self.wait_for(lambda: self.job_dirs())
            # the picker keeps failing, but nothing fails for it: both tasks wait queued
            time.sleep(0.4)
            job = self.read_job(self.job_dirs()[0])
            self.assertEqual([t["state"] for t in job["tasks"]], ["queued", "queued"])
            self.assertEqual(run.run_dirs(), [])
            # the meter refills: drop the flag and the cached 100% reading
            (self.root / "meters-full").unlink()
            (config.STATE / "usage.json").unlink(missing_ok=True)
            thread.join(timeout=60)
        finally:
            (self.root / "meters-full").unlink(missing_ok=True)
            (config.STATE / "usage.json").unlink(missing_ok=True)
            thread.join(timeout=60)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["rc"], 0)
        job = self.read_job(self.job_dirs()[0])
        self.assertEqual({t["state"] for t in job["tasks"]}, {"passed"})

    def test_v5q_after_holds_until_dependency_merged(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task", after=["a.md"])
        with redirect_stdout(io.StringIO()):
            rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 0)
        job = self.read_job(self.job_dirs()[0])
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["a.md"]["after"], [])
        self.assertEqual(by_name["b.md"]["after"], ["a.md"])
        self.assertEqual(by_name["a.md"]["state"], "passed")
        self.assertEqual(by_name["b.md"]["state"], "passed")
        self.assertLessEqual(by_name["a.md"]["finished_at"], by_name["b.md"]["started_at"])

    def test_v5q_failed_dependency_skips_dependant(self):
        a = self.task("fail-a.md", "Failing task", rounds=1)
        b = self.task("dep-b.md", "Dependant task", after=["fail-a.md"])
        c = self.task("lone-c.md", "Independent task")
        with redirect_stdout(io.StringIO()):
            rc = run.main([a, b, c, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 1)
        job = self.read_job(self.job_dirs()[0])
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["fail-a.md"]["state"], "failed")
        self.assertEqual(by_name["dep-b.md"]["state"], "skipped")
        self.assertIn("skipped: fail-a.md did not merge", by_name["dep-b.md"]["verdict_line"])
        self.assertEqual(by_name["lone-c.md"]["state"], "passed")
        log = (self.job_dirs()[0] / "log.txt").read_text()
        self.assertIn("skipped: fail-a.md did not merge", log)

    def test_v5q_one_done_card_when_all_merged(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 0)
        self.assertEqual(self.shaped.call_count, 1)
        args, kwargs = self.shaped.call_args
        self.assertEqual(args[0], "done")
        self.assertEqual(kwargs.get("session"), "seat-v5q")
        log = (self.job_dirs()[0] / "log.txt").read_text()
        self.assertIn("a.md: PASS", log)
        self.assertIn("b.md: PASS", log)

    def test_v5q_a_task_that_needs_the_owner_goes_back_to_the_seat_instead(self):
        # v5ay: the seat that launched the job is there, so its failures are that seat's to
        # act on -- the owner is never asked while it is, and a seat mid-turn leaves the
        # line on the job's record for the tick's next quiet prompt.
        a = self.task("a.md", "Failing task", rounds=1)
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 1)
        self.assertEqual(self.shaped.call_count, 0)
        job = self.read_job(self.job_dirs()[0])
        self.assertIn("task(s) need you", job["handback_pending"])
        self.assertIn("Decide the next step.", job["handback_pending"])
        log = (self.job_dirs()[0] / "log.txt").read_text()
        self.assertIn("needs you", log)
        self.assertIn("its seat is not at its prompt", log)

    def test_v5q_job_json_exists_before_first_run_and_current(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a, b],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        # written before the first run starts: no run directories yet
        self.assertTrue((job_dir / "job.json").exists())
        saved = self.read_job(job_dir)
        self.assertEqual(saved["job_id"], job_dir.name)
        self.assertEqual(saved["seat"], "seat-v5q")
        self.assertIsNone(saved["finished_at"])
        self.assertEqual([t["state"] for t in saved["tasks"]], ["queued", "queued"])
        self.assertEqual(run.run_dirs(), [])
        with redirect_stdout(io.StringIO()):
            rc = run.run_job_loop(self.cfg, job_dir, job, to_file=True)
        self.assertEqual(rc, 0)
        saved = self.read_job(job_dir)
        self.assertIsNotNone(saved["finished_at"])
        self.assertEqual({t["state"] for t in saved["tasks"]}, {"passed"})
        for task in saved["tasks"]:
            for key in ("name", "title", "after", "state", "run_id", "executor",
                        "reviewer", "started_at", "finished_at"):
                self.assertIn(key, task)
            self.assertIsNotNone(task["run_id"])

    def test_v5q_status_prints_job_block(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([]), 0)
        text = out.getvalue()
        job_id = self.job_dirs()[0].name
        self.assertIn(f"job {job_id}:", text)
        self.assertIn("passed", text)
        self.assertIn("a.md: PASS", text)

    def test_v5q_resume_after_kill_resumes_interrupted_and_starts_unstarted(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a, b],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        # the kill lands after the launcher allocated a's run but before any work finished
        run_dir_a = run.job_allocate_run_dir("Alpha task")
        (run_dir_a / "task.md").write_text(Path(a).read_text())
        run_opts = {"--rounds": None, "--exec": self.executor, "--review": self.reviewer,
                    "--review-pr": None, "--no-merge": False, "--no-worktree": False,
                    "--bg": False}
        with redirect_stdout(io.StringIO()):
            run.prepare(run_dir_a, run_opts, run.logger(run_dir_a, True))
        state = run.read_state(run_dir_a)
        state.update(state="interrupted", interrupted_at=time.time(),
                     interruption_reason="killed in test", recovery_pending=True)
        run.save_state(run_dir_a, state)
        job["tasks"][0].update(state="running", run_id=run_dir_a.name, started_at=time.time())
        # the kill took the launcher: resume refuses a live one, so record the death
        job.update(pid=99999999)
        job.pop("process_identity", None)
        run.save_job(job_dir, job)
        before = set(run.run_dirs())
        with redirect_stdout(io.StringIO()):
            rc = run.cmd_resume([job_dir.name])
        self.assertEqual(rc, 0)
        # adopting the interrupted run sent no per-task recovery noise: one Done card only
        self.assertEqual(self.shaped.call_count, 1)
        self.assertEqual(self.shaped.call_args.args[0], "done")
        # the interrupted run resumed in its own directory; only the unstarted task is new
        fresh = set(run.run_dirs()) - before
        self.assertEqual(len(fresh), 1)
        self.assertNotIn(run_dir_a, fresh)
        job = self.read_job(job_dir)
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["a.md"]["state"], "passed")
        self.assertEqual(by_name["a.md"]["run_id"], run_dir_a.name)
        self.assertEqual(by_name["b.md"]["state"], "passed")
        self.assertNotEqual(by_name["b.md"]["run_id"], run_dir_a.name)

    def test_v5q_resume_adopts_finished_run_without_rerunning(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main([a, "--exec", self.executor,
                                       "--review", self.reviewer]), 0)
        finished = run.run_dirs()[0]
        before = set(run.run_dirs())
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a, b],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        # the kill lands after a's run finished but before the scheduler settled it
        job["tasks"][0].update(state="running", run_id=finished.name, started_at=time.time())
        job.update(pid=99999999)
        job.pop("process_identity", None)
        run.save_job(job_dir, job)
        with redirect_stdout(io.StringIO()):
            rc = run.cmd_resume([job_dir.name])
        self.assertEqual(rc, 0)
        # a's result was adopted, never re-executed: only b allocated a run
        self.assertEqual(len(set(run.run_dirs()) - before), 1)
        self.assertEqual(len(self.calls("executor")), 2)
        job = self.read_job(job_dir)
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["a.md"]["state"], "passed")
        self.assertEqual(by_name["a.md"]["run_id"], finished.name)
        self.assertEqual(by_name["b.md"]["state"], "passed")

    def test_v5q_single_task_has_no_job_receipt(self):
        a = self.task("a.md", "Alpha task")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = run.main([a, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 0)
        self.assertEqual(self.job_dirs(), [])
        self.assertIn("run ", out.getvalue())

    def test_v5q_budget_fail_is_neither_resumed_nor_rerun_and_needs_you(self):
        a = self.task("a.md", "Failing task", rounds=1)
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
            rc = run.run_job_loop(self.cfg, job_dir, job, to_file=True)
        self.assertEqual(rc, 1)
        job = self.read_job(self.job_dirs()[0])
        task = job["tasks"][0]
        self.assertEqual(task["state"], "failed")
        # three rounds is the budget: its reviews failed it, so it gets no more rounds and
        # no other model, and goes back with its findings to be split or re-scoped
        self.assertNotIn("resume_attempted", task)
        self.assertNotIn("rerun_attempted", task)
        self.assertEqual(job["executor_history"], [])
        self.assertEqual(task["verdict_line"], "a.md: FAIL after 1 rounds: needs you")
        self.assertIn("flaw.py:1", task["findings"])
        log = (self.job_dirs()[0] / "log.txt").read_text()
        self.assertNotIn("resuming with", log)
        self.assertNotIn("rerunning on", log)
        # v5ay: the live seat is handed the job's failures, so the owner gets no card
        self.assertEqual(self.shaped.call_count, 0)
        self.assertIn("task(s) need you", job["handback_pending"])
        # the initial attempt and nothing after it
        executors = self.calls("executor")
        reviewers = self.calls("reviewer")
        self.assertEqual(len(executors), 1, executors)
        self.assertEqual(len(reviewers), 1, reviewers)

    def test_v5q_repo_dependency_merges_then_dependant_starts(self):
        repo = self.git_repo()
        a = self.repo_task("ra.md", "Repo alpha", repo)
        b = self.repo_task("rb.md", "Repo beta", repo, after=["ra.md"])
        with self.fake_delivery(), redirect_stdout(io.StringIO()):
            rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 0)
        job = self.read_job(self.job_dirs()[0])
        by_name = {t["name"]: t for t in job["tasks"]}
        # the merge gate is real: the dependant lands after its dependency, which it may have
        # started from before that merged (tests/test_after_from_pass.py)
        self.assertEqual(by_name["ra.md"]["state"], "merged")
        self.assertIn("PASS, merged", by_name["ra.md"]["verdict_line"])
        self.assertEqual(by_name["rb.md"]["state"], "merged")
        self.assertLessEqual(by_name["ra.md"]["finished_at"], by_name["rb.md"]["finished_at"])

    def test_v5q_two_repo_tasks_merge_in_separate_worktrees(self):
        repo = self.git_repo()
        a = self.repo_task("ra.md", "Repo alpha", repo)
        b = self.repo_task("rb.md", "Repo beta", repo)
        with self.fake_delivery(), redirect_stdout(io.StringIO()):
            rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(rc, 0)
        job = self.read_job(self.job_dirs()[0])
        self.assertEqual({t["state"] for t in job["tasks"]}, {"merged"})
        runs = {t["run_id"]: run.read_state(config.RUNS / t["run_id"]) for t in job["tasks"]}
        branches = {state["branch"] for state in runs.values()}
        worktrees = {state["worktree"] for state in runs.values()}
        self.assertEqual(len(branches), 2)
        self.assertEqual(len(worktrees), 2)

    def test_v5q_anyway_starts_beside_a_live_rival(self):
        repo = self.git_repo()
        # a live rival run in the same repo whose title shares four words
        rival_dir = run.job_allocate_run_dir("Orange orangutan orchestrates operations daily")
        (rival_dir / "task.md").write_text(
            f"---\nrepo: {repo}\nbase: main\n---\n"
            "# Orange orangutan orchestrates operations daily\n\n"
            "## Done when\n```bash\ntest -f deliverable\n```\n")
        rival_state = {"run_id": rival_dir.name,
                       "title": "Orange orangutan orchestrates operations daily",
                       "state": "running", "repo": str(repo), "started_at": time.time(),
                       "launched_session": "seat-v5q", **run.process_owner()}
        (rival_dir / "run.json").write_text(json.dumps(rival_state))
        lines = ["---", f"repo: {repo}", "base: main",
                 "---", "# Orange orangutan orchestrates operations nightly", "",
                 "## Done when", "```bash", "test -f deliverable", "```", ""]
        newcomer = str(self.root / "newcomer.md")
        Path(newcomer).write_text("\n".join(lines))
        other = self.task("other.md", "Unrelated scratch piece")
        base = ["--exec", self.executor, "--review", self.reviewer]
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "already under way.*--anyway"):
                run.main([newcomer, other, *base])
        self.assertEqual(self.job_dirs(), [])
        with self.fake_delivery(), redirect_stdout(io.StringIO()):
            rc = run.main([newcomer, other, "--anyway", *base])
        self.assertEqual(rc, 0)
        job = self.read_job(self.job_dirs()[0])
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["newcomer.md"]["state"], "merged")
        self.assertEqual(by_name["other.md"]["state"], "passed")

    def test_v5q_duplicate_basenames_are_refused(self):
        first = self.root / "one"
        second = self.root / "two"
        first.mkdir()
        second.mkdir()
        a = self.task("one/setup.md", "First setup")
        b = self.task("two/setup.md", "Second setup")
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "already called 'setup.md'"):
                run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        self.assertEqual(self.job_dirs(), [])

    def test_v5q_no_worktree_jobs_are_refused(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "--no-worktree"):
                run.main([a, b, "--no-worktree", "--exec", self.executor,
                          "--review", self.reviewer])
        self.assertEqual(self.job_dirs(), [])

    def test_v5q_single_task_parallel_is_refused(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "--parallel needs more than"):
                run.main([a, "--parallel", "2", "--exec", self.executor,
                          "--review", self.reviewer])
        self.assertEqual(self.job_dirs(), [])

    def test_v5q_mute_is_thread_local_and_leaves_nothing_behind(self):
        real_announce, real_recovery = run.announce, run.notify_recovery
        entered, release, left = threading.Event(), threading.Event(), threading.Event()
        seen = {}

        def muted():
            with run.job_muted():
                entered.set()
                self.assertTrue(release.wait(timeout=10))
                seen["depth"] = getattr(run._JOB_MUTE, "depth", 0)

        thread = threading.Thread(target=muted, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(timeout=10))
            # the other thread is muted; this one is not, and no global moved
            self.assertIs(run.announce, real_announce)
            self.assertIs(run.notify_recovery, real_recovery)
            self.assertEqual(getattr(run._JOB_MUTE, "depth", 0), 0)
            with run.job_muted():
                seen["nested"] = getattr(run._JOB_MUTE, "depth", 0)
        finally:
            release.set()
            thread.join(timeout=10)
            left.set()
        self.assertFalse(thread.is_alive())
        self.assertEqual(seen, {"depth": 1, "nested": 1})
        self.assertIs(run.announce, real_announce)
        self.assertIs(run.notify_recovery, real_recovery)

    def test_v5q_exhausted_attempt_waits_with_its_run_kept(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        task = job["tasks"][0]
        task.update(state="running", run_id="kept-run", executor=self.executor)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        # the suite paces the picker at 0; production paces it at JOB_PICKER_INTERVAL
        before = time.time()
        with redirect_stdout(io.StringIO()):
            run.job_ladder(self.cfg, job_dir, job, task, job_dir,
                           {"state": "exhausted",
                            "error": "every tier B model has a gate meter at 100% used",
                            "executor": self.executor, "reviewer": self.reviewer}, 1, log, lock)
        # never failed for lack of budget: queued again with the same run to resume
        self.assertEqual(task["state"], "queued")
        self.assertEqual(task["run_id"], "kept-run")
        self.assertTrue(task.get("budget_wait"))
        self.assertEqual(task.get("exhausted_waits"), 1)
        self.assertGreaterEqual(task.get("retry_after", 0), before)
        self.assertNotIn("resume_attempted", task)
        self.assertNotIn("rerun_attempted", task)

    def test_v5q_resume_refuses_a_live_launcher(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a, b],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        # the launcher is this very process and alive: a second scheduler must not start
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "is still running as pid"):
                run.cmd_resume([job_dir.name])
        self.assertIn(str(os.getpid()), str(self.read_job(job_dir)["pid"]))
        # ...while a dead launcher resumes like a kill
        job = self.read_job(job_dir)
        job.update(pid=99999999)
        job.pop("process_identity", None)
        run.save_job(job_dir, job)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_resume([job_dir.name]), 0)
        self.assertEqual({t["state"] for t in self.read_job(job_dir)["tasks"]}, {"passed"})

    def test_v5q_round_shortfall_exhaustion_reruns_with_no_more_rounds(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        run_dir = run.job_allocate_run_dir("Alpha task")
        shortfall = ("done-when and review are pending at round 4, but the round budget "
                     "(3) is spent; split or re-scope the task")
        state = {"run_id": run_dir.name, "title": "Alpha task", "state": "exhausted",
                 "verdict": "FAIL", "error": shortfall, "executor": self.executor,
                 "reviewer": self.reviewer, "rounds": 3, "round_summaries": [{}, {}, {}],
                 "review_pending": {"round": 4, "reason": "integration moved main"},
                 "findings": ""}
        (run_dir / "run.json").write_text(json.dumps(state))
        task = job["tasks"][0]
        task.update(state="running", run_id=run_dir.name)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        with patch.object(run, "cmd_resume", side_effect=AssertionError("given more rounds")), \
                redirect_stdout(io.StringIO()):
            run.job_ladder(self.cfg, job_dir, job, task, run_dir, dict(state), 1, log, lock)
        # the spent round budget gets no more rounds, three being the budget, but no review
        # failed it either: the one rerun on the next executor model, not a failure
        self.assertNotIn("resume_attempted", task)
        self.assertTrue(task.get("rerun_attempted"))
        self.assertEqual(task["rerun_executor"], run.job_next_executor(self.cfg, self.executor))
        self.assertNotEqual(task["run_id"], run_dir.name)
        self.assertEqual(task["state"], "passed")

    def test_v5q_shortfall_on_spent_meters_waits_for_budget(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        task = job["tasks"][0]
        task.update(state="running", run_id="kept-run", executor=self.executor)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        # a pending review parked on spent meters: the message decides first, so the
        # run waits for budget even with `review_pending` still set
        parked = ("every tier B model has a gate meter at 100% used; "
                  "done-when and review are pending")
        with redirect_stdout(io.StringIO()):
            run.job_ladder(self.cfg, job_dir, job, task, job_dir,
                           {"state": "exhausted", "error": parked,
                            "executor": self.executor, "reviewer": self.reviewer,
                            "review_pending": {"round": 4}, "round_summaries": [{}, {}]},
                           1, log, lock)
        self.assertEqual(task["state"], "queued")
        self.assertNotIn("resume_attempted", task)
        self.assertNotIn("rerun_attempted", task)
        self.assertEqual(task.get("exhausted_waits"), 1)

    def test_v5q_transport_cap_counts_one_outage_not_history(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        task = job["tasks"][0]
        task.update(state="running", run_id="kept-run", executor=self.executor)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        outage = (f"reviewer {self.reviewer} died on API/transport errors 3 times and no "
                  "eligible reviewer is left on another provider; waiting for review")
        with redirect_stdout(io.StringIO()):
            for _ in range(3):
                run.job_ladder(self.cfg, job_dir, job, task, job_dir,
                               {"state": "exhausted", "error": outage,
                                "executor": self.executor, "reviewer": self.reviewer,
                                "round_summaries": [{}]}, 1, log, lock)
                self.assertEqual(task["state"], "queued")
            self.assertEqual(task.get("transport_waits"), 3)
            # the next attempt got past the outage (more rounds done) before dying again:
            # a new episode starts at one, not at four
            run.job_ladder(self.cfg, job_dir, job, task, job_dir,
                           {"state": "exhausted", "error": outage,
                            "executor": self.executor, "reviewer": self.reviewer,
                            "round_summaries": [{}, {}, {}]}, 1, log, lock)
        self.assertEqual(task["state"], "queued")
        self.assertEqual(task.get("transport_waits"), 1)

    def test_v5q_transport_outage_waits_then_needs_the_owner(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        task = job["tasks"][0]
        task.update(state="running", run_id="kept-run", executor=self.executor)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        outage = (f"reviewer {self.reviewer} died on API/transport errors 3 times and no "
                  "eligible reviewer is left on another provider; waiting for review")
        attempt = {"state": "exhausted", "error": outage, "executor": self.executor,
                   "reviewer": self.reviewer}
        with redirect_stdout(io.StringIO()):
            for _ in range(run.JOB_TRANSPORT_WAITS):
                run.job_ladder(self.cfg, job_dir, job, task, job_dir, dict(attempt), 1,
                               log, lock)
                self.assertEqual(task["state"], "queued")
            run.job_ladder(self.cfg, job_dir, job, task, job_dir, dict(attempt), 1,
                           log, lock)
        # paced waits while the outage might end, then a card instead of silent burning
        self.assertEqual(task.get("transport_waits"), run.JOB_TRANSPORT_WAITS + 1)
        self.assertEqual(task["state"], "failed")
        self.assertIn("needs you", task["verdict_line"])
        self.assertIn("transport", task["findings"])

    def test_v5q_stopped_tool_exhaustion_needs_the_owner(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        task = job["tasks"][0]
        task.update(state="running", run_id="kept-run", executor=self.executor)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        with redirect_stdout(io.StringIO()):
            run.job_ladder(self.cfg, job_dir, job, task, job_dir,
                           {"state": "exhausted", "error": "gh timed out",
                            "executor": self.executor, "reviewer": self.reviewer}, 1, log, lock)
        # a stopped tool never comes back on its own: failed with the reason kept
        self.assertEqual(task["state"], "failed")
        self.assertIn("needs you", task["verdict_line"])
        self.assertEqual(task["findings"], "gh timed out")

    def test_v5q_merge_failed_is_finished_with_merge_not_rerun(self):
        a = self.task("a.md", "Alpha task")
        with redirect_stdout(io.StringIO()):
            job_dir, job = run.job_create(self.cfg, [a],
                                          {"--rounds": None, "--exec": self.executor,
                                           "--review": self.reviewer, "--no-merge": False,
                                           "--no-worktree": False}, None)
        run_dir = run.job_allocate_run_dir("Alpha task")
        exec_provider = config.model(self.cfg, self.executor)["provider"]
        review_provider = config.model(self.cfg, self.reviewer)["provider"]
        state = {"run_id": run_dir.name, "title": "Alpha task", "state": "pass", "verdict": "PASS",
                 "executor": self.executor, "reviewer": self.reviewer, "merged": False,
                 "merge_failed": True, "merge_note": "push rejected", "round_summaries": [{}],
                 "rounds": 1, "findings": "",
                 "review": {"executor": self.executor, "executor_provider": exec_provider,
                            "reviewer": self.reviewer, "reviewer_provider": review_provider,
                            "returncode": 0, "verdict": "PASS", "done_when": True,
                            "head_sha": "abc", "tree_sha": "def"}}
        (run_dir / "run.json").write_text(json.dumps(state))

        def delivered(argv):
            run_id = argv[0]
            current = json.loads((config.RUNS / run_id / "run.json").read_text())
            current.update(merged=True, merge_failed=False, merge_note=None,
                           pr="https://example.invalid/pr/9")
            (config.RUNS / run_id / "run.json").write_text(json.dumps(current))
            return 0

        task = job["tasks"][0]
        task.update(state="running", run_id=run_dir.name)
        log = run.job_logger(job_dir, False)
        lock = threading.Lock()
        with patch.object(run, "cmd_merge", side_effect=delivered), \
                redirect_stdout(io.StringIO()):
            run.job_ladder(self.cfg, job_dir, job, task, run_dir, dict(state), 1, log, lock)
        self.assertEqual(task["state"], "merged")
        self.assertNotIn("rerun_attempted", task)
        self.assertNotIn("resume_attempted", task)

    def test_v5q_status_job_json_contract(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([self.job_dirs()[0].name, "--json"]), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["job_id"], self.job_dirs()[0].name)
        self.assertEqual([t["state"] for t in payload["tasks"]], ["passed", "passed"])
        self.assertIn("paths", payload)

    def test_v5q_scheduler_keeps_starting_while_a_retry_runs(self):
        # a's reviews pass but its done-when never does, so at its budget the ladder
        # reruns it once on the next executor model: that rerun is the retry held here
        a = self.task("a.md", "Alpha task", rounds=1)
        Path(a).write_text(Path(a).read_text().replace("test -f deliverable", "test -f missing"))
        b = self.task("b.md", "Beta task")
        real_next = run.job_next_executor
        entered, release = threading.Event(), threading.Event()

        def slow_next(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=30))
            return real_next(*args, **kwargs)

        result = {}

        def launch():
            with redirect_stdout(io.StringIO()):
                result["rc"] = run.main([a, b, "--exec", self.executor,
                                         "--review", self.reviewer])

        with patch.object(run, "job_next_executor", side_effect=slow_next):
            thread = threading.Thread(target=launch, daemon=True)
            thread.start()
            try:
                # the ladder's rerun is parked inside the worker; the scheduler must
                # still start and finish the queued task meanwhile
                self.assertTrue(entered.wait(timeout=30))
                self.wait_for(lambda: self.job_dirs() and any(
                    t["state"] == "passed" for t in
                    self.read_job(self.job_dirs()[0])["tasks"]), seconds=30)
                job = self.read_job(self.job_dirs()[0])
                by_name = {t["name"]: t for t in job["tasks"]}
                self.assertEqual(by_name["b.md"]["state"], "passed")
                self.assertEqual(by_name["a.md"]["state"], "running")
            finally:
                release.set()
                thread.join(timeout=90)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["rc"], 1)
        job = self.read_job(self.job_dirs()[0])
        by_name = {t["name"]: t for t in job["tasks"]}
        self.assertEqual(by_name["a.md"]["state"], "failed")
        self.assertTrue(by_name["a.md"]["rerun_attempted"])
        self.assertEqual(by_name["b.md"]["state"], "passed")

    def test_v5q_bg_detaches_and_the_child_adopts_the_receipt(self):
        import subprocess as stdlib_subprocess
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        spawned = {}

        class FakeChild:
            # the child's own live pid: the old code refused itself as "still running"
            pid = os.getpid()

            def poll(self):
                return None          # ... and a launched child is a running one

        def fake_popen(argv, **kwargs):
            spawned["argv"] = argv
            spawned["env"] = kwargs.get("env")
            spawned["stdout"] = kwargs.get("stdout")
            # a child placed in the slice leaves the mark its `sh` writes before it becomes
            # the work, and that mark is what the launcher records as the pid
            marker = next((arg for arg in argv if arg.endswith(".launched")), None)
            if marker:
                Path(marker).write_text(str(FakeChild.pid))
            return FakeChild()

        with patch.object(stdlib_subprocess, "Popen", side_effect=fake_popen):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = run.main([a, b, "--exec", self.executor, "--review", self.reviewer,
                               "--bg"])
        self.assertEqual(rc, 0)
        job_dir = self.job_dirs()[0]
        job = self.read_job(job_dir)
        # the detach contract: the child resumes this job, owns its stdout, adopts the pid
        self.assertEqual(spawned["argv"][-3:], ["run", "resume", job_dir.name])
        self.assertEqual(spawned["env"][config.JOB_DIR_ENV], str(job_dir))
        self.assertEqual(spawned["stdout"].name, str(job_dir / "log.txt"))
        self.assertEqual(job["pid"], os.getpid())
        self.assertIn(job_dir.name, out.getvalue())
        self.assertEqual(run.run_dirs(), [])
        self.assertEqual([t["state"] for t in job["tasks"]], ["queued", "queued"])
        # the child, whose stdout is the job log, records nothing twice and adopts the pid
        with patch.dict(os.environ, {config.JOB_DIR_ENV: str(job_dir)}):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = run.cmd_resume([job_dir.name])
        self.assertEqual(rc, 0)
        job = self.read_job(job_dir)
        self.assertEqual({t["state"] for t in job["tasks"]}, {"passed"})
        self.assertEqual(job["pid"], os.getpid())
        self.assertIn("start:", out.getvalue())
        self.assertIn("exit", out.getvalue())

    def test_v5q_gc_collects_only_old_finished_jobs(self):
        a = self.task("a.md", "Alpha task")
        b = self.task("b.md", "Beta task")
        with redirect_stdout(io.StringIO()):
            run.main([a, b, "--exec", self.executor, "--review", self.reviewer])
        job_dir = self.job_dirs()[0]
        job = self.read_job(job_dir)
        job["finished_at"] = time.time() - run.GC_AGE - 1
        # the launcher is long gone: only then is an old finished job collectible
        job.update(pid=99999999)
        job.pop("process_identity", None)
        (job_dir / "job.json").write_text(json.dumps(job))
        kinds = [item["kind"] for item in run.gc_plan()]
        self.assertIn("finished-job", kinds)
        removed = run.gc(lambda _: None)
        self.assertIn(str(job_dir), removed)
        self.assertFalse(job_dir.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
