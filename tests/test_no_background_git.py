"""Repository-local auto-gc suppression and the tick's daily, idle-only foreground git gc.

Offline: real throwaway repositories under HOME, traced git children and an injected process
inventory. No host process, seat, service, global config or remote is read or changed.
"""

from contextlib import redirect_stdout
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from fixtures.tick import only_passes
from agentkit import config, gc, gitcall, land, orch, record, watch

DAY = 86400
PID = 99999999


class NoBackgroundGit(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(self.root / ".gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@example.com",
            "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@example.com"}))
        self.global_config = self.root / ".gitconfig"
        self.global_config.write_text("[gc]\n\tauto = 1\n[maintenance]\n\tauto = true\n")
        self.original = self.global_config.read_bytes()
        self.repo = self.repository(config.CODE / "acme")
        self.processes = {}
        self.stack.enter_context(patch.object(record, "process_active",
            side_effect=lambda state: state.get("pid") in self.processes))
        self.stack.enter_context(patch.object(gc.retention, "process_dirs", return_value=[]))
        self.inventory = self.stack.enter_context(patch.object(
            gc.proc_snapshot, "collect", side_effect=lambda *_: (self.processes, [])))
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=({}, "offline")))
        self.logs = []

    def git(self, repo, *args, **kw):
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, **kw)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def repository(self, repo):
        repo.mkdir(parents=True)
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "commit", "--allow-empty", "-qm", "seed")
        return repo

    def worktree(self, name="fix-api", repo=None):
        tree, _ = gitcall.make_worktree(repo or self.repo, name, name, "main")
        return tree

    def tick(self, now=2 * DAY):
        with patch.object(gc.time, "time", return_value=now), \
                only_passes(self.root, "git housekeeping did not finish"), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(watch.main([]), 0)
        self.logs.extend(output.getvalue().splitlines())
        return output.getvalue()

    def mark(self, repo=None):
        dirs = orch.git_dirs(repo or self.repo)
        return dirs[0] / "ak-gc"

    def running(self):
        self.processes[PID] = {"uid": os.getuid(), "cwd": "/", "args": [], "paths": []}

    def test_a_runs_worktree_and_the_install_share_repository_settings(self):
        own = self.repository(self.root / "agentkit")
        for repo in (self.repo, own):
            tree = self.worktree(repo.name, repo)
            for checkout in (repo, tree):
                self.assertEqual(self.git(checkout, "config", "--local", "gc.auto"), "0")
                self.assertEqual(self.git(checkout, "config", "maintenance.auto"), "false")
        self.assertEqual(self.global_config.read_bytes(), self.original)

    def test_worktree_config_cannot_override_the_repository_housekeeping_policy(self):
        tree = self.worktree()
        self.git(self.repo, "config", "extensions.worktreeConfig", "true")
        for checkout in (self.repo, tree):
            self.git(checkout, "config", "--worktree", "gc.auto", "1")
            self.git(checkout, "config", "--worktree", "maintenance.auto", "true")
            gitcall.no_auto_gc(checkout)
            self.assertEqual(self.git(checkout, "config", "gc.auto"), "0")
            self.assertEqual(self.git(checkout, "config", "maintenance.auto"), "false")
        self.assertEqual(self.global_config.read_bytes(), self.original)

    def test_a_commit_above_the_auto_gc_threshold_starts_no_housekeeping_child(self):
        tree = self.worktree()
        # Git samples loose objects in bucket 17 for its auto-gc threshold.
        count, number = 0, 0
        while count < 4:
            data = f"loose object {number}".encode()
            number += 1
            if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()[:2] == "17":
                self.git(tree, "hash-object", "-w", "--stdin", input=data.decode())
                count += 1
        trace = self.root / "commit.jsonl"
        self.git(tree, "commit", "--allow-empty", "-qm", "past threshold",
                 env={**os.environ, "GIT_TRACE2_EVENT": str(trace)})
        children = [row["argv"] for row in map(json.loads, trace.read_text().splitlines())
                    if row.get("event") == "child_start"]
        self.assertFalse(any(word in ("gc", "maintenance", "reflog")
                             for argv in children for word in argv), children)
        # The same objects really do trigger collection when the old setting is restored;
        # autoDetach=false keeps this control entirely in the foreground.
        control = self.root / "control.jsonl"
        self.git(tree, "-c", "gc.auto=1", "-c", "gc.autoDetach=false", "gc", "--auto",
                 env={**os.environ, "GIT_TRACE2_EVENT": str(control)})
        children = [row["argv"] for row in map(json.loads, control.read_text().splitlines())
                    if row.get("event") == "child_start"]
        self.assertTrue(any("repack" in argv for argv in children), children)

    def test_the_tick_collects_each_idle_repository_once_a_day(self):
        own = self.repository(self.root / "agentkit")
        self.worktree()
        self.assertIn(f"git gc: {self.repo}", self.tick())
        self.assertIn(f"git gc: {own}", "\n".join(self.logs))
        for repo in (self.repo, own):
            self.assertEqual(float(self.mark(repo).read_text()), 2 * DAY)
        self.assertNotIn("git gc:", self.tick(3 * DAY - 1))
        self.assertIn(f"git gc: {self.repo}", self.tick(3 * DAY))
        self.assertEqual(self.global_config.read_bytes(), self.original)

    def test_no_daily_mark_means_due_even_during_the_first_day_of_the_clock(self):
        self.assertIn(f"git gc: {self.repo}", self.tick(10000))

    def test_inherited_git_environment_cannot_configure_or_collect_another_repository(self):
        other = self.repository(self.root / "other")
        with patch.dict(os.environ, {"GIT_DIR": str(other / ".git"),
                                     "GIT_WORK_TREE": str(other)}):
            gitcall.no_auto_gc(self.repo)
            self.assertIn(f"git gc: {self.repo}", self.tick())
        self.assertEqual(self.git(other, "config", "gc.auto"), "1")
        self.assertFalse(self.mark(other).exists())
        self.assertEqual(self.global_config.read_bytes(), self.original)

    def test_a_live_run_in_a_linked_worktree_defers_only_its_repository(self):
        tree = self.worktree()
        other = self.repository(config.CODE / "widgets")
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        record.save_state(directory, {"repo": str(tree), "worktree": str(tree),
                                      "state": "running", "pid": PID})
        self.running()
        self.assertNotIn(f"git gc: {self.repo}\n", self.tick())
        self.assertFalse(self.mark().exists())
        self.assertTrue(self.mark(other).exists())
        self.processes.clear()
        self.assertIn(f"git gc: {self.repo}", self.tick())
        self.assertNotIn("git gc:", self.tick())

    def test_a_live_seat_or_lander_defers_housekeeping_in_all_linked_worktrees(self):
        tree = self.worktree()
        with patch.object(orch, "sessions", return_value=[{"name": "builder", "path": str(tree)}]):
            self.tick()
        self.assertFalse(self.mark().exists())
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        turn = config.RUNS / ".merge-acme"
        record.save_state(directory, {"repo": str(self.repo), "worktree": str(tree),
                                      "state": "waiting", "waiting_on": {"line": turn.name}})
        land._keep_passes(turn, {"pid": PID, "started": DAY})
        self.running()
        self.tick()
        self.assertFalse(self.mark().exists())
        self.processes.clear()
        self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_a_process_in_a_scratch_worktree_holds_its_repository(self):
        tree = self.worktree()
        self.running()
        self.processes[PID]["cwd"] = str(tree / "subdirectory")
        self.tick()
        self.assertFalse(self.mark().exists())
        self.processes.clear()
        self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_a_seat_using_absolute_paths_from_code_holds_its_repository(self):
        self.running()
        self.processes[PID].update(cwd=str(config.CODE),
                                  paths=[str(self.repo / ".git" / "index")])
        with patch.object(orch, "sessions", return_value=[{"name": "builder", "path": str(config.CODE)}]):
            self.tick()
        self.assertFalse(self.mark().exists())
        self.processes.clear()
        self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_a_run_started_during_an_earlier_collection_holds_its_repository(self):
        other = self.repository(config.CODE / "widgets")
        real_run = subprocess.run

        def start(argv, **kw):
            if argv == ["git", "-C", str(self.repo), "gc"]:
                directory = config.RUNS / "fix-api"
                directory.mkdir()
                record.save_state(directory, {"repo": str(other), "state": "running", "pid": PID})
                self.running()
            return real_run(argv, **kw)

        with patch.object(gc.subprocess, "run", side_effect=start):
            self.tick()
        self.assertTrue(self.mark().exists())
        self.assertFalse(self.mark(other).exists())
        self.processes.clear()
        self.assertIn(f"git gc: {other}", self.tick())

    def test_preparation_and_collection_exclude_each_other_across_worktrees(self):
        tree = self.worktree()
        with gitcall.repository_lock(tree):
            self.tick()
        self.assertFalse(self.mark().exists())
        real_run = subprocess.run

        def collecting(argv, **kw):
            if argv == ["git", "-C", str(self.repo), "gc"]:
                directory = os.open(orch.git_dirs(tree)[0], os.O_RDONLY | os.O_DIRECTORY)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(directory, fcntl.LOCK_SH | fcntl.LOCK_NB)
                finally:
                    os.close(directory)
            return real_run(argv, **kw)

        with patch.object(gc.subprocess, "run", side_effect=collecting):
            self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_an_unreadable_process_inventory_is_no_proof_of_idle(self):
        self.inventory.side_effect = lambda *_: ({}, [PID])
        self.tick()
        self.assertFalse(self.mark().exists())
        self.inventory.side_effect = lambda *_: ({}, [])
        self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_a_failed_collection_waits_a_day_and_does_not_stop_other_repositories(self):
        other = self.repository(config.CODE / "widgets")
        real_run = subprocess.run

        def fail(argv, **kw):
            if argv == ["git", "-C", str(self.repo), "gc"]:
                return subprocess.CompletedProcess(argv, 1)
            return real_run(argv, **kw)

        with patch.object(gc.subprocess, "run", side_effect=fail):
            self.assertIn(f"WARN git gc failed in {self.repo}", self.tick())
            self.assertTrue(self.mark(other).exists())
        self.assertNotIn("git gc:", self.tick())
        self.assertIn(f"git gc: {self.repo}", self.tick(3 * DAY))

    def test_a_dry_tick_writes_neither_config_nor_collection_stamp(self):
        with only_passes(self.root, "git housekeeping did not finish"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main(["--dry-run"]), 0)
        self.assertEqual(self.git(self.repo, "config", "gc.auto"), "1")
        self.assertFalse(self.mark().exists())


if __name__ == "__main__":
    unittest.main()
