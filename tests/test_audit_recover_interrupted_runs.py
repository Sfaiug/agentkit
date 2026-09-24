"""Finding 5: interrupted work stays visible and numerically recoverable; entirely offline."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, terminal, watch


class InterruptedRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".recover-runs-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
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
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AK_RUN_LOG": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets),
            "TMUX": "", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1",
            config.ADAPTER_DIR_ENV: str(adapters), "RECOVERY_FIXTURE": str(self.root),
            "AK_SLOT_POLL": ".05",
            "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                            "load": 1, "cpus": 8,
                                            "unit_memory_current_mb": 100,
                                            "unit_memory_high_mb": 1000})}))
        # No real tmux server, model harness, GitHub or Discord can be reached. Even this
        # tmux recorder insists on the permitted socket name and a private socket directory.
        self.script(self.bin / "tmux", '''import os, sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
assert os.environ["TMUX_TMPDIR"].startswith(os.environ["RECOVERY_FIXTURE"])
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord call")))
        self.notified = self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.seats = []
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: self.seats))
        # v5ay: an unfinished run under a live seat is handed back to it, at its own prompt
        self.typed = self.stack.enter_context(
            patch.object(watch, "type_at_prompt", return_value=True))
        self.stack.enter_context(patch.object(terminal, "width", return_value=40))
        config.ensure_dirs()
        self.cfg = config.load()
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        # The repository's catalogue supplies all models and efforts, including in the child.
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", '''import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["RECOVERY_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls").open("a") as calls:
    calls.write(role + "\\n")
if role == "executor":
    deadline = time.monotonic() + 15
    while (root / "hold").exists():
        assert time.monotonic() < deadline, "fixture was not released"
        time.sleep(.02)
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
text = "VERDICT: PASS\\n## Findings\\n- none" if role == "reviewer" else "## Summary\\nFixture work."
(out / "final.md").write_text(text)
(out / "session_id").write_text("fixture-" + role)
if role == "reviewer" and (root / "fail-review").exists():
    sys.exit(17)
''')
        self.now = time.time()
        self.task = "---\nrepo: none\nrounds: 1\n---\n# Recovery fixture\n\n## Done when\n```bash\ntest -f deliverable\n```\n"
        self.children = []
        self.addCleanup(self.finish_children)

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def finish_children(self):
        (self.root / "hold").unlink(missing_ok=True)
        for child in self.children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)

    def receipt(self, name, status="running", **extra):
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "task.md").write_text(self.task)
        (directory / "log.txt").touch()
        state = {"run_id": name, "title": name, "state": status, "verdict": None,
                 "pid": 99999999, "started_at": self.now - 2 * 86400, "finished_at": None,
                 "launched_session": "owner", "reported": False, **extra}
        run.save_state(directory, state)
        return directory

    def screen(self, *answers):
        out = io.StringIO()
        with redirect_stdout(out):
            run.cmd_status([])
        return out.getvalue()

    def scratch_receipt(self, name):
        workspace = config.WORK / name
        workspace.mkdir()
        (workspace / "keep").write_text("existing deliverable")
        return self.receipt(name, "interrupted", launched_session=None, scratch=True,
                            worktree=str(workspace), rounds=1, round_summaries=[], findings="",
                            base=None, base_sha=None, branch=None, repo=None,
                            executor=self.executor, reviewer=self.reviewer, no_merge=True)

    def wait_for(self, predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "fixture child did not reach expected state")
            time.sleep(.02)

    def track_background(self):
        original = run.subprocess.Popen
        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            return child
        return patch.object(run.subprocess, "Popen", side_effect=spawn)

    def test_dead_running_and_abandoned_queued_stay_visible_after_a_day(self):
        directories = [self.receipt("dead"), self.receipt("queued", "queued")]
        with patch.object(run.time, "time", return_value=self.now):
            first = self.screen("")
        for directory in directories:
            state = run.read_state(directory)
            self.assertEqual(state["state"], "interrupted")
            self.assertIsNone(state["finished_at"])
            self.assertIsNone(state["verdict"])
            self.assertEqual(state["interrupted_at"], self.now)
            self.assertIn(directory.name, first)
        self.assertIn("needs you", first)
        with patch.object(run.time, "time", return_value=self.now + 86401):
            second = self.screen("")
            self.assertEqual({path for path, _ in menu.run_records()}, set(directories))
            self.assertTrue(all(run.needs_recovery(record) for _, record in menu.run_records()))
        self.assertIn("dead", second)
        self.assertEqual(self.notified.call_count, 2)
        self.assertEqual(run.read_state(directories[0])["interrupted_at"], self.now)

    def test_pid_reuse_and_boot_change_are_interrupted_but_active_identity_is_kept(self):
        owner = run.process_owner()
        self.assertIsNotNone(owner["process_identity"])
        active = self.receipt("active", **owner)
        queued = self.receipt("active-queue", "queued", **owner)
        for key, value in (("ticks", -1), ("boot", "earlier-boot")):
            reused = copy.deepcopy(owner)
            reused["process_identity"][key] = value
            directory = self.receipt(f"reused-{key}", **reused)
            self.assertEqual(run.reap(directory, {})["state"], "interrupted")
        for directory in (active, queued):
            before = (directory / "run.json").read_bytes()
            self.assertTrue(run.process_active(run.reap(directory, {})))
            self.assertEqual((directory / "run.json").read_bytes(), before)
            with self.assertRaisesRegex(config.Error, "still running"):
                run.cmd_resume([directory.name, "--bg"])
        self.assertEqual(self.notified.call_count, 2)

    def test_legacy_live_run_identity_and_stale_menu_snapshot_do_not_interrupt_work(self):
        source = self.root / "task.md"
        source.write_text(self.task)
        (self.root / "hold").touch()
        with self.track_background(), redirect_stdout(io.StringIO()):
            self.assertEqual(run.main([str(source), "--exec", self.executor,
                                       "--review", self.reviewer, "--bg"]), 0)
        directory = run.run_dirs()[0]
        self.wait_for(lambda: (self.root / "calls").exists())
        active = run.read_state(directory)
        self.assertTrue(run.process_active(active))
        active.pop("process_identity")
        run.save_state(directory, active)
        self.assertTrue(run.process_active(active), active)
        stale = {**active, "pid": 99999999}
        self.assertEqual(run.reap(directory, stale)["state"], "running")
        (self.root / "hold").unlink()
        self.finish_children()
        self.assertEqual(run.read_state(directory)["state"], "pass")
        self.notified.assert_not_called()

    def test_legacy_unrelated_live_pid_and_recent_abandoned_launcher(self):
        directory = self.receipt("legacy-reused", pid=os.getpid())
        self.assertEqual(run.reap(directory, {})["state"], "interrupted")
        queued = self.receipt("handoff", "queued", started_at=self.now)
        with patch.object(run.time, "time", return_value=self.now):
            self.assertEqual(run.reap(queued, {})["state"], "queued")
        with patch.object(run.time, "time", return_value=self.now + run.QUEUED_GRACE + 1):
            self.assertEqual(run.reap(queued, {})["state"], "interrupted")

    def test_zombie_and_parent_death_during_handoff(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        self.children.append(child)
        self.wait_for(lambda: Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z")
        directory = self.receipt("zombie", pid=child.pid)
        self.assertTrue(run.alive(child.pid))
        self.assertEqual(run.reap(directory, {})["state"], "interrupted")
        queued = self.receipt("pending-handoff", "queued", launch_pending=True,
                              process_identity={"boot": "dead", "ticks": 1}, queued_at=self.now)
        with patch.object(run.time, "time", return_value=self.now):
            self.assertEqual(run.reap(queued, {})["state"], "queued")
        with patch.object(run.time, "time", return_value=self.now + run.QUEUED_GRACE + 1):
            self.assertEqual(run.reap(queued, {})["state"], "interrupted")
        # A delayed detached child must not turn an already reaped receipt into a new run.
        with patch.dict(os.environ, {config.RUN_DIR_ENV: str(queued)}):
            with self.assertRaisesRegex(config.Error, "launch was interrupted"):
                run.main([str(queued / "task.md")])
        self.assertEqual(set(run.run_dirs()), {directory, queued})

    def test_existing_interruption_is_notified_once_under_concurrent_reaping(self):
        self.seats = [{"name": "owner"}]
        directory = self.receipt("old-interruption", "interrupted", reported=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            states = list(pool.map(lambda _: run.reap(directory, {}), range(8)))
        self.typed.assert_called_once()
        self.notified.assert_not_called()
        self.assertIn("Decide the next step.", self.typed.call_args.args[1])
        self.assertEqual(len({state["interrupted_at"] for state in states}), 1)
        self.assertIsNone(states[0]["finished_at"])
        self.assertEqual(states[0]["recovery_notified"], "orchestrator")
        self.screen("")
        self.assertFalse(run.read_state(directory).get("recovery_acknowledged_at"))
        self.assertIn(directory, dict(menu.run_records()))

    def test_unavailable_or_failed_orchestrator_uses_needs_once_and_no_seat_stays_local(self):
        for name, seat in (("gone", None), ("exited", {"name": "owner", "exited": True})):
            self.seats = [seat] if seat else []
            self.typed.return_value = False
            directory = self.receipt(name)
            for _ in range(3):
                run.reap(directory, {})
            self.assertEqual(run.read_state(directory)["recovery_notified"], "needs")
        self.assertEqual(self.notified.call_count, 2)
        for call in self.notified.call_args_list:
            self.assertEqual(call.args[0], "needs")
            self.assertEqual(call.kwargs["session"], "owner")
            self.assertIn("ak run resume", call.args[1])
        # v5ay: a seat that is there is never a reason to ask the owner instead -- a line it
        # could not be told yet waits on its record for the tick's next quiet prompt
        self.seats = [{"name": "owner"}]
        self.typed.return_value = False
        busy = self.receipt("failed-send")
        for _ in range(3):
            run.reap(busy, {})
        self.assertTrue(run.read_state(busy)["handback_pending"])
        self.assertNotIn("recovery_notified", run.read_state(busy))
        self.assertEqual(self.notified.call_count, 2)
        local = self.receipt("local", launched_session=None)
        run.reap(local, {})
        self.assertEqual(self.notified.call_count, 2)

    def test_numeric_acknowledgment_hides_only_selected_recovery_and_preserves_deliverables(self):
        directory = self.receipt("ack", "interrupted", scratch=True,
                                 worktree=str(config.WORK / "ack"))
        workspace = config.WORK / "ack"
        workspace.mkdir()
        (workspace / "deliverable").write_text("keep me")
        self.screen("")  # drawing the list is not acknowledgment
        self.assertIn(directory, dict(menu.run_records()))
        run.acknowledge(directory)
        state = run.read_state(directory)
        self.assertTrue(state["recovery_acknowledged_at"])
        self.assertEqual(state["state"], "interrupted")
        self.assertIsNone(state["finished_at"])
        self.assertIn(directory, dict(menu.run_records()))
        other = self.receipt("still-pending", "interrupted")
        self.assertEqual(set(dict(menu.run_records())), {directory, other})
        with patch.object(run, "disk_pressure", return_value=(99, 85)):
            run.gc(lambda _: None)
        self.assertEqual((workspace / "deliverable").read_text(), "keep me")
        self.assertTrue((directory / "run.json").exists())

    def test_numeric_resume_of_abandoned_launch_uses_same_run_and_fake_adapters(self):
        directory = self.receipt("resume-queue", "queued", launched_session=None,
                                 launch_opts={"--exec": self.executor, "--review": self.reviewer,
                                              "--no-merge": True})
        with self.track_background():
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run.cmd_resume([directory.name, "--bg"]), 0)
        self.finish_children()
        state = run.read_state(directory)
        self.assertEqual(state["state"], "pass", (directory / "log.txt").read_text())
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertTrue(state["no_merge"])
        self.assertFalse(run.needs_recovery(state))
        self.assertEqual(run.run_dirs(), [directory])
        self.assertEqual((self.root / "calls").read_text().splitlines(), ["executor", "reviewer"])
        # the delivered workspace stays with its run: the resumed work is there,
        # and result.md links it
        self.assertEqual((Path(state["worktree"]) / "deliverable").read_text(), "fixture work\n")
        self.assertIn("- [deliverable](", (directory / "result.md").read_text())
        self.assertLessEqual(state["interrupted_at"], state["finished_at"])

    def test_numeric_resume_reuses_scratch_workspace_and_active_resume_cannot_be_started_twice(self):
        directory = self.scratch_receipt("scratch-resume")
        (self.root / "hold").touch()
        with self.track_background():
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run.cmd_resume([directory.name, "--bg"]), 0)
        self.wait_for(lambda: (self.root / "calls").exists())
        state = run.read_state(directory)
        self.assertEqual(state["state"], "running")
        self.assertTrue(run.process_active(state))
        with self.assertRaisesRegex(config.Error, "still running"):
            run.cmd_resume([directory.name, "--bg"])
        self.finish_children()
        state = run.read_state(directory)
        self.assertEqual(state["state"], "pass", (directory / "log.txt").read_text())
        self.assertEqual(Path(state["worktree"]), config.WORK / "scratch-resume")
        # the delivered workspace stays with its run: the resumed work is there,
        # and result.md links it
        self.assertEqual((Path(state["worktree"]) / "keep").read_text(), "existing deliverable")
        self.assertIn("- [keep](", (directory / "result.md").read_text())

    def test_failed_detached_attempt_retains_the_recovery_entry_after_a_day(self):
        directory = self.scratch_receipt("failed-attempt")
        (self.root / "fail-review").touch()
        with self.track_background():
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run.cmd_resume([directory.name, "--bg"]), 0)
        self.finish_children()
        state = run.read_state(directory)
        self.assertEqual(state["state"], "fail", (directory / "log.txt").read_text())
        self.assertTrue(run.needs_recovery(state))
        with patch.object(run.time, "time", return_value=self.now + 86401):
            self.assertIn(directory, dict(menu.run_records()))
        self.assertEqual((Path(state["worktree"]) / "keep").read_text(), "existing deliverable")

    def test_failed_numeric_resume_keeps_recovery_entry_and_does_not_repeat_notification(self):
        directory = self.receipt("bad-resume", "interrupted", scratch=True, rounds=1,
                                 worktree=str(config.WORK / "gone"))
        run.reap(directory, {})
        self.notified.assert_called_once()
        with self.assertRaises(config.Error):
            with redirect_stdout(io.StringIO()):
                run.cmd_resume([directory.name])
        self.assertIn(directory, dict(menu.run_records()))
        self.notified.assert_called_once()
        self.assertEqual(run.read_state(directory)["state"], "interrupted")

    def test_failed_background_launch_and_failed_attempt_stay_recoverable(self):
        directory = self.receipt("spawn-failure", "interrupted", launched_session=None)
        with patch.object(run.subprocess, "Popen", side_effect=OSError("fixture launch failure")):
            with self.assertRaisesRegex(config.Error, "fixture launch failure"):
                with redirect_stdout(io.StringIO()):
                    run.cmd_resume([directory.name, "--bg"])
        self.assertIn(directory, dict(menu.run_records()))
        self.assertIsNone(run.read_state(directory)["finished_at"])
        with patch.object(run, "loop", side_effect=config.Error("fixture resume failure")), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(config.Error, "fixture resume failure"):
                run.cmd_resume([directory.name])
        with patch.object(run.time, "time", return_value=self.now + 86401):
            self.assertIn(directory, dict(menu.run_records()))
            self.assertIn("needs you", self.screen(""))

    def test_watcher_reaps_without_github_and_does_not_automatically_retry_interruption(self):
        # A dead loop is no longer left interrupted for a person: the same tick resumes
        # it and sends no recovery card. The model is not called; the resume is the loop's.
        workspace = config.WORK / "unattended"
        workspace.mkdir(parents=True)         # a running run always has one to go back to
        directory = self.receipt("unattended", worktree=str(workspace), scratch=True)
        resumed = []
        with patch.object(watch, "health"), patch.object(watch, "gh_json", return_value=(None, "offline")), \
                patch.object(run, "schedule_gc"), \
                patch.object(watch, "launch_resume",
                             side_effect=lambda run_id, log=lambda _: None: resumed.append(run_id) or True), \
                redirect_stdout(io.StringIO()) as said:
            self.assertEqual(watch.main([]), 0)
            self.assertIn("PR checks skipped", said.getvalue())
            self.assertIn(f"resumed {directory.name}: loop died", said.getvalue())
        state = run.read_state(directory)
        self.assertEqual(state["state"], "running")
        self.assertEqual(resumed, [directory.name])
        self.assertIn("loop process", state["deaths"][0]["reason"])
        self.notified.assert_not_called()
        self.assertEqual(watch.settled({"run": directory.name}), "pending")
        self.assertFalse((self.root / "calls").exists())

    def dead_job(self, name, seat="owner", tasks=None, **fields):
        """A job receipt whose launcher is gone: a pid no process has, and no identity."""
        job_dir = config.JOBS / name
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": name, "seat": seat, "started_at": self.now, "finished_at": None,
               "parallel": None, "executor_history": [], "pid": 99999999, "cwd": str(self.root),
               "opts": {"--exec": self.executor, "--review": self.reviewer, "--anyway": True},
               "tasks": tasks or [{"name": "a.md", "title": "A", "after": [], "state": "queued",
                                   "run_id": None}],
               **fields}
        run.save_job(job_dir, job)
        return job_dir

    def placements(self):
        """A fake placement: what would have started, and the pid this process lends it."""
        started = []

        def placed(argv, unit, env, output, **kwargs):
            kwargs["placement"].update(scope=unit)
            started.append({"argv": argv, "unit": unit, "env": env, **kwargs})
            return os.getpid()

        return started, patch.object(orch, "start_in_slice", side_effect=placed)

    def test_the_tick_relaunches_a_dead_job_and_its_waiting_task_starts_after_the_running_one(self):
        # the scopes the fake placement names are nobody's: no real unit is ever stopped
        self.stack.enter_context(patch.object(orch, "stop_scope", return_value=True))
        config.save_session(self.cfg, "owner", self.executor, [self.executor, self.reviewer])
        launched = self.root / "launched-from"
        launched.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        a, b = self.root / "a.md", self.root / "b.md"
        a.write_text(self.task)
        b.write_text(self.task.replace("rounds: 1\n", "rounds: 1\nafter: a.md\n"))
        # a finished before its launcher died: the relaunch adopts that run, never redoes it
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main([str(a), "--exec", self.executor,
                                       "--review", self.reviewer]), 0)
        finished = run.run_dirs()[0]
        tasks = [{"name": "a.md", "title": "A", "after": [], "state": "running",
                  "run_id": finished.name, "started_at": self.now, "task_file": str(a)},
                 {"name": "b.md", "title": "B", "after": ["a.md"], "state": "waiting",
                  "run_id": None, "task_file": str(b)}]
        job_dir = self.dead_job("20260923-2000-recover", tasks=tasks, cwd=str(launched))
        out = io.StringIO()
        with redirect_stdout(out):
            run.cmd_status([job_dir.name])
        self.assertIn("launcher gone; the next tick relaunches it · session owner exists",
                      out.getvalue())
        said = []
        started, placement = self.placements()
        with placement:
            watch.resume_dead_jobs(log=said.append)
        # `ak run resume <job>` in the job's own scope, for the job's own seat
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["argv"][2:], ["run", "resume", job_dir.name])
        self.assertEqual(started[0]["unit"], f"agentkit-job-{job_dir.name}")
        env = started[0]["env"]
        self.assertEqual(env[config.SESSION_ENV], "owner")
        self.assertEqual(env[config.JOB_DIR_ENV], str(job_dir))
        self.assertEqual(said, [f"relaunched job {job_dir.name}: launcher gone; session owner "
                                "exists; alive under 24h ago; no task stopped"])
        self.assertIn(said[0], (job_dir / "log.txt").read_text())
        job = run.read_job(job_dir)
        self.assertEqual(job["pid"], os.getpid())
        self.assertEqual(len(job["relaunches"]), 1)
        # the child it started, run here: it adopts a's result and starts b behind it, in the
        # directory the job was launched from, where a task naming no repo finds its checkout
        looked, task_repo = [], run.task_repo
        with patch.dict(os.environ, {key: env[key] for key in (config.JOB_DIR_ENV,
                                                               config.SESSION_ENV)}), \
                patch.object(run, "task_repo", side_effect=lambda meta, path: (
                    looked.append(Path.cwd()) or task_repo(meta, path))), \
                patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}), \
                patch.object(run, "JOB_TICK", 0.05), \
                patch.object(run, "JOB_PICKER_INTERVAL", 0), \
                redirect_stdout(io.StringIO()):
            for key in ("AGENTKIT_RUN", "AK_PARENT_RUN"):
                os.environ.pop(key, None)
            self.assertEqual(run.cmd_resume([job_dir.name]), 0)
        job = run.read_job(job_dir)
        by_name = {task["name"]: task for task in job["tasks"]}
        self.assertEqual(by_name["a.md"]["state"], "passed")
        self.assertEqual(by_name["a.md"]["run_id"], finished.name)
        self.assertEqual(by_name["b.md"]["state"], "passed")
        self.assertTrue(looked)
        self.assertEqual({path.resolve() for path in looked}, {launched.resolve()})
        self.assertEqual(run.read_state(config.RUNS / by_name["b.md"]["run_id"])
                         ["launched_session"], "owner")
        self.assertEqual((self.root / "calls").read_text().splitlines(),
                         ["executor", "reviewer", "executor", "reviewer"])
        self.assertEqual(self.notified.call_args.args[0], "done")

    def test_a_dead_job_outside_the_ticks_bounds_stays_for_a_person(self):
        config.save_session(self.cfg, "owner", self.executor, [self.executor, self.reviewer])
        config.save_session(self.cfg, "closed", self.executor, [self.executor, self.reviewer])
        watch.seat_write("closed", stopped_at=self.now, closed_by_owner=True)
        # renamed since: the job names the old seat, whose file now only points on
        config.session_path("renamed-away").write_text(json.dumps({"renamed": "closed"}))

        def running(run_dir):
            return [{"name": "a.md", "title": "A", "after": [], "state": "running",
                     "run_id": run_dir.name},
                    {"name": "b.md", "title": "B", "after": [], "state": "queued",
                     "run_id": None}]

        refused = [self.dead_job("by-hand", seat=None),
                   self.dead_job("session-gone", seat="gone"),
                   self.dead_job("owner-closed", seat="closed"),
                   self.dead_job("owner-closed-after-a-rename", seat="renamed-away"),
                   self.dead_job("task-stopped", tasks=[
                       {"name": "a.md", "title": "A", "after": [], "state": "stopped",
                        "run_id": None},
                       {"name": "b.md", "title": "B", "after": [], "state": "queued",
                        "run_id": None}]),
                   self.dead_job("run-stopped", tasks=running(
                       self.receipt("stopped-task-run", "stopped"))),
                   self.dead_job("a-day-old"),
                   # where a task naming no repo would find its checkout is not known, or gone
                   self.dead_job("launch-dir-unknown", cwd=None),
                   self.dead_job("launch-dir-gone", cwd=str(self.root / "gone")),
                   # relaunched twice in the hour before it died again: the third death parks
                   self.dead_job("third-death", relaunches=[self.now - 1200, self.now - 600])]
        # a run already handed back, carded or acknowledged is a person's, as a lone one is
        for key, value in (("handed_back", self.now), ("recovery_notified", "orchestrator"),
                           ("recovery_acknowledged_at", self.now)):
            refused.append(self.dead_job(f"told-{key}", tasks=running(
                self.receipt(f"told-{key}-run", "interrupted", **{key: value}))))
        # a launcher quiet for a day is gone for a day, whatever wrote its task's run since:
        # the tick's own dead-loop pass rewrites that receipt and log before this pass reads
        refused.append(self.dead_job("resumed-since", tasks=running(
            self.receipt("resumed-since-run"))))
        for job_dir in (config.JOBS / "a-day-old", config.JOBS / "resumed-since"):
            for path in (job_dir / "job.json", job_dir / "log.txt"):
                os.utime(path, (self.now - 86401, self.now - 86401))
        # a run handed back after its ending is every task's hand-back: the job adopts it
        ended = self.dead_job("handed-back-after-its-ending", tasks=running(
            self.receipt("ended-run", "pass", verdict="PASS", finished_at=self.now,
                         handed_back=self.now)))
        # never looked at: a launcher alive, and a job already finished
        self.dead_job("alive", **run.process_owner())
        self.dead_job("finished", finished_at=self.now)
        # relaunches more than an hour before its last sign of life count for nothing
        lived = self.dead_job("lived-past-its-relaunches",
                              relaunches=[self.now - 9000, self.now - 7200])
        said = []
        started, placement = self.placements()
        with placement:
            watch.resume_dead_jobs(log=said.append)
        self.assertEqual([start["argv"][-1] for start in started], [ended.name, lived.name])
        for job_dir in refused:
            self.assertEqual(run.read_job(job_dir)["pid"], 99999999, job_dir.name)
            out = io.StringIO()
            with redirect_stdout(out):
                run.cmd_status([job_dir.name])
            self.assertIn(f"launcher gone; ak run resume {job_dir.name} to continue",
                          out.getvalue())
        self.assertEqual(len(said), 2)

    def test_a_launcher_keeps_its_directory_fresh_while_its_tasks_run(self):
        # however long a task runs without the receipt changing, the launcher's directory says
        # it was alive: its heartbeat is what the tick reads once the launcher is gone
        job_dir = self.dead_job("20260923-2000-heartbeat", tasks=[
            {"name": "a.md", "title": "A", "after": [], "state": "running",
             "run_id": "20260923-2000-long-task", "retry_after": self.now + 3600}])
        os.utime(job_dir / "job.json", (self.now - 2 * 86400, self.now - 2 * 86400))

        class Stop(Exception):
            pass

        with patch.object(run, "save_job"), \
                patch.object(run.time, "sleep", side_effect=Stop), \
                redirect_stdout(io.StringIO()), self.assertRaises(Stop):
            run.run_job_loop(self.cfg, job_dir, run.read_job(job_dir), to_file=False)
        # fresh, not two days old: the file clock may trail `time.time()` by a tick
        self.assertGreater((job_dir / "job.json").stat().st_mtime, self.now - 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
