"""Detached run placement and cleanup; all systemd calls are fakes."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import warnings
from unittest.mock import MagicMock, patch

from test_v4n import REPO
import sys
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, watch


class RunScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".run-scope-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()

    def run_dir(self, name="20260922-0900-scope"):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        run.save_state(directory, {"run_id": name, "state": "queued",
                                   "launched_session": "old-session"})
        return directory

    def scoped_job(self):
        """A job whose process sits in its own scope: the cgroup file says so, nothing else."""
        cgroup = self.root / "cgroup"
        cgroup.write_text("0::/user.slice/user-1000.slice/user@1000.service/agentkit-test.slice/"
                          "agentkit-test-runs.slice/agentkit-job-20260923-2000-job.scope\n")
        self.stack.enter_context(patch.object(orch, "OWN_CGROUP", cgroup))
        self.stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0",
                                                         "AK_MAX_RUNS": "0"}))
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", config.RUN_DIR_ENV,
                    config.JOB_DIR_ENV):
            os.environ.pop(key, None)
        return {"job_id": "20260923-2000-job", "scope": "agentkit-job-20260923-2000-job",
                "seat": None, "opts": {}, "tasks": []}

    def fake_children(self, endings=None):
        """A fake process table behind a fake placement: nothing is started, signalled or stopped.

        `start_in_slice` hands back a pid no process has and `process_active` knows only those.
        The job's first sleep ends every such child with the record `endings` names for its run
        (a PASS by default); None leaves the record as the child's death left it.
        """
        endings = endings or {}
        self.live, self.started, self.stopped = {}, [], []

        def placed(argv, unit, env, output, log=None, **kwargs):
            kwargs["placement"].update(scope=unit)
            pid = 99999900 + len(self.started)
            self.started.append({"argv": argv, "unit": unit, "env": env, **kwargs})
            self.live[pid] = Path(output).parent
            return pid

        def finish(_seconds):
            for pid, directory in list(self.live.items()):
                ending = endings.get(directory.name, {"state": "pass", "verdict": "PASS"})
                if ending is not None:
                    run.save_state(directory, {**run.read_state(directory), **ending})
                del self.live[pid]

        for where, name, fake in (
                (orch, "start_in_slice", placed),
                (orch, "next_scope_unit", lambda unit: unit),
                (orch, "stop_scope", lambda scope, log=None, wait=False:
                    self.stopped.append((scope, wait)) or True),
                (run, "process_active", lambda state: state.get("pid") in self.live),
                (run, "_scope_oom_probe", lambda state: ("success", 0)),
                (run.worker, "kill_marked", lambda run_id, log=None: True),
                (run.time, "sleep", finish)):
            self.stack.enter_context(patch.object(where, name, side_effect=fake))

    def job_task(self, name, **fields):
        """A task's receipt the way its job left it before starting it: slot held, preflight done."""
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(
            "---\nrepo: none\nrounds: 1\n---\n# A job task\n\n## Done when\n```bash\ntrue\n```\n")
        (directory / "log.txt").touch()
        run.save_state(directory, {"run_id": name, "state": "running", "slot_waiting": False,
                                   "job_id": "20260923-2000-job", "launched_session": None,
                                   "pid": os.getpid(), **fields})
        return directory

    def test_systemd_scope_carries_batch_properties(self):
        output = self.root / "log.txt"
        placement = {}
        proc = MagicMock(pid=321, poll=MagicMock(return_value=None))
        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "can_scope", return_value=True), \
                patch.object(orch, "marked_pid", return_value=654), \
                patch.object(orch.subprocess, "Popen", return_value=proc) as popen:
            self.assertEqual(orch.start_in_slice(
                ["python3", "-c", "pass"], "agentkit-run-r1", {}, output,
                target_slice=orch.RUNS_SLICE,
                properties=("-p", "CPUWeight=40", "-p", "IOWeight=40"),
                nice=True, placement=placement), 654)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:6], ["systemd-run", "--user", "--slice=agentkit-runs.slice",
                                    "--scope", "--quiet", "--unit=agentkit-run-r1"])
        self.assertIn("CPUWeight=40", argv)
        self.assertIn("IOWeight=40", argv)
        self.assertNotIn("Nice=10", argv)
        self.assertEqual(argv[argv.index("--") + 1:argv.index("--") + 4],
                         ["sh", "-c", orch.WITNESS])
        self.assertIn("nice", argv[argv.index("--"):])
        self.assertEqual(placement["scope"], "agentkit-run-r1")

    def test_systemd_service_carries_nice_property(self):
        output = self.root / "service.log"
        proc = MagicMock(pid=323, poll=MagicMock(return_value=None),
                         wait=MagicMock(return_value=0))
        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "can_scope", return_value=False), \
                patch.object(orch, "marked_pid", return_value=655), \
                patch.object(orch.subprocess, "Popen", return_value=proc) as popen:
            self.assertEqual(orch.start_in_slice(
                ["python3", "-c", "pass"], "agentkit-run-r1-service", {}, output,
                target_slice=orch.RUNS_SLICE,
                properties=("-p", "CPUWeight=40", "-p", "IOWeight=40"),
                nice=True), 655)
        argv = popen.call_args.args[0]
        self.assertIn("Nice=10", argv)
        self.assertEqual(argv[argv.index("--") + 1:argv.index("--") + 4],
                         ["sh", "-c", orch.WITNESS.replace("$", "$$")])

    def test_fake_systemd_run_on_path_executes_the_scope_command(self):
        fake = self.root / "bin"
        fake.mkdir()
        argv_file = self.root / "fake-argv.json"
        wrapper = fake / "systemd-run"
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['FAKE_ARGV']).write_text(json.dumps(sys.argv[1:]))\n"
            "i = sys.argv.index('--') + 1\n"
            "os.execvp(sys.argv[i], sys.argv[i:])\n")
        wrapper.chmod(0o755)
        placement = {}
        with patch.dict(os.environ, {"PATH": f"{fake}:{os.environ['PATH']}",
                                     "FAKE_ARGV": str(argv_file)}), \
                patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "can_scope", return_value=True), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            pid = orch.start_in_slice([sys.executable, "-c", "pass"], "agentkit-run-r1-fake",
                                      dict(os.environ), self.root / "fake.log",
                                      target_slice=orch.RUNS_SLICE,
                                      properties=("-p", "CPUWeight=40", "-p", "IOWeight=40"),
                                      nice=True, placement=placement)
        self.assertGreater(pid, 0)
        argv = json.loads(argv_file.read_text())
        self.assertNotIn("Nice=10", argv)
        self.assertIn("nice", argv)
        self.assertEqual(placement["scope"], "agentkit-run-r1-fake")

    def test_plain_host_records_none_and_sets_nice_preexec(self):
        output = self.root / "plain.log"
        placement = {}
        proc = MagicMock(pid=322)
        with patch.object(orch, "user_manager", return_value=False), \
                patch.object(orch.subprocess, "Popen", return_value=proc) as popen:
            self.assertEqual(orch.start_in_slice(["sleep", "1"], "agentkit-run-r2", {}, output,
                                                 nice=True, placement=placement), 322)
        self.assertEqual(popen.call_args.args[0], ["sleep", "1"])
        self.assertIn("preexec_fn", popen.call_args.kwargs)
        self.assertEqual(placement, {"scope": "none", "scope_reason": "no user systemd manager"})

    def test_spawn_bg_persists_scope_and_loop_pid(self):
        directory = self.run_dir()

        def placed(*args, **kwargs):
            kwargs["placement"].update(scope="agentkit-run-20260922-0900-scope")
            return 9876

        with patch.object(orch, "start_in_slice", side_effect=placed):
            run.spawn_bg(directory, ["resume", directory.name])
        state = run.read_state(directory)
        self.assertEqual(state["scope"], "agentkit-run-20260922-0900-scope")
        self.assertEqual(state["pid"], 9876)
        self.assertEqual(state["launched_session"], "old-session")

    def test_spawn_bg_plain_fallback_persists_reason(self):
        directory = self.run_dir("20260922-0900-plain")

        def plain(*args, **kwargs):
            kwargs["placement"].update(scope="none", scope_reason="systemd-run failed (exit 1)")
            return 9877

        with patch.object(orch, "start_in_slice", side_effect=plain):
            run.spawn_bg(directory, ["resume", directory.name])
        state = run.read_state(directory)
        self.assertEqual(state["scope"], "none")
        self.assertIn("systemd-run failed", state["scope_reason"])

    def test_background_preflight_scope_is_appended_without_rewriting_log(self):
        directory = self.run_dir("20260922-0900-log")
        (directory / "log.txt").write_text("[09:00:00] scope: pending\n")

        def placed(*args, **kwargs):
            kwargs["placement"].update(scope="agentkit-run-20260922-0900-log")
            return 9878

        with patch.object(orch, "start_in_slice", side_effect=placed):
            run.spawn_bg(directory, ["resume", directory.name])
        log = (directory / "log.txt").read_text()
        self.assertIn("scope: pending", log)
        self.assertIn("scope: agentkit-run-20260922-0900-log", log)

    def test_preflight_prints_scope_reason_once(self):
        directory = self.run_dir("20260922-0900-preflight")
        (directory / "task.md").write_text("---\n---\n# Scratch\n")
        run.save_state(directory, {**(run.read_state(directory) or {}),
                                   "silence_minutes": 20, "ceiling_hours": 6,
                                   "scope": "none", "scope_reason": "no user systemd manager"})
        opts = {"--review-pr": None, "--no-merge": True, "--anyway": False}
        lines = []
        with patch.object(run, "task_repo", return_value=None), \
                patch.object(run, "done_when_groups", return_value=([], [])), \
                patch.object(run, "ignore_time_keys"), \
                patch.object(run, "parse_task", return_value=({}, "", "Scratch")):
            run.preflight(directory, opts, lines.append)
        self.assertEqual([line for line in lines if line.startswith("scope:")],
                         ["scope: none (no user systemd manager)"])

    def test_launched_session_name_survives_restart(self):
        directory = self.run_dir("20260922-0900-handback")
        with patch.object(config, "current_session", return_value="restarted-session"):
            self.assertEqual(run.launch_session(directory), "old-session")

    def test_stop_scope_uses_systemctl_scope_unit(self):
        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch.subprocess, "run", return_value=MagicMock()) as run_call:
            self.assertTrue(orch.stop_scope("agentkit-run-r3"))
        self.assertEqual(run_call.call_args.args[0],
                         ["systemctl", "--user", "stop", "agentkit-run-r3.scope"])

    def test_scope_name_probe_failure_allows_plain_fallback(self):
        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch.subprocess, "run", side_effect=OSError("bus vanished")):
            self.assertEqual(orch.next_scope_unit("agentkit-run-r3"), "agentkit-run-r3")

    def test_watch_stops_a_recorded_scope(self):
        with patch.object(orch, "stop_scope", return_value=True) as stop:
            self.assertTrue(watch.stop_run_scope({"scope": "agentkit-run-r4"}))
        stop.assert_called_once_with("agentkit-run-r4", unittest.mock.ANY)

    def test_recovery_orders_resume_after_releasing_the_run_lock(self):
        directory = self.run_dir("20260922-0900-recover")
        run.save_state(directory, {"run_id": directory.name, "state": "running",
                                   "pid": 999999, "scope": "none", "silence_minutes": 1})
        (directory / "log.txt").write_text("old\n")

        def placed(*args, **kwargs):
            kwargs["placement"].update(scope="agentkit-run-20260922-0900-recover")
            return 999998

        with patch.object(run, "run_dirs", return_value=[directory]), \
                patch.object(run, "process_active", return_value=False), \
                patch.object(orch, "start_in_slice", side_effect=placed):
            watch.recover_runs({}, now=time.time() + 3600, log=lambda _: None)
        self.assertEqual(run.read_state(directory)["scope"],
                         "agentkit-run-20260922-0900-recover")

    def test_scope_stop_cleans_an_escaped_executor_session(self):
        fake = self.root / "bin"
        fake.mkdir(exist_ok=True)
        systemctl = fake / "systemctl"
        systemctl.write_text(
            "#!/usr/bin/env python3\n"
            "import os, signal, sys\n"
            "from pathlib import Path\n"
            "if sys.argv[1:3] == ['--user', 'stop']:\n"
            "    os.kill(int(Path(os.environ['CHILD_PID']).read_text()), signal.SIGKILL)\n")
        systemctl.chmod(0o755)
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess,time; "
             "child=subprocess.Popen(['setsid','sleep','100000']); "
             "print(child.pid, flush=True); "
             "exec('while child.poll() is None:\\n time.sleep(.05)'); "
             "child.wait(); time.sleep(100000)"],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        child_pid = int(proc.stdout.readline())
        child_file = self.root / "child.pid"
        child_file.write_text(str(child_pid))

        def cleanup():
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            proc.stdout.close()

        self.addCleanup(cleanup)
        with patch.dict(os.environ, {"PATH": f"{fake}:{os.environ['PATH']}",
                                     "CHILD_PID": str(child_file)}), \
                patch.object(orch, "user_manager", return_value=True):
            self.assertTrue(watch.stop_run_scope({"scope": "agentkit-run-r5"}))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and Path(f"/proc/{child_pid}").exists():
            time.sleep(0.05)
        self.assertFalse(Path(f"/proc/{child_pid}").exists())

    def test_a_job_in_its_own_scope_starts_each_task_in_a_run_scope_of_its_own(self):
        job = self.scoped_job()
        self.assertTrue(run.job_scoped(job))
        # a record naming a scope this process is not in -- the job resumed from a terminal
        # after its scoped launcher died -- and a plain start keep the tasks in the process
        self.assertFalse(run.job_scoped({**job, "scope": "agentkit-job-an-older-launch"}))
        self.assertFalse(run.job_scoped({**job, "scope": "none (no user systemd manager)"}))
        self.assertFalse(run.job_scoped({}))
        self.fake_children()
        cfg = config.load()
        tasks = [self.job_task("20260923-2000-alpha"), self.job_task("20260923-2000-beta")]
        opts = {"--rounds": "2", "--exec": "exec-model", "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": False, "--anyway": False, "--bg": False}
        boxes = [{}, {}]
        with redirect_stdout(io.StringIO()), \
                patch.object(run, "drive", side_effect=AssertionError("driven in the job")):
            for directory, box in zip(tasks, boxes):
                run.job_drive(cfg, directory, opts, box, run.job_scoped(job))
        # each task went where a lone `--bg` run goes: its own unit, capped, in the runs slice
        self.assertEqual([start["unit"] for start in self.started],
                         [f"agentkit-run-{directory.name}" for directory in tasks])
        for directory, start, box in zip(tasks, self.started, boxes):
            self.assertEqual(start["target_slice"], orch.run_slice_name())
            self.assertTrue(any(str(prop).startswith("MemoryMax=")
                                for prop in start["properties"]))
            self.assertEqual(start["argv"][2:], ["run", str(directory / "task.md"),
                                                 "--rounds", "2", "--exec", "exec-model",
                                                 "--no-merge"])
            self.assertEqual(start["env"][config.RUN_DIR_ENV], str(directory))
            state = run.read_state(directory)
            self.assertEqual(state["scope"], f"agentkit-run-{directory.name}")
            self.assertEqual(state["job_id"], "20260923-2000-job")
            self.assertEqual(state["memory_cap_mb"], run.memory_cap_mb())
            # ... and the job followed it there to its ending
            self.assertEqual(box["state"]["state"], "pass")
        self.assertNotIn(job["scope"], [scope for scope, _ in self.stopped])

    def test_a_scoped_job_resumes_and_redelivers_a_task_in_the_tasks_own_scope(self):
        job = self.scoped_job()
        cfg = config.load()
        workers = cfg["defaults"]["workers"]
        workspace = config.WORK / "resume-me"
        workspace.mkdir(parents=True)
        resumed = self.job_task("20260923-2000-resume", state="interrupted", pid=99999999,
                                scope="agentkit-run-20260923-2000-resume", recovery_pending=True,
                                scratch=True, worktree=str(workspace), rounds=1,
                                round_summaries=[], executor=workers[0], reviewer=workers[-1],
                                no_merge=True)
        undelivered = self.job_task("20260923-2000-deliver", state="pass", verdict="PASS",
                                    pid=99999999, merge_failed=True, merge_note="push rejected")
        self.fake_children({undelivered.name: {"state": "pass", "merge_failed": True,
                                               "merge_note": "push rejected again"}})
        job_dir = config.JOBS / job["job_id"]
        job_dir.mkdir(parents=True)
        task = {"name": "a.md", "state": "running", "run_id": resumed.name, "after": []}
        laddered = []
        with redirect_stdout(io.StringIO()), \
                patch.object(run, "job_ladder", side_effect=lambda *args: laddered.append(args[5])):
            run.job_adopt_worker(cfg, job_dir, job, task, resumed, threading.Lock(),
                                 lambda _: None)
        # the resume is `ak run resume <id>` in the task's own scope, followed to its ending
        self.assertEqual(self.started[0]["argv"][2:], ["run", "resume", resumed.name])
        self.assertEqual(self.started[0]["unit"], f"agentkit-run-{resumed.name}")
        self.assertEqual([state["state"] for state in laddered], ["pass"])
        # ... and a PASS whose delivery failed is retried the same way, never in the job
        delivery = {"name": "b.md", "state": "running", "run_id": undelivered.name, "after": []}
        job["tasks"] = [task, delivery]
        with patch.object(run, "cmd_merge", side_effect=AssertionError("merged in the job")):
            run.job_ladder(cfg, job_dir, job, delivery, undelivered, run.read_state(undelivered),
                           1, lambda _: None, threading.Lock())
        self.assertEqual(self.started[1]["argv"][2:], ["run", "merge", undelivered.name])
        self.assertEqual(self.started[1]["unit"], f"agentkit-run-{undelivered.name}")
        self.assertTrue(any(str(prop).startswith("MemoryMax=")
                            for prop in self.started[1]["properties"]))
        self.assertEqual(delivery["state"], "failed")
        self.assertEqual(delivery["verdict_line"], "b.md: PASS, delivery failed: needs you")

    def test_a_detached_merge_reads_its_receipt_only_once_its_new_scope_is_saved(self):
        # `launch_resume` holds the handoff lock from the start until the new scope is on the
        # receipt; a merge that read it before then would save the old scope back over it
        directory = self.run_dir("20260923-2000-merge")
        reads, refused = [], []
        real_read = run.read_state

        def reading(run_dir):
            state = real_read(run_dir)
            if threading.current_thread().name == "merge":
                reads.append(state)
            return state

        def merge():
            try:
                run.cmd_merge([directory.name])
            except config.Error as exc:
                refused.append(str(exc))

        child = threading.Thread(target=merge, name="merge", daemon=True)
        with patch.object(run, "read_state", side_effect=reading):
            with run.recovery_lock(directory):
                child.start()
                time.sleep(0.3)
                self.assertEqual(reads, [])
                run.save_state(directory, {**real_read(directory),
                                           "scope": "agentkit-run-20260923-2000-merge-2"})
            child.join(timeout=10)
        self.assertEqual(reads[0]["scope"], "agentkit-run-20260923-2000-merge-2")
        self.assertIn("merge requires a finished PASS", refused[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
