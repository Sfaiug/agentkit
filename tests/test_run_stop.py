"""`ak run stop` is the one deliberate way to end a run.

Offline and deterministic: fake run receipts under a throwaway HOME, real `sleep`
processes for the tree the stop must end, and a real throwaway git repo for the
checkout it must take. No harness, no network and nothing of the owner's is touched.
"""

import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import gate, config, job as jobs, land, menu, orch, run, watch, worker
from agentkit import host, record
from agentkit import task as taskfile


def alive(pid):
    """Whether that pid still runs anything killable."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X")
    except (OSError, IndexError):
        return True


class RunStop(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_SESSION", "AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)

    def running(self, name, owner="seat", **extra):
        """A running receipt with a dead pid, unless the caller names a live one."""
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "task.md").write_text("# Task\n\n## Done when\n```bash\ntrue\n```\n")
        (directory / "log.txt").touch()
        state = {"run_id": name, "title": f"Running {name}", "state": "running",
                 "verdict": None, "launched_session": owner,
                 "executor": "opus", "reviewer": "astra", "rounds": 3,
                 "started_at": time.time() - 60, "reported": False,
                 "pid": 999999999, "process_identity": None, **extra}
        record.save_state(directory, state)
        return directory

    def test_stop_of_a_parked_member_leaves_the_line_and_starts_a_pass(self):
        turn = config.RUNS / ".merge-acme.lock"
        with patch.object(land, "start_line") as start:
            directory = self.running("fix-api", state="waiting",
                                     waiting_on={"line": turn.name, "joined": 1})
            start.reset_mock()
            with (patch.object(orch, "user_manager", return_value=False),
                  patch.object(run, "marker_pids", return_value=[]),
                  patch.object(run, "stop_checkout", return_value=True),
                  patch("agentkit.browser.close_owned"), redirect_stdout(io.StringIO())):
                self.assertEqual(run.cmd_stop([directory.name]), 0)
            start.assert_called_once_with(turn)
        state = record.read_state(directory)
        self.assertEqual(state["state"], "stopped")
        self.assertNotIn("waiting_on", state)
        self.assertEqual(land.line(turn), [])

    def test_a_delayed_lander_wake_never_launches_a_stopped_member(self):
        directory = self.running("fix-api", state="stopped", verdict="STOPPED")
        with patch.object(orch, "start_in_slice") as start:
            self.assertFalse(watch.launch_resume(directory.name))
        start.assert_not_called()
        self.assertEqual(record.read_state(directory)["state"], "stopped")

    def repo(self):
        """A throwaway git repo with one commit, ready for worktrees."""
        repo = self.root / f"repo-{time.time_ns()}"
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)],
                       check=True, env=env, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                       check=True, env=env, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                       check=True, env=env, capture_output=True)
        (repo / "file.txt").write_text("base\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True,
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"],
                       check=True, env=env, capture_output=True)
        return repo

    def test_stop_ends_the_loop_and_its_children(self):
        from agentkit import watch as watch_mod
        run_id = "20260101-0900-stop-tree"
        loop = subprocess.Popen(["bash", "-c", "sleep 30 & wait"])
        marked = subprocess.Popen(
            ["sleep", "30"],
            env={**os.environ, "AK_PARENT_RUN": run_id,
                 worker.RUN_MARKER: worker.run_marker(run_id)})
        self.addCleanup(self.reap, loop)
        self.addCleanup(self.reap, marked)
        time.sleep(0.3)  # the shell has its sleep by now
        children = [pid for pid, _ in watch_mod.loop_children(loop.pid)]
        self.assertTrue(children, "the fixture loop has no child to kill")
        directory = self.running(run_id, pid=loop.pid,
                                 process_identity=host.process_identity(loop.pid))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        try:
            loop.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            marked.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        self.assertFalse(alive(loop.pid), "the loop survived its stop")
        for pid in children:
            self.assertFalse(alive(pid), f"the loop's child {pid} survived")
        self.assertFalse(alive(marked.pid), "the marked child survived")
        self.assertEqual(record.read_state(directory)["state"], "stopped")
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def reap(self, proc):
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass

    def test_stopped_reads_final_and_is_never_offered(self):
        run_id = "20260101-0900-stop-final"
        directory = self.running(run_id, recovery_pending=True)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        state = record.read_state(directory)
        self.assertEqual(state["state"], "stopped")
        self.assertIn("stopped", run.ENDED)
        self.assertFalse(run.needs_recovery(state))
        self.assertFalse(run.unfinished(state))
        self.assertFalse(run.owes_ending(state))
        self.assertEqual(state.get("verdict"), "STOPPED")
        # Reaping leaves a deliberate end alone, and resume refuses it.
        self.assertEqual(run.reap(directory, state)["state"], "stopped")
        with self.assertRaises(config.Error) as refused:
            run.cmd_resume([run_id])
        self.assertIn("stopped", str(refused.exception))
        # No hand-back, no card: announce is a no-op for a stopped run.
        with patch.object(run, "hand_back",
                          side_effect=AssertionError("handed back")), \
                patch("agentkit.notify.shaped",
                      side_effect=AssertionError("card sent")):
            run.announce(state, directory, lambda _: None)
        self.assertEqual(menu.run_state_word(state), "done")
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)

    def test_keep_keeps_the_worktree(self):
        repo = self.repo()
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        # Without --keep the checkout and the branch go; the line names the branch
        # but advertises no `from:` line, since that branch is gone with it.
        wt, branch = run.make_worktree(repo, "20260101-0900-stop-gone", "gone", base)
        gone = self.running("20260101-0900-stop-gone", repo=str(repo),
                             worktree=str(wt), branch=branch, base="main",
                             base_sha=base)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["20260101-0900-stop-gone"]), 0)
        self.assertFalse(wt.exists(), "the worktree survived its stop")
        left = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "", "the local branch survived its stop")
        line = out.getvalue().strip()
        self.assertIn(branch, line)
        self.assertIn("removed", line)
        self.assertNotIn("from:", line)
        # With --keep both stay, for the relaunch the line names.
        wt2, branch2 = run.make_worktree(repo, "20260101-0900-stop-kept", "kept", base)
        self.running("20260101-0900-stop-kept", repo=str(repo), worktree=str(wt2),
                     branch=branch2, base="main", base_sha=base)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["20260101-0900-stop-kept", "--keep"]), 0)
        self.assertTrue(wt2.is_dir(), "--keep removed the worktree")
        left = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch2],
                              capture_output=True, text=True).stdout.strip()
        self.assertIn(branch2, left, "--keep deleted the branch")
        line = out.getvalue().strip()
        self.assertIn("kept", line)
        self.assertIn(f"from: {branch2}", line)

    def test_a_stopped_task_fails_the_job_and_an_old_waiting_task_is_blocked(self):
        self.assertIn("stopped", jobs.JOB_TERMINAL)
        self.assertIn("stopped", jobs.JOB_UNDELIVERED)
        cfg = self.cfg
        self.assertEqual(jobs.job_classify({"state": "stopped"}, cfg), "stopped")
        self.assertEqual(jobs.job_verdict_line({"name": "a.md", "state": "stopped"}),
                         "a.md: stopped")
        job_dir = config.JOBS / "20260101-090000-stop-job"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": job_dir.name, "seat": None, "started_at": time.time(),
               "finished_at": None, "parallel": None, **record.process_owner(),
               "opts": {}, "tasks": [
                   {"name": "a.md", "title": "A", "state": "stopped",
                    "run_id": "gone", "verdict_line": "a.md: stopped"},
                   {"name": "b.md", "title": "B", "after": ["a.md"], "state": "waiting",
                    "run_id": None},
                   {"name": "c.md", "title": "C", "after": ["a.md"], "state": "queued",
                    "run_id": None, "from_pass": {"task": "a.md", "tip": "tip"}}]}
        jobs.save_job(job_dir, job)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = jobs.run_job_loop(cfg, job_dir, job)
        self.assertEqual(rc, 1)
        kept = jobs.read_job(job_dir)
        waiting = next(task for task in kept["tasks"] if task["name"] == "b.md")
        cut = next(task for task in kept["tasks"] if task["name"] == "c.md")
        for task in (waiting, cut):
            # never built: undelivered, so the job ends needing its seat, never as done
            self.assertEqual(task["state"], "blocked")
            self.assertIn("`after:` is gone", task["verdict_line"])
            self.assertIn(f"launch {task['name']} on its own once a.md merged", task["findings"])

    def test_an_old_task_behind_a_merged_one_goes_back_to_its_seat(self):
        job_dir = config.JOBS / "20260101-090000-old-after"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": job_dir.name, "seat": "atoll-fix", "started_at": time.time(),
               "finished_at": None, "parallel": None, **record.process_owner(),
               "opts": {}, "tasks": [
                   {"name": "a.md", "title": "A", "state": "merged", "run_id": "gone",
                    "verdict_line": "a.md: PASS, merged"},
                   {"name": "b.md", "title": "B", "after": ["a.md"], "state": "waiting",
                    "run_id": None}]}
        jobs.save_job(job_dir, job)
        # spent providers never hold it: it goes back before any budget check
        with patch.object(jobs, "job_hand_back", return_value="sent") as handed, \
                patch.object(run, "collect_usage", side_effect=AssertionError("budget checked")), \
                redirect_stdout(io.StringIO()):
            rc = jobs.run_job_loop(self.cfg, job_dir, job)
        self.assertEqual(rc, 1)
        line = handed.call_args.args[1]
        self.assertIn("1 task(s) need you", line)
        self.assertIn("launch b.md on its own once a.md merged", line)

    def old_job(self, name, *tasks):
        job_dir = config.JOBS / name
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": job_dir.name, "seat": None, "started_at": time.time(),
               "finished_at": None, "parallel": None, **record.process_owner(), "opts": {},
               "tasks": [{"name": "a.md", "title": "A", "state": "merged", "run_id": "gone",
                          "verdict_line": "a.md: PASS, merged"}, *tasks]}
        jobs.save_job(job_dir, job)
        return job_dir, job

    def test_an_old_task_with_a_kept_run_is_adopted_never_blocked(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        for state in ("waiting", "queued"):
            with self.subTest(state=state):
                kept = self.running(f"20260101-0900-kept-{state}", owner=None, state="pass",
                                    verdict="PASS", merged=True, pid=None)
                job_dir, job = self.old_job(f"20260101-090000-kept-{state}", {
                    "name": "b.md", "title": "B", "after": ["a.md"], "state": state,
                    "run_id": kept.name, "from_pass": legacy})

                def adopt(cfg, job_dir, receipt, task, run_dir, lock, log):
                    task.update(state="merged", finished_at=time.time(),
                                verdict_line="b.md: PASS, merged")
                    with lock:
                        jobs.save_job(job_dir, receipt)

                with patch.object(jobs, "job_adopt_worker", side_effect=adopt) as adopted, \
                        patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                        redirect_stdout(io.StringIO()):
                    rc = jobs.run_job_loop(self.cfg, job_dir, job)
                self.assertEqual(rc, 0)
                self.assertEqual(adopted.call_args.args[4], kept)
                self.assertEqual(jobs.read_job(job_dir)["tasks"][1]["state"], "merged")

    def test_an_old_task_whose_kept_run_stands_on_its_dependency_ends_through_its_guard(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        # whatever state it was saved in, and whether its job died before or while it ran:
        # no resume, merge retry, budget or login wait first
        cases = [(saved, held) for held in ("waiting", "running") for saved in (
            {"state": "exhausted", "error": "provider has no budget"},
            {"state": "interrupted"},
            {"state": "waiting_login", "error": "the login expired"},
            {"state": "pass", "verdict": "PASS", "merge_failed": True,
             "error": "git push failed"})]
        for saved, held in cases:
            with self.subTest(saved=saved["state"], held=held):
                name = f"20260101-0900-kept-{saved['state']}-{held}"
                workspace = config.WORK / name
                workspace.mkdir(parents=True)
                kept = self.running(name, owner=None, **{
                    "verdict": None, "pid": None, "base_sha": "tip", "from_pass": legacy,
                    "scratch": True, "repo": None, "worktree": str(workspace), "branch": "ak/b",
                    "round_summaries": [], "findings": "", "merged": False, **saved})
                job_dir, job = self.old_job(f"20260101-090000-{saved['state']}-{held}", {
                    "name": "b.md", "title": "B", "after": ["a.md"], "state": held,
                    "run_id": kept.name, "from_pass": legacy})
                with patch.object(run, "collect_usage", side_effect=AssertionError("budget")), \
                        patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                        patch.object(run, "cmd_resume", side_effect=AssertionError("a resume")), \
                        patch.object(run, "cmd_merge", side_effect=AssertionError("a merge")), \
                        redirect_stdout(io.StringIO()):
                    rc = jobs.run_job_loop(self.cfg, job_dir, job)
                self.assertEqual(rc, 1)
                self.assertEqual(record.read_state(kept)["state"], "blocked")
                task = jobs.read_job(job_dir)["tasks"][1]
                self.assertEqual((task["state"], task["run_id"]), ("blocked", kept.name))
                # the relaunch goes on from the work the kept run has, never from the target
                self.assertIn("relaunch with `from: ak/b`", task["findings"])
                self.assertIn("relaunch with `from: ak/b`", task["verdict_line"])

    def test_an_old_task_whose_kept_run_cannot_be_ended_still_goes_back_with_it(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        for held in ("waiting", "running"):
            with self.subTest(held=held):
                kept = self.running(f"20260101-0900-kept-stuck-{held}", owner=None,
                                    state="interrupted", verdict=None, pid=None, base_sha="tip",
                                    from_pass=legacy, branch="ak/b", round_summaries=[],
                                    findings="", merged=False)
                job_dir, job = self.old_job(f"20260101-090000-stuck-{held}", {
                    "name": "b.md", "title": "B", "after": ["a.md"], "state": held,
                    "run_id": kept.name, "from_pass": legacy})
                with patch.object(run, "end_on_dependency", side_effect=run.Stopped("git killed")), \
                        patch.object(run, "cmd_resume", side_effect=AssertionError("a resume")), \
                        patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                        redirect_stdout(io.StringIO()):
                    rc = jobs.run_job_loop(self.cfg, job_dir, job)
                self.assertEqual(rc, 1)
                task = jobs.read_job(job_dir)["tasks"][1]
                self.assertEqual((task["state"], task["run_id"]), ("blocked", kept.name))
                self.assertIn("relaunch with `from: ak/b`", task["findings"])
                self.assertIn("git killed", task["findings"])

    def test_a_kept_run_another_process_moved_on_is_left_as_it_left_it(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        kept = self.running("20260101-0900-kept-raced", owner=None, state="interrupted",
                            verdict=None, pid=None, base_sha="tip", from_pass=legacy,
                            branch="ak/b", round_summaries=[], findings="", merged=False)
        stale = record.read_state(kept)
        job_dir, job = self.old_job("20260101-090000-raced")
        for live in ({**stale, "state": "running", "pid": 999999991},
                     {**stale, "state": "pass", "verdict": "PASS", "merged": True}):
            with self.subTest(state=live["state"]):
                record.save_state(kept, stale)
                task = {"name": "b.md", "title": "B", "after": ["a.md"], "state": "running",
                        "run_id": kept.name, "from_pass": legacy}

                def reap(directory, _state):
                    # a resume or a delivery wins the run once the reap lets go of it
                    record.save_state(directory, live)
                    return stale

                with patch.object(run, "reap", side_effect=reap), \
                        patch.object(record, "process_active",
                                     side_effect=lambda state: state.get("pid") == 999999991), \
                        patch.object(run, "cmd_resume"), patch.object(jobs, "job_ladder"):
                    jobs.job_adopt_worker(self.cfg, job_dir, {**job, "tasks": [task]}, task, kept,
                                          threading.Lock(), lambda _: None)
                saved = record.read_state(kept)
                self.assertEqual((saved["state"], saved.get("merged"), saved.get("pid")),
                                 (live["state"], live.get("merged"), live.get("pid")))

    def test_a_queued_task_whose_file_now_names_after_gets_no_fresh_run(self):
        # the receipt saved it plain; its file was edited to wait on another task since
        task_file = self.root / "beta.md"
        task_file.write_text("---\nrepo: none\nafter: alpha.md\n---\n# Beta\n\n"
                             "## Done when\n```bash\ntrue\n```\n")
        job_dir, job = self.old_job("20260101-090000-after-added", {
            "name": "beta.md", "title": "Beta", "state": "queued", "run_id": None,
            "task_file": str(task_file)})
        with patch.object(run, "collect_usage", return_value={}), \
                patch.object(run, "pick_models", return_value=("opus", "astra")), \
                patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                redirect_stdout(io.StringIO()):
            rc = jobs.run_job_loop(self.cfg, job_dir, job)
        self.assertEqual(rc, 1)
        task = jobs.read_job(job_dir)["tasks"][1]
        self.assertEqual(task["state"], "blocked")
        self.assertIn("`after:` is gone", task["findings"])

    def test_a_kept_run_merged_elsewhere_while_adopted_is_the_tasks_ending(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        for name, extra in (("legacy", {"after": ["a.md"], "from_pass": legacy}),
                            ("plain", {})):
            with self.subTest(task=name):
                kept = self.running(f"20260101-0900-merged-{name}", owner=None,
                                    state="interrupted", verdict=None, pid=None, branch="ak/b",
                                    round_summaries=[], findings="", merged=False,
                                    **({"from_pass": legacy, "base_sha": "tip"} if extra else {}))
                stale = record.read_state(kept)
                job_dir, job = self.old_job(f"20260101-090000-merged-{name}")
                task = {"name": "b.md", "title": "B", "state": "running",
                        "run_id": kept.name, **extra}
                job["tasks"] = [job["tasks"][0], task]

                def reap(directory, _state):
                    # a delivery wins the run once the reap lets go of it
                    record.save_state(directory, {**stale, "state": "pass", "verdict": "PASS",
                                                  "merged": True, "base_sha": "main"})
                    return dict(stale)

                with patch.object(run, "reap", side_effect=reap), \
                        patch.object(run, "review_pass",
                                     side_effect=lambda state, _cfg: state.get("verdict") == "PASS"), \
                        patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                        redirect_stdout(io.StringIO()):
                    jobs.job_adopt_worker(self.cfg, job_dir, job, task, kept, threading.Lock(),
                                          lambda _: None)
                self.assertEqual((task["state"], task["run_id"]), ("merged", kept.name))

    def test_a_merged_task_stays_merged_after_its_models_are_removed(self):
        review = {"executor": "opus", "reviewer": "astra", "returncode": 0, "verdict": "PASS",
                  "executor_provider": config.model(self.cfg, "opus")["provider"],
                  "reviewer_provider": config.model(self.cfg, "astra")["provider"],
                  "done_when": True, "head_sha": "a" * 40, "tree_sha": "b" * 40}
        for removed in ("opus", "astra"):
            with self.subTest(removed=removed):
                kept = self.running(f"20260101-0900-merged-{removed}", owner=None, state="pass",
                                    pid=None, verdict="PASS", merged=True, review=review,
                                    repo=str(self.root / "repo"), round_summaries=[])
                cfg = copy.deepcopy(self.cfg)
                config.remove_model(cfg, removed)      # its review can no longer be judged today
                task = {"name": "b.md", "title": "B", "state": "running", "run_id": kept.name}
                job_dir, job = self.old_job(f"20260101-090000-merged-{removed}", task)
                with patch.object(run, "reap",
                                  side_effect=lambda directory, _state: record.read_state(directory)), \
                        redirect_stdout(io.StringIO()):
                    jobs.job_adopt_worker(cfg, job_dir, job, task, kept, threading.Lock(),
                                          lambda _: None)
                self.assertEqual(task["state"], "merged")

    def test_a_kept_run_taken_on_elsewhere_while_adopted_stays_the_tasks(self):
        for moved in ({"state": "running", "pid": 999999991},
                      {"state": "queued", "slot_waiting": True, "pid": 999999991},
                      {"state": "waiting", "waiting_on": {"line": ".merge-acme.lock",
                                                          "joined": 1}}):
            with self.subTest(state=moved["state"]):
                kept = self.running(f"20260101-0900-moved-{moved['state']}", owner=None,
                                    state="interrupted", verdict=None, pid=None, branch="ak/b",
                                    round_summaries=[], findings="", merged=False)
                stale = record.read_state(kept)
                job_dir, job = self.old_job(f"20260101-090000-moved-{moved['state']}")
                task = {"name": "b.md", "title": "B", "state": "running", "run_id": kept.name}
                job["tasks"] = [job["tasks"][0], task]

                def reap(directory, _state):
                    # a resume or the lander takes the run on once the reap lets go of it
                    record.save_state(directory, {**stale, **moved})
                    return dict(stale)

                followed = []
                with patch.object(run, "reap", side_effect=reap), \
                        patch.object(record, "process_active",
                                     side_effect=lambda state: state.get("pid") == 999999991), \
                        patch.object(jobs, "job_ladder",
                                     side_effect=lambda *args: followed.append(args[5]["state"])), \
                        patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                        redirect_stdout(io.StringIO()):
                    jobs.job_adopt_worker(self.cfg, job_dir, job, task, kept, threading.Lock(),
                                          lambda _: None)
                self.assertEqual((task["state"], task["run_id"], followed),
                                 ("queued", kept.name, []))
                self.assertGreater(task["retry_after"], time.time())

    def test_an_old_task_whose_kept_run_was_stopped_stays_stopped(self):
        legacy = {"task": "a.md", "branch": "ak/a", "tip": "tip"}
        kept = self.running("20260101-0900-kept-stopped", owner=None, state="stopped",
                            verdict=None, pid=None, base_sha="tip", from_pass=legacy)
        job_dir, job = self.old_job("20260101-090000-kept-stopped", {
            "name": "b.md", "title": "B", "after": ["a.md"], "state": "queued",
            "run_id": kept.name, "from_pass": legacy})
        with redirect_stdout(io.StringIO()):
            jobs.run_job_loop(self.cfg, job_dir, job)
        task = jobs.read_job(job_dir)["tasks"][1]
        self.assertEqual(task["state"], "stopped")
        self.assertNotIn("findings", task)

    def test_an_old_task_left_running_without_its_run_gets_no_fresh_one(self):
        job_dir, job = self.old_job("20260101-090000-no-run", {
            "name": "b.md", "title": "B", "after": ["a.md"], "state": "running",
            "run_id": None, "from_pass": {"task": "a.md", "branch": "ak/a", "tip": "tip"}})
        with patch.object(run, "prepare", side_effect=AssertionError("a fresh run")), \
                patch.object(run, "collect_usage", side_effect=AssertionError("budget checked")), \
                redirect_stdout(io.StringIO()):
            rc = jobs.run_job_loop(self.cfg, job_dir, job)
        self.assertEqual(rc, 1)
        task = jobs.read_job(job_dir)["tasks"][1]
        self.assertEqual(task["state"], "blocked")
        self.assertIn("launch b.md on its own once a.md merged", task["findings"])

    def test_x_stops_the_sessions_runs_first(self):
        seat = "atoll-fix"
        mine = self.running("20260101-0900-stop-mine", owner=seat)
        other = self.running("20260101-0900-stop-other", owner="parser")
        done = self.ended("20260101-0900-stop-done", owner=seat)
        order = []
        real_stop = run.cmd_stop

        def stop(run_id):
            order.append(("run", run_id[0]))
            return real_stop(run_id)

        def seat_stop(argv):
            order.append(("seat", argv[0]))
            return 0

        seats = [{"name": seat}, {"name": "parser"}]
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=["1", "y"]), \
                patch.object(run, "cmd_stop", side_effect=stop), \
                patch.object(orch, "cmd_stop", side_effect=seat_stop), \
                redirect_stdout(out):
            menu.stop_session([dict(entry) for entry in seats], dry_run=False)
        self.assertEqual(record.read_state(mine)["state"], "stopped")
        self.assertEqual(record.read_state(other)["state"], "running")
        self.assertEqual(record.read_state(done)["state"], "pass")
        self.assertIn(("run", mine.name), order)
        self.assertIn(("seat", seat), order)
        self.assertLess(order.index(("run", mine.name)), order.index(("seat", seat)),
                        "the seat ended before its run stopped")

    def test_from_cuts_the_worktree_from_the_named_branch(self):
        repo = self.repo()
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "ak/previous"],
                       check=True, capture_output=True)
        (repo / "carried.txt").write_text("carried\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "previous work"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"],
                       check=True, capture_output=True)
        task = self.root / "relaunch.md"
        task.write_text(f"---\nrepo: {repo}\nfrom: ak/previous\n---\n"
                        "# Relaunch\n\n## Done when\n```bash\ntrue\n```\n")
        run_dir = config.RUNS / "20260101-0900-stop-from"
        run_dir.mkdir()
        (run_dir / "task.md").write_text(task.read_text())
        (run_dir / "log.txt").touch()
        meta, _, title = taskfile.parse_task(task)
        from_branch = (meta.get("from") or "").strip()
        wt, branch = run.make_worktree(repo, run_dir.name, run.slugify(title), from_branch)
        try:
            self.assertTrue((wt / "carried.txt").exists(),
                            "the new checkout does not carry the named branch")
            diff = subprocess.run(["git", "-C", str(wt), "diff", f"{base}...HEAD",
                                   "--name-only"],
                                  capture_output=True, text=True, check=True).stdout
            self.assertIn("carried.txt", diff,
                          "the diff against base does not show the carried work")
        finally:
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                            str(wt)], capture_output=True)
            subprocess.run(["git", "-C", str(repo), "branch", "-D", branch],
                           capture_output=True)

    def test_stop_of_a_job_task_kills_only_its_own_marker(self):
        from agentkit import watch as watch_mod
        run_a, run_b = "20260101-0900-stop-job-a", "20260101-0900-stop-job-b"
        scheduler = subprocess.Popen(
            ["bash", "-c",
             f"{worker.RUN_MARKER}={shlex.quote(worker.run_marker(run_a))} sleep 30 & "
             f"{worker.RUN_MARKER}={shlex.quote(worker.run_marker(run_b))} sleep 30 & wait"],
            stderr=subprocess.DEVNULL)
        self.addCleanup(self.reap, scheduler)
        time.sleep(0.5)  # both marked sleeps are children of the scheduler by now
        children = watch_mod.loop_children(scheduler.pid)
        self.assertEqual(len(children), 2, "the fixture scheduler has no two children")
        ident = host.process_identity(scheduler.pid)
        self.running(run_a, pid=scheduler.pid, process_identity=ident)
        self.running(run_b, pid=scheduler.pid, process_identity=ident)
        job_dir = config.JOBS / "20260101-090000-stop-shared"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        jobs.save_job(job_dir, {"job_id": job_dir.name, "seat": None,
                               "started_at": time.time(), "finished_at": None,
                               "parallel": None, **record.process_owner(scheduler.pid),
                               "opts": {}, "tasks": [
                                   {"name": "a.md", "title": "A", "after": [],
                                    "state": "running", "run_id": run_a},
                                   {"name": "b.md", "title": "B", "after": [],
                                    "state": "running", "run_id": run_b}]})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_a]), 0)
        time.sleep(0.5)
        self.assertTrue(alive(scheduler.pid), "the stop killed its job's scheduler")
        left = [pid for pid in run.marker_pids(run_b) if alive(pid)]
        self.assertTrue(left, "the stop killed its sibling task's child")
        gone = [pid for pid in run.marker_pids(run_a) if alive(pid)]
        self.assertEqual(gone, [], "the stopped task's own child survived")
        self.assertEqual(record.read_state(config.RUNS / run_a)["state"], "stopped")
        self.assertEqual(record.read_state(config.RUNS / run_b)["state"], "running")
        for pid, _ in children:
            if alive(pid):
                try:
                    import signal
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            scheduler.wait(timeout=5)
        except subprocess.TimeoutExpired:
            scheduler.kill()

    def test_preflight_receipt_names_its_job(self):
        repo = self.repo()
        task = self.root / "job-task.md"
        task.write_text(f"---\nrepo: {repo}\n---\n# Job task\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        run_dir = config.RUNS / "20260101-0900-stop-jobid"
        run_dir.mkdir()
        (run_dir / "task.md").write_text(task.read_text())
        (run_dir / "log.txt").touch()
        run.prepare(run_dir, {"--rounds": None, "--exec": None, "--review": None,
                              "--review-pr": None, "--no-merge": True,
                              "--no-worktree": False, "--anyway": True, "--bg": False},
                    lambda _: None, job_id="20260101-090000-stop-job")
        state = record.read_state(run_dir)
        self.assertEqual(state.get("job_id"), "20260101-090000-stop-job")
        self.assertEqual(state.get("pid"), os.getpid())

    def test_stop_during_preflight_kills_only_its_own_marker(self):
        from agentkit import watch as watch_mod
        run_a, run_b = "20260101-0900-stop-pre-a", "20260101-0900-stop-pre-b"
        scheduler = subprocess.Popen(
            ["bash", "-c",
             f"{worker.RUN_MARKER}={shlex.quote(worker.run_marker(run_a))} sleep 30 & "
             f"{worker.RUN_MARKER}={shlex.quote(worker.run_marker(run_b))} sleep 30 & wait"],
            stderr=subprocess.DEVNULL)
        self.addCleanup(self.reap, scheduler)
        time.sleep(0.5)
        children = watch_mod.loop_children(scheduler.pid)
        self.assertEqual(len(children), 2, "the fixture scheduler has no two children")
        ident = host.process_identity(scheduler.pid)
        # The preflight window: the receipt records the scheduler pid before the
        # scheduler writes task["run_id"], so the job file cannot name this run yet.
        self.running(run_a, pid=scheduler.pid, process_identity=ident,
                     job_id="20260101-090000-stop-pre")
        self.running(run_b, pid=scheduler.pid, process_identity=ident,
                     job_id="20260101-090000-stop-pre")
        job_dir = config.JOBS / "20260101-090000-stop-pre"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        jobs.save_job(job_dir, {"job_id": job_dir.name, "seat": None,
                               "started_at": time.time(), "finished_at": None,
                               "parallel": None, **record.process_owner(scheduler.pid),
                               "opts": {}, "tasks": [
                                   {"name": "a.md", "title": "A", "after": [],
                                    "state": "running", "run_id": None},
                                   {"name": "b.md", "title": "B", "after": [],
                                    "state": "running", "run_id": run_b}]})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_a]), 0)
        time.sleep(0.5)
        self.assertTrue(alive(scheduler.pid), "the stop killed its job's scheduler")
        left = [pid for pid in run.marker_pids(run_b) if alive(pid)]
        self.assertTrue(left, "the stop killed its sibling task's child")
        gone = [pid for pid in run.marker_pids(run_a) if alive(pid)]
        self.assertEqual(gone, [], "the stopped task's own child survived")
        self.assertEqual(record.read_state(config.RUNS / run_a)["state"], "stopped")
        for pid, _ in children:
            if alive(pid):
                try:
                    import signal
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            scheduler.wait(timeout=5)
        except subprocess.TimeoutExpired:
            scheduler.kill()

    def test_stop_write_is_atomic_with_the_guard(self):
        import threading
        run_id = "20260101-0900-stop-atomic"
        directory = self.running(run_id)
        held = threading.Event()

        def holder():
            with record.recovery_lock(directory):
                held.set()
                time.sleep(0.4)

        thread = threading.Thread(target=holder)
        thread.start()
        try:
            self.assertTrue(held.wait(timeout=10))
            state = record.read_state(directory)
            state["note"] = "guarded-write"
            start = time.monotonic()
            record.save_state(directory, state)
            blocked = time.monotonic() - start
        finally:
            thread.join(timeout=10)
        self.assertGreaterEqual(blocked, 0.25,
                                "the guard checked and wrote without the lock")

    def test_save_refuses_to_resurrect_a_stopped_run(self):
        run_id = "20260101-0900-stop-noreap"
        directory = self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        stale = record.read_state(directory)
        stale.update(state="running", finished_at=None, error=None)
        with self.assertRaises(record.StopRequested):
            record.save_state(directory, stale)
        self.assertEqual(record.read_state(directory)["state"], "stopped")

    def test_mark_state_keeps_a_concurrent_stop(self):
        run_id = "20260101-0900-stop-markkept"
        directory = self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        kept = run.mark_state(directory, "error", "boom")
        self.assertEqual(kept["state"], "stopped")
        self.assertEqual(record.read_state(directory)["state"], "stopped")

    def test_scheduler_settles_task_stopped_when_stop_lands_in_preflight(self):
        task_file = self.root / "pre-stop.md"
        task_file.write_text("# Pre-stop\n\n## Done when\n```bash\ntrue\n```\n")
        job_dir = config.JOBS / "20260101-090000-stop-preflight"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": job_dir.name, "seat": None, "started_at": time.time(),
               "finished_at": None, "parallel": 1, **record.process_owner(),
               "opts": {}, "tasks": [
                   {"name": "pre-stop.md", "title": "Pre-stop", "after": [],
                    "state": "queued", "run_id": None,
                    "task_file": str(task_file)}]}
        jobs.save_job(job_dir, job)
        out = io.StringIO()
        with patch.object(jobs, "job_start_task",
                          side_effect=record.StopRequested("20260101 stopped")), \
                redirect_stdout(out):
            rc = jobs.run_job_loop(self.cfg, job_dir, job)
        self.assertEqual(rc, 1)
        kept = jobs.read_job(job_dir)
        self.assertEqual(kept["tasks"][0]["state"], "stopped")

    def test_launch_reports_the_stop_that_landed_in_preflight(self):
        task_file = self.root / "launch-stop.md"
        task_file.write_text("# Launch-stop\n\n## Done when\n```bash\ntrue\n```\n")
        out = io.StringIO()
        with patch.object(run, "prepare",
                          side_effect=record.StopRequested("launch stopped")), \
                redirect_stdout(out):
            rc = run.main([str(task_file)])
        self.assertEqual(rc, 1)
        self.assertRegex(out.getvalue().strip(), r"^stopped 20\d{6}-\d{4}-")

    def test_stop_of_manually_resumed_job_task_ends_its_loop(self):
        run_id = "20260101-0900-stop-resumed"
        scheduler = subprocess.Popen(["sleep", "30"], stderr=subprocess.DEVNULL)
        loop = subprocess.Popen(["bash", "-c", "sleep 30 & wait"],
                                stderr=subprocess.DEVNULL)
        self.addCleanup(self.reap, scheduler)
        self.addCleanup(self.reap, loop)
        time.sleep(0.3)
        # A task resumed by hand: the receipt still names its old job, but its loop
        # runs under its own pid while the scheduler works on undisturbed.
        self.running(run_id, pid=loop.pid, process_identity=host.process_identity(loop.pid),
                     job_id="20260101-090000-stop-oldjob")
        job_dir = config.JOBS / "20260101-090000-stop-oldjob"
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        jobs.save_job(job_dir, {"job_id": job_dir.name, "seat": None,
                               "started_at": time.time(), "finished_at": None,
                               "parallel": None,
                               **record.process_owner(scheduler.pid),
                               "opts": {}, "tasks": [
                                   {"name": "a.md", "title": "A", "after": [],
                                    "state": "running", "run_id": run_id}]})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        try:
            loop.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        self.assertFalse(alive(loop.pid), "the resumed loop survived its stop")
        self.assertTrue(alive(scheduler.pid), "the stop killed the live scheduler")
        self.assertEqual(record.read_state(config.RUNS / run_id)["state"], "stopped")

    def test_stop_commits_before_killing(self):
        from agentkit import watch as watch_mod
        run_id = "20260101-0900-stop-order"
        loop = subprocess.Popen(["bash", "-c", "sleep 30 & wait"],
                                stderr=subprocess.DEVNULL)
        self.addCleanup(self.reap, loop)
        time.sleep(0.3)
        self.running(run_id, pid=loop.pid,
                     process_identity=host.process_identity(loop.pid))
        events = []
        real_save, real_kill = record.save_state, watch_mod.kill_tree

        def saving(run_dir, state):
            events.append(("save", state.get("state")))
            return real_save(run_dir, state)

        def killing(pid, log=None):
            events.append(("kill", pid))
            return real_kill(pid, log)

        out = io.StringIO()
        with patch.object(record, "save_state", side_effect=saving), \
                patch.object(watch_mod, "kill_tree", side_effect=killing), \
                redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        try:
            loop.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        kinds = [kind for kind, _ in events]
        self.assertIn("save", kinds)
        self.assertIn("kill", kinds)
        self.assertLess(kinds.index("save"), kinds.index("kill"),
                        "the stop killed before the record said stopped")
        self.assertEqual(events[kinds.index("save")][1], "stopped")

    def test_worker_turn_aborts_on_a_stopped_record(self):
        from agentkit import worker as worker_mod
        run_id = "20260101-0900-stop-noturn"
        directory = self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        target = directory / "round-1" / "executor"
        target.mkdir(parents=True)
        calls = []
        with patch.object(worker_mod, "call",
                          side_effect=lambda *a, **k: calls.append(a) or (0, "x", None, False)):
            with self.assertRaises(record.StopRequested):
                run.call_retrying(self.cfg, "opus", "do it", str(self.root),
                                  target, "executor", None, lambda _: None)
        self.assertEqual(calls, [], "a worker turn started on a stopped run")

    def test_spawn_bg_refuses_a_stopped_receipt(self):
        from agentkit import orch as orch_mod
        run_id = "20260101-0900-stop-nolaunch"
        directory = self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        with patch.object(orch_mod, "start_in_slice",
                          side_effect=AssertionError("launched")) as started:
            with self.assertRaises(config.Error) as refused:
                run.spawn_bg(directory, ["resume", run_id])
        self.assertIn("stopped", str(refused.exception))
        started.assert_not_called()
        self.assertEqual(record.read_state(directory)["state"], "stopped")

    def test_no_worktree_stop_reports_branch_kept(self):
        repo = self.repo()
        branch = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref",
                                 "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        self.running("20260101-0900-stop-shared", repo=str(repo), worktree=str(repo),
                     branch=branch, base="main", base_sha="0" * 40)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["20260101-0900-stop-shared"]), 0)
        line = out.getvalue().strip()
        self.assertIn("kept", line)
        self.assertNotIn("removed", line)
        left = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch],
                              capture_output=True, text=True).stdout.strip()
        self.assertIn(branch, left, "the shared branch was deleted")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["20260101-0900-stop-shared"]), 0)
        again = out.getvalue().strip()
        self.assertNotIn("removed", again)

    def test_missing_run_is_checked_without_creating_or_locking(self):
        directory = self.root / "no-record"
        directory.mkdir()
        with patch.object(record, "recovery_lock", wraps=record.recovery_lock) as lock:
            self.assertIsNone(record.stop_check(None))
            self.assertIsNone(record.stop_check(directory / "no-such-run"))
            self.assertIsNone(record.stop_check(directory))
        self.assertEqual(list(directory.iterdir()), [])
        lock.assert_not_called()

    def test_spawn_boundaries_ask_under_the_stop_lock(self):
        import threading
        run_id = "20260101-0900-stop-gate"
        directory = self.running(run_id)
        held = threading.Event()

        def holder():
            with record.recovery_lock(directory):
                held.set()
                time.sleep(0.4)

        thread = threading.Thread(target=holder)
        thread.start()
        try:
            self.assertTrue(held.wait(timeout=10))
            start = time.monotonic()
            record.stop_check(directory)
        finally:
            thread.join(timeout=10)
        self.assertGreaterEqual(time.monotonic() - start, 0.25,
                                "the spawn gate checked without the stop lock")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        with self.assertRaises(record.StopRequested):
            record.stop_check(directory)
        self.assertIsNone(record.stop_check(self.root / "no-such-run"))

    def test_done_when_aborts_on_a_stopped_record(self):
        run_id = "20260101-0900-stop-nogate"
        directory = self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        marker = self.root / "gate-marker"
        with self.assertRaises(record.StopRequested):
            gate.run_done_when(["touch %s" % marker], self.root,
                              directory / "donewhen.log", set(), 60,
                              run_dir=directory)
        self.assertFalse(marker.exists(), "a done-when command ran on a stopped run")

    def test_aborted_launch_drops_its_unrecorded_checkout(self):
        repo = self.repo()
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        wt, branch = run.make_worktree(repo, "20260101-0900-stop-orphan", "orphan", base)
        self.assertTrue(wt.is_dir())
        run.drop_unrecorded_checkout(repo, wt, branch, lambda _: None)
        self.assertFalse(wt.exists(), "the unrecorded worktree survived its abort")
        left = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "", "the unrecorded branch survived its abort")

    def test_settled_treats_a_stopped_review_as_done(self):
        from agentkit import watch as watch_mod
        run_id = "20260101-0900-stop-review"
        self.running(run_id)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        entry = {"sha": "abc123", "run": run_id, "at": time.time(), "attempts": 2}
        self.assertEqual(watch_mod.settled(entry), "done")

    def test_stopped_status_names_the_removed_branch(self):
        run_id = "20260101-0900-stop-gone-wording"
        directory = self.running(run_id, repo=str(self.root), branch="ak/gone-wording",
                                 worktree=str(self.root / "wt-gone"))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop([run_id]), 0)
        state = record.read_state(directory)
        self.assertEqual(state["state"], "stopped")
        lines = run.status_details(directory, state)
        workspace = next(line for line in lines if "workspace:" in line)
        self.assertIn("branch removed", workspace)
        self.assertNotIn("branch/PR retained", workspace)


if __name__ == "__main__":
    unittest.main(verbosity=2)
