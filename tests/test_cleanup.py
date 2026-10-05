"""Stopping a session removes what it owns, and finished work does not wait a week.

Offline. Checkouts are tiny git repos under the test's own HOME. Pids are either
dead or this process, and nothing here signals a real unit or a foreign process.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import browser, config, gc, menu, orch, retention, run, worktrees, watch
from agentkit import record as run_record

DAY = 86400
DEAD = 99999999


class Cleanup(Sandbox):
    def setUp(self):
        # Sandbox pins menu.time.time at 10000, which is the time module. Ages of
        # more than a few hours would be negative, and retention ignores those.
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100"}))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "config", "user.email", "c@localhost")
        self.git(self.repo, "config", "user.name", "cleanup")
        (self.repo / "tracked").write_text("base\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "base")
        self.head = self.git(self.repo, "rev-parse", "HEAD")
        self.closed = []
        self.stack.enter_context(patch.object(
            browser, "close_tab", side_effect=lambda target: self.closed.append(target)))

    def git(self, repo, *args):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def branch_exists(self, branch):
        proc = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{branch}"], capture_output=True, text=True)
        return proc.returncode == 0

    def worktree(self, name):
        wt, branch = config.WT / name, "ak/" + name
        self.git(self.repo, "worktree", "add", "-q", str(wt), "-b", branch)
        return wt, branch

    def receipt(self, name, state="pass", owner=None, age=60, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        wt, branch = self.worktree(name)
        now = time.time()
        record = {"run_id": name, "title": name, "state": state, "verdict": "PASS",
                  "repo": str(self.repo), "worktree": str(wt), "branch": branch,
                  "base": "main", "delivery_sha": self.head, "merged": state == "pass",
                  "launched_session": owner, "started_at": now - age - 30,
                  "finished_at": None if state == "running" else now - age,
                  "pid": DEAD, "process_identity": None, "reported": True,
                  "round_summaries": [], "findings": "", "rounds": 1, **extra}
        if state == "running":
            record["verdict"] = None
            record["merged"] = False
        run_record.save_state(directory, record)
        (directory / "result.md").write_text("result\n")
        (directory / "task.md").write_text("task\n")
        (directory / "log.txt").write_text("log\n")
        return directory, wt, branch

    def seat(self, name):
        config.save_session(self.cfg, name, self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"],
                            {"cwd": str(self.root), "created": time.time()})

    def test_stop_removes_runs_worktrees_state_files_and_tabs(self):
        self.seat("atoll")
        for leaf in ("plan-atoll.md", "card-atoll.json", "hook-atoll.json", "notify-atoll.json",
                     "compact-atoll.json", "stop-atoll.json", "session-atoll.json",
                     "rulebook-atoll.md", "seat-atoll.lock", "notify-atoll.lock"):
            path = config.STATE / leaf
            if not path.exists():
                path.write_text("{}\n" if leaf.endswith(".json") else "plan\n")
        (config.STATE / "plan-other.md").write_text("keep\n")
        mine, mine_wt, mine_branch = self.receipt("mine", state="running", owner="atoll",
                                                  merged=False)
        done, done_wt, done_branch = self.receipt("done", state="pass", owner="atoll",
                                                  merged=False)
        other, other_wt, _ = self.receipt("other", state="running", owner="parser", merged=False)
        stored = {"tab-seat": {"opener": {"session": "atoll"}},
                  "tab-run": {"opener": {"run": "mine"}}}
        stored["tab-stray"] = {"first_seen": 1, "last_change": 1, "url": "https://x", "title": "x"}
        browser._write_tabs(stored)
        self.assertIn("and everything it is running", menu.stop_question("atoll"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop(["atoll"]), 0)
        self.assertEqual(run_record.read_state(mine)["state"], "stopped")
        self.assertEqual(run_record.read_state(done)["state"], "pass")
        self.assertEqual(run_record.read_state(other)["state"], "running")
        self.assertTrue(run_record.read_state(mine)["branch_removed"])
        self.assertTrue(run_record.read_state(done)["branch_removed"])
        self.assertNotIn("branch_removed", run_record.read_state(other))
        self.assertFalse(mine_wt.exists())
        self.assertFalse(done_wt.exists())
        self.assertTrue(other_wt.is_dir())
        self.assertFalse(self.branch_exists(mine_branch))
        self.assertFalse(self.branch_exists(done_branch))
        self.assertTrue((mine / "run.json").is_file())
        self.assertTrue((done / "result.md").is_file())
        for leaf in ("plan-atoll.md", "card-atoll.json", "hook-atoll.json", "notify-atoll.json",
                     "compact-atoll.json", "stop-atoll.json", "session-atoll.json",
                     "rulebook-atoll.md"):
            self.assertFalse((config.STATE / leaf).exists(), leaf)
        self.assertTrue((config.STATE / "plan-other.md").is_file())
        # Waiting writers and a reopened name must keep using the same lock inodes;
        # the daily gc takes unused locks and the stop mark.
        self.assertEqual({path.name for path in orch.session_owned_files("atoll")},
                         {"seat-atoll.json", "seat-atoll.lock", "notify-atoll.lock"})
        seat = watch.seat_read("atoll")
        self.assertTrue(seat.get("closed_by_owner"))
        self.assertTrue(seat.get("stopped_at"))
        self.assertEqual(sorted(self.closed), ["tab-run", "tab-seat"])
        left = browser._read_tabs()
        self.assertEqual(list(left), ["tab-stray"])

    def test_merged_run_worktree_is_gone(self):
        directory, wt, branch = self.receipt("merged", state="pass", merged=True, age=60)
        state = run_record.read_state(directory)
        with redirect_stdout(io.StringIO()):
            worktrees.settle_run(state, directory, lambda _message: None)
        self.assertFalse(wt.exists())
        self.assertFalse(self.branch_exists(branch))
        for name in ("result.md", "run.json", "task.md"):
            self.assertTrue((directory / name).is_file(), name)
        # A second merged checkout the loop did not reach is collected on the first pass,
        # not after a week.
        leftover, left_wt, _ = self.receipt("leftover", state="pass", merged=True, age=60)
        self.assertIn(str(left_wt), {item["path"] for item in gc.gc_plan()})
        self.assertIn(str(left_wt), gc.gc(lambda _message: None))
        self.assertFalse(left_wt.exists())
        self.assertTrue((leftover / "result.md").is_file())

    def test_failed_run_worktree_is_gone_after_handback(self):
        directory, wt, branch = self.receipt("failed", state="fail", merged=False, age=60,
                                             owner="seat", verdict="FAIL")
        state = run_record.read_state(directory)
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(watch, "type_at_prompt", return_value=True), \
                patch.object(watch, "is_preexisting", return_value=False), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(run.hand_back(state, directory, lambda _message: None))
        self.assertFalse(wt.exists(), "the checkout survived the hand-back")
        # The run never pushed, so the branch is the only copy of its commits.
        self.assertTrue(self.branch_exists(branch))
        self.assertTrue((directory / "result.md").is_file())
        # Not yet told, and younger than a week: the tree stays.
        waiting, waiting_wt, _ = self.receipt("waiting", state="fail", merged=False, age=DAY)
        self.assertNotIn(str(waiting_wt), {item["path"] for item in gc.gc_plan()})
        self.assertTrue(waiting_wt.is_dir())
        # A week without a hand-back is the other clock. The branch stays there too.
        aged, aged_wt, aged_branch = self.receipt("aged", state="fail", merged=False,
                                                 age=8 * DAY)
        self.assertIn(str(aged_wt), {item["path"] for item in gc.gc_plan()})
        gc.gc(lambda _message: None)
        self.assertFalse(aged_wt.exists())
        self.assertTrue(self.branch_exists(aged_branch))
        self.assertTrue((aged / "run.json").is_file())
        self.assertTrue(waiting_wt.is_dir())

    def test_resumable_fail_keeps_its_tree_until_the_week_is_out(self):
        # A FAIL at its round budget is the scheduler's own resume, and `ak run
        # status` prints its `continue:` line: the hand-back must not take the
        # checkout either of them needs.
        summaries = [{"verdict": "FAIL", "done_when": "python3 tests/test_x.py",
                      "head_sha": self.head}]
        directory, wt, branch = self.receipt("budget", state="fail", merged=False, age=60,
                                             owner="seat", verdict="FAIL",
                                             round_summaries=summaries)
        state = run_record.read_state(directory)
        self.assertIn("ak run resume budget --rounds 3",
                      run.continue_line(state, directory))
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(watch, "type_at_prompt", return_value=True), \
                patch.object(watch, "is_preexisting", return_value=False), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(run.hand_back(state, directory, lambda _message: None))
        self.assertTrue(wt.is_dir(), "the hand-back took the resume's checkout")
        self.assertNotIn(str(wt), {item["path"] for item in gc.gc_plan()})
        self.assertIn("ak run resume budget --rounds 3",
                      run.continue_line(run_record.read_state(directory), directory))
        # The seven-day clock still takes it; the branch stays regardless.
        old, old_wt, old_branch = self.receipt("budget-old", state="fail", merged=False,
                                               age=8 * DAY, verdict="FAIL",
                                               round_summaries=summaries)
        self.assertIn(str(old_wt), {item["path"] for item in gc.gc_plan()})
        gc.gc(lambda _message: None)
        self.assertFalse(old_wt.exists())
        self.assertTrue(self.branch_exists(old_branch))
        self.assertTrue((old / "result.md").is_file())

    def test_live_run_worktree_is_never_removed(self):
        directory, wt, _ = self.receipt("live", state="running", merged=False)
        state = run_record.read_state(directory)
        state.update(run_record.process_owner())
        run_record.save_state(directory, state)
        self.assertEqual(gc.gc(lambda _message: None), [])
        worktrees.settle_run(state, directory, lambda _message: None)
        worktrees.drop_checkout(state, lambda _message: None)
        self.assertTrue(wt.is_dir())
        # A finished run whose checkout is under ~/code is not collected either.
        owned = config.CODE / "proj"
        owned.mkdir(parents=True)
        (owned / "keep").write_text("owner\n")
        code_dir, _, _ = self.receipt("code", state="pass", merged=True, age=60)
        current = run_record.read_state(code_dir)
        current["worktree"] = str(owned)
        current["repo"] = str(owned)
        run_record.save_state(code_dir, current)
        gc.gc(lambda _message: None)
        worktrees.drop_checkout(current, lambda _message: None)
        self.assertEqual((owned / "keep").read_text(), "owner\n")

    def test_clean_leaves_a_live_or_owned_checkout_and_says_why(self):
        # `ak run clean` takes the same guarded way out as a stop: never a tree under a
        # loop that may still be going, never anything under ~/code
        directory, wt, _ = self.receipt("going", state="running", pid="scheduler")
        with self.assertRaisesRegex(config.Error, "the run is still going"):
            run.cmd_clean(["going"])
        self.assertTrue(wt.is_dir())
        owned = config.CODE / "proj"
        owned.mkdir(parents=True)
        (owned / "keep").write_text("owner\n")
        directory, _, _ = self.receipt("owned", state="stopped")
        state = run_record.read_state(directory)
        state["worktree"] = str(owned)
        run_record.save_state(directory, state)
        with self.assertRaisesRegex(config.Error, "under"):
            run.cmd_clean(["owned"])
        self.assertEqual((owned / "keep").read_text(), "owner\n")

    def test_a_checkout_git_no_longer_lists_still_goes(self):
        # its registration pruned, or its repo cloned afresh: the tree is the run's own
        # under ~/.agentkit/wt, so it goes as a directory, and nothing is reported left
        directory, wt, branch = self.receipt("unlisted", state="stopped")
        shutil.rmtree(self.repo / ".git" / "worktrees" / "unlisted")
        told = []
        self.assertTrue(worktrees.stop_checkout(run_record.read_state(directory), told.append))
        self.assertFalse(wt.exists())
        self.assertFalse(self.branch_exists(branch))
        self.assertEqual(told, [])

    def test_repo_under_code_still_loses_worktree_and_branch(self):
        # Every real repo lives under ~/code; only the worktree being deleted
        # is guarded, never the repo git runs in.
        repo = config.CODE / "proj"
        repo.mkdir(parents=True)
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "user.email", "c@localhost")
        self.git(repo, "config", "user.name", "cleanup")
        (repo / "tracked").write_text("base\n")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        wt = config.WT / "coded"
        branch = "ak/coded"
        self.git(repo, "worktree", "add", "-q", str(wt), "-b", branch)
        now = time.time()
        state = {"run_id": "coded", "state": "pass", "verdict": "PASS",
                 "repo": str(repo), "worktree": str(wt), "branch": branch,
                 "merged": True, "started_at": now - 90, "finished_at": now - 60,
                 "pid": DEAD, "process_identity": None}
        worktrees.drop_checkout(state, lambda _message: None)
        self.assertFalse(wt.exists())
        left = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{branch}"],
                              capture_output=True, text=True)
        self.assertNotEqual(left.returncode, 0)
        self.assertEqual((repo / "tracked").read_text(), "base\n")

    def test_stop_matches_only_known_seat_file_kinds(self):
        # Stopping `fix` must not take a live sibling's `session-atoll-fix.json`,
        # and no seat owns the browser's tabs, a usage reset or a preview record.
        config.ensure_dirs()
        for leaf in ("session-atoll-fix.json", "seat-atoll-fix.json", "hook-atoll-fix.json",
                     "browser-tabs.json", "claude-reset.json", "preview-repo.json",
                     "installed-at", "session-fix.json", "hook-fix.json", "rulebook-fix.md"):
            (config.STATE / leaf).write_text("{}\n")
        owned = {path.name for path in orch.session_owned_files("fix")}
        self.assertEqual(owned, {"session-fix.json", "hook-fix.json", "rulebook-fix.md"})
        sibling = {path.name for path in orch.session_owned_files("atoll-fix")}
        self.assertEqual(sibling, {"session-atoll-fix.json", "seat-atoll-fix.json",
                                   "hook-atoll-fix.json"})
        self.assertEqual(orch.session_owned_files("tabs"), [])
        self.assertEqual(orch.session_owned_files("reset"), [])

    def test_gc_takes_a_gone_seats_files_a_day_later(self):
        # A seat tmux lost, or one `orch.sweep` retired, leaves its files; so does the stop
        # mark. A day after the last write, with no record left, gc takes every one of them.
        def left(name, age):
            path = config.STATE / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n")
            os.utime(path, (time.time() - age, time.time() - age))
            return path

        self.seat("living")
        self.seat("atoll.v2")          # a name may hold a dot; the extension is the last one
        gone = [left(name, 2 * DAY) for name in (
            "rulebook-old-seat.md", "seat-old-seat.json", "seat-old-seat.lock",
            "notify-old-seat.lock", "compact-old-seat.json", "plan-old-seat.md",
            "notify-host.json", "seat-old.v1.json")]
        stamp = left("idle-compact/99999999.json", 2 * DAY)
        kept = [left(name, 2 * DAY) for name in (
            "plan-living.md", "hook-living.json", "seat-held.json", "browser-tabs.json",
            "openai-reset.json", "usage-meta-probe.json", "codex-launch-abc.json",
            f"idle-compact/{os.getpid()}.json", "idle-compact/log",
            "rulebook-atoll.v2.md", "seat-atoll.v2.json")]
        kept.append(self.aged(config.session_path("atoll.v2"), 2 * DAY))
        kept += [left("seat-young.json", 3600), left("idle-compact/99999998.json", 3600)]
        # a gone seat that still owns a running run keeps the mark its hand-back reads
        self.receipt("held-run", state="running", owner="held")
        dry = self.gc_out("--dry-run")
        for path in gone:
            self.assertIn(f"gc: would remove seat-file {path}: seat ", dry)
        self.assertIn("gc: would remove seat-file "
                      f"{config.STATE / 'rulebook-old-seat.md'}: seat old-seat is gone", dry)
        self.assertIn(f"{config.STATE / 'seat-old.v1.json'}: seat old.v1 is gone", dry)
        self.assertIn(f"gc: would remove compact-stamp {stamp}: its wrapper, pid 99999999, "
                      "is gone", dry)
        removed = set(gc.gc(lambda _message: None))
        self.assertEqual(removed, {str(path) for path in gone + [stamp]})
        for path in kept:
            self.assertTrue(path.exists(), path)
        self.assertEqual(gc.gc(lambda _message: None), [])

    def aged(self, path, age):
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def gc_out(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(gc.cmd_gc(list(argv)), 0)
        return out.getvalue()

    def test_stop_says_kept_when_the_checkout_stays(self):
        # A pid the stop cannot prove dead -- a job task still under its live
        # scheduler -- leaves the worktree and the branch, so the line must say
        # kept, and the record must agree for the status row that reads it later.
        directory, wt, branch = self.receipt("task", state="running", owner="atoll",
                                             pid="scheduler", process_identity=None)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["task"]), 0)
        self.assertIn(f"kept; relaunch with from: {branch}", out.getvalue())
        self.assertTrue(wt.is_dir())
        self.assertTrue(self.branch_exists(branch))
        self.assertTrue(run_record.read_state(directory)["stop_kept"])

    def test_a_branch_git_keeps_is_reported_kept(self):
        # a branch another checkout holds outlives `git branch -D`: the stop says kept and
        # names the relaunch line, and the record agrees, so a later stop tries again
        directory, wt, branch = self.receipt("held", state="running")
        self.git(self.repo, "worktree", "add", "-q", str(self.root / "holder"), branch,
                 "--force")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["held"]), 0)
        self.assertFalse(wt.exists())
        self.assertTrue(self.branch_exists(branch))
        self.assertIn(f"kept; relaunch with from: {branch}", out.getvalue())
        self.assertTrue(run_record.read_state(directory)["stop_kept"])

    def test_a_branch_lookup_that_times_out_is_reported_kept(self):
        # a git that never said whether the branch is there has not removed it: the stop
        # finishes, says kept, and the record agrees
        directory, wt, branch = self.receipt("slow-ref", state="running")
        real = run.tool_run

        def timed_out(cmd, *args, **kwargs):
            if cmd[3:4] == ["rev-parse"] and cmd[-1] == f"refs/heads/{branch}":
                return None, "", "git rev-parse timed out"
            return real(cmd, *args, **kwargs)
        out = io.StringIO()
        with patch.object(run, "tool_run", side_effect=timed_out), redirect_stdout(out):
            self.assertEqual(run.cmd_stop(["slow-ref"]), 0)
        self.assertFalse(wt.exists())
        self.assertTrue(self.branch_exists(branch))
        self.assertIn(f"kept; relaunch with from: {branch}", out.getvalue())
        self.assertTrue(run_record.read_state(directory)["stop_kept"])

    def test_changed_files_survive_the_removed_checkout(self):
        # history reads the changed files after the merge took the tree: the
        # delivery sha names the same tip in the repo the branch pointed at
        directory, wt, branch = self.receipt("changed", state="pass", merged=True, age=60)
        (wt / "shipped.txt").write_text("done\n")
        self.git(wt, "add", ".")
        self.git(wt, "commit", "-qm", "ship")
        tip = self.git(wt, "rev-parse", "HEAD")
        state = run_record.read_state(directory)
        state.update(base_sha=self.head, delivery_sha=tip)
        run_record.save_state(directory, state)
        worktrees.settle_run(run_record.read_state(directory), directory, lambda _message: None)
        self.assertFalse(wt.exists())
        self.assertFalse(self.branch_exists(branch))
        self.assertEqual(run.changed_files(run_record.read_state(directory)), ["shipped.txt"])

    def test_clean_names_the_gone_scratch_workspace(self):
        directory = config.RUNS / "cleaned"
        directory.mkdir(parents=True)
        run_record.save_state(directory, {"run_id": "cleaned", "state": "pass", "verdict": "PASS",
                                   "scratch": True,
                                   "worktree": str(config.WORK / "cleaned")})
        (directory / "result.md").write_text("result\n")
        (directory / "task.md").write_text("task\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_clean(["cleaned"]), 0)
        self.assertIn("its workspace is gone", out.getvalue())

    def test_a_scratch_workspace_outlives_every_ending_and_goes_with_its_run(self):
        # its files are the delivery: the ending, the hand-back, `ak run clean` and the
        # seat's stop all leave them where they are, even a month on, while the living
        # seat keeps the run directory from the collector
        self.seat("atoll")
        now = time.time()
        runs = []
        for name, state in (("made", "pass"), ("missed", "fail")):
            directory, work = config.RUNS / name, config.WORK / name
            directory.mkdir(parents=True)
            work.mkdir(parents=True)
            (work / "crosscheck.md").write_text("33 KB of findings\n")
            run_record.save_state(directory, {"run_id": name, "title": name, "state": state,
                                       "verdict": state.upper(), "scratch": True, "repo": None,
                                       "worktree": str(work), "launched_session": "atoll",
                                       "started_at": now - 31 * DAY - 90,
                                       "finished_at": now - 31 * DAY,
                                       "handed_back": now, "pid": DEAD,
                                       "process_identity": None, "round_summaries": [],
                                       "rounds": 1})
            worktrees.settle_run(run_record.read_state(directory), directory, lambda _message: None)
            worktrees._drop_told(run_record.read_state(directory), lambda _message: None, directory)
            runs.append((directory, work))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_clean(["made"]), 0)
        gc.gc(lambda _message: None)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop(["atoll"]), 0)
        for directory, work in runs:
            self.assertTrue((directory / "run.json").is_file(), directory)
            self.assertTrue((work / "crosscheck.md").is_file(), work)
        # with the seat gone, the collector takes each workspace with its run directory
        gc.gc(lambda _message: None)
        for directory, work in runs:
            self.assertFalse(directory.exists())
            self.assertFalse(work.exists())

    def test_31_day_run_directory_is_collected(self):
        directory, _, branch = self.receipt("ancient", state="pass", merged=False,
                                            age=31 * DAY, launched_session=None)
        self.assertIn(str(directory), {item["path"] for item in gc.gc_plan()})
        gc.gc(lambda _message: None)
        self.assertFalse(directory.exists())
        # oblivion takes the branch with the record: nothing points at it anymore
        self.assertFalse(self.branch_exists(branch))

    def test_living_session_run_directory_is_kept(self):
        self.seat("living")
        directory, _, _ = self.receipt("kept", state="pass", merged=True, age=31 * DAY,
                                       owner="living")
        self.assertNotIn(str(directory), {item["path"] for item in gc.gc_plan()})
        gc.gc(lambda _message: None)
        self.assertTrue((directory / "result.md").is_file())
        self.assertTrue((directory / "run.json").is_file())

    def test_tmp_older_than_a_day_goes(self):
        def ephemeral(name, age, live=False):
            path = config.TMP / name
            path.mkdir()
            (path / "fixture").write_text("temp\n")
            self.assertTrue(retention.begin(path, "smoke"))
            record = retention.read_json(retention.marker(path))
            record["created_at"] = time.time() - age
            record["finished_at"] = time.time() - age
            if live:
                record.update(run_record.process_owner())
            else:
                record.update(pid=DEAD, process_identity=None)
            retention.marker(path).write_text(json.dumps(record))
            now = time.time()
            for item in (path, path / "fixture", retention.marker(path)):
                os.utime(item, (now - age, now - age))
            return path

        old = ephemeral("old-smoke", 2 * DAY)
        young = ephemeral("young-smoke", 3600)
        held = ephemeral("held-smoke", 2 * DAY, live=True)
        removed = set(gc.gc(lambda _message: None))
        self.assertIn(str(old), removed)
        self.assertFalse(old.exists())
        self.assertTrue(young.is_dir())
        self.assertTrue(held.is_dir())

    def test_tab_opened_by_a_run_closes_when_it_ends(self):
        directory, wt, _ = self.receipt("ended", state="pass", merged=True, age=60)
        stored = {"tab-ended": {"opener": {"run": "ended"}}}
        stored["tab-other"] = {"first_seen": 1, "last_change": 1, "url": "https://y", "title": "y"}
        browser._write_tabs(stored)
        state = run_record.read_state(directory)
        worktrees.settle_run(state, directory, lambda _message: None)
        self.assertIn("tab-ended", self.closed)
        self.assertNotIn("tab-other", self.closed)
        self.assertEqual(list(browser._read_tabs()), ["tab-other"])
        self.assertFalse(wt.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
