"""`ak run gc` sweeps every merged run's worktree, and the smoke suite leaves no sandbox behind.

Offline. Checkouts are tiny git repos under the test's own HOME, and nothing here touches
the real ~/.agentkit. Pids are either dead or this process; nothing signals anything.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, orch, retention, run

DAY = 86400
DEAD = 99999999


class GcSweep(Sandbox):
    def setUp(self):
        # Sandbox pins menu.time.time at 10000, which is the time module. Ages of
        # more than a few hours would be negative, and retention ignores those.
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100"}))
        self.repo = self.make_repo("repo")
        self.other = self.make_repo("other")

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "user.email", "s@localhost")
        self.git(repo, "config", "user.name", "sweep")
        (repo / "tracked").write_text("base\n")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def git(self, repo, *args):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def listed(self, repo):
        return self.git(repo, "worktree", "list", "--porcelain")

    def branch_exists(self, repo, branch):
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{branch}"], capture_output=True, text=True)
        return proc.returncode == 0

    def receipt(self, name, repo, state="pass", merged=True, dirty=False, **extra):
        """A merged run's record and checkout; `dirty` leaves the untracked output a
        real merged worktree tends to hold, which the collector's proof refuses."""
        directory, wt, branch = config.RUNS / name, config.WT / name, "ak/" + name
        directory.mkdir(parents=True)
        self.git(repo, "worktree", "add", "-q", str(wt), "-b", branch)
        if dirty:
            (wt / "stray.txt").write_text("left behind\n")
            (wt / "build").mkdir()
            (wt / "build" / "out.o").write_bytes(b"\0" * 4096)
        now = time.time()
        record = {"run_id": name, "title": name, "state": state, "verdict": "PASS",
                  "repo": str(repo), "worktree": str(wt), "branch": branch, "base": "main",
                  "delivery_sha": self.git(repo, "rev-parse", "HEAD"), "merged": merged,
                  "launched_session": None, "started_at": now - 90, "finished_at": now - 60,
                  "pid": DEAD, "process_identity": None, "reported": True, "rounds": 1, **extra}
        run.save_state(directory, record)
        (directory / "result.md").write_text("result\n")
        (directory / "task.md").write_text("task\n")
        (directory / "log.txt").write_text("log\n")
        return directory, wt, branch

    def sandbox(self, name, finished=True, live=False, age=60):
        """A smoke sandbox with its receipt: signed off or not, its writer dead or this
        process, and every timestamp `age` seconds back."""
        path = config.TMP / name
        path.mkdir()
        (path / "fixture").write_text("temp\n")
        self.assertTrue(retention.begin(path, "smoke"))
        record = retention.read_json(retention.marker(path))
        record["created_at"] = time.time() - age
        if finished:
            record["finished_at"] = time.time() - age
        record.update(run.process_owner() if live else {"pid": DEAD, "process_identity": None})
        retention.marker(path).write_text(json.dumps(record))
        now = time.time()
        for item in (path, path / "fixture", retention.marker(path)):
            os.utime(item, (now - age, now - age))
        return path

    def gc(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_gc(list(argv)), 0)
        return out.getvalue()

    def test_merged_worktree_in_a_second_repo_is_removed(self):
        first, first_wt, first_branch = self.receipt("first", self.repo, dirty=True)
        second, second_wt, second_branch = self.receipt("second", self.other, dirty=True)
        unmerged, unmerged_wt, _ = self.receipt("unmerged", self.other, merged=False)
        running, running_wt, _ = self.receipt("running", self.other, state="running")
        # The collector's proof leaves a dirty tree; the sweep takes it, in either repo.
        self.assertNotIn(str(second_wt), {item["path"] for item in run.gc_plan()})
        self.assertEqual({item["path"] for item in run.sweep_plan()},
                         {str(first_wt), str(second_wt)})
        dry = self.gc("--dry-run")
        self.assertIn(f"gc: would remove merged-worktree {second_wt}", dry)
        self.assertTrue(second_wt.is_dir())
        out = self.gc()
        for wt in (first_wt, second_wt):
            self.assertFalse(wt.exists(), wt)
            self.assertIn(f"gc: remove merged-worktree {wt}", out)
        self.assertNotIn(str(second_wt), self.listed(self.other))
        self.assertFalse(self.branch_exists(self.other, second_branch))
        self.assertFalse(self.branch_exists(self.repo, first_branch))
        self.assertRegex(out, r"gc: removed 2 merged worktrees and 0 smoke sandboxes, "
                              r"[0-9.]+ [kMG]?B freed")
        for directory in (first, second):
            self.assertTrue((directory / "result.md").is_file())
            self.assertTrue((directory / "run.json").is_file())
        # A pass that did not merge, and a run still going, keep their trees.
        self.assertTrue(unmerged_wt.is_dir())
        self.assertTrue(running_wt.is_dir())
        self.assertIn("no eligible artifacts", self.gc())

    def test_unregistered_directory_is_removed_and_pruned(self):
        directory, wt, branch = self.receipt("orphan", self.repo)
        # git forgot the checkout, the way a repo cloned afresh forgets every old one
        shutil.rmtree(self.repo / ".git" / "worktrees" / "orphan")
        self.assertNotIn(str(wt), self.listed(self.repo))
        self.assertTrue(wt.is_dir())
        self.assertNotIn(str(wt), {item["path"] for item in run.gc_plan()})
        # and a registration whose directory already went is what the prune is for
        stale, stale_wt, _ = self.receipt("stale", self.repo)
        shutil.rmtree(stale_wt)
        self.assertIn(str(stale_wt), self.listed(self.repo))
        out = self.gc()
        self.assertFalse(wt.exists())
        self.assertIn(f"gc: remove merged-worktree {wt}", out)
        self.assertIn("removed 1 merged worktree and 0 smoke sandboxes", out)
        self.assertNotIn(str(stale_wt), self.listed(self.repo))
        self.assertFalse(self.branch_exists(self.repo, branch))
        self.assertTrue((directory / "result.md").is_file())
        self.assertEqual((self.repo / "tracked").read_text(), "base\n")
        self.assertIn("no eligible artifacts", self.gc())

    def test_passed_suite_leaves_no_sandbox(self):
        own = self.sandbox("smoke-20260922-100000", finished=False)
        older = self.sandbox("smoke-20260922-090000")
        self.assertTrue(retention.settle(own, True))
        self.assertFalse(own.exists())
        # a pass takes only its own: the newest failed sandbox is somebody's to read
        self.assertTrue(older.is_dir())
        # The trap hands the suite's exit status to this entry point, and nothing else.
        text = (config.REPO / "tests" / "smoke.sh").read_text()
        self.assertIn("trap 'SMOKE_RC=$?", text)
        self.assertIn('python3 -m agentkit.retention settle "$WORK" "$SMOKE_RC"', text)
        self.assertNotIn("retention finish", text)
        home = self.root / "cli-home"
        box = home / ".agentkit" / "tmp" / "smoke-20260922-110000"
        box.mkdir(parents=True)
        (box / "fixture").write_text("temp\n")
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(config.REPO)}
        subprocess.run([sys.executable, "-m", "agentkit.retention", "begin", str(box),
                        "smoke", str(os.getpid())], env=env, check=True)
        subprocess.run([sys.executable, "-m", "agentkit.retention", "settle", str(box), "0"],
                       env=env, check=True)
        self.assertFalse(box.exists())
        self.assertTrue((home / ".agentkit" / "tmp").is_dir())

    def test_failed_sandbox_is_kept_once_and_an_older_one_goes(self):
        older = self.sandbox("smoke-20260922-090000")
        killed = self.sandbox("smoke-20260922-093000", finished=False)
        live = self.sandbox("smoke-20260922-094000", finished=False, live=True)
        bare = config.TMP / "smoke-20260922-095000"
        bare.mkdir()
        newer = self.sandbox("smoke-20260922-120000")
        own = self.sandbox("smoke-20260922-100000", finished=False)
        self.assertTrue(retention.settle(own, False))
        self.assertTrue(own.is_dir())
        self.assertTrue(retention.read_json(retention.marker(own))["finished_at"])
        # an older suite that signed off, or died, goes; a live one, one with no
        # receipt, and a later one are not this suite's to take
        self.assertFalse(older.exists())
        self.assertFalse(killed.exists())
        self.assertTrue(live.is_dir())
        self.assertTrue(bare.is_dir())
        self.assertTrue(newer.is_dir())
        # the next failure keeps its own and takes this one: one failed sandbox, the newest
        later = self.sandbox("smoke-20260922-130000", finished=False)
        self.assertTrue(retention.settle(later, False))
        self.assertFalse(own.exists())
        self.assertTrue(later.is_dir())
        # the same call through the trap's entry point, with a failing status
        env = {**os.environ, "HOME": str(self.root), "PYTHONPATH": str(config.REPO)}
        home_box = self.root / ".agentkit" / "tmp" / "smoke-20260922-140000"
        home_box.mkdir(parents=True)
        subprocess.run([sys.executable, "-m", "agentkit.retention", "settle", str(home_box), "1"],
                       env=env, check=True)
        self.assertTrue(home_box.is_dir())

    def test_gc_takes_day_old_sandboxes_and_says_what_it_freed(self):
        old = self.sandbox("smoke-old", age=2 * DAY)
        killed = self.sandbox("smoke-killed", finished=False, age=2 * DAY)
        bare = config.TMP / "smoke-bare"
        bare.mkdir()
        (bare / "fixture").write_bytes(b"\0" * 8192)
        for item in (bare, bare / "fixture"):
            os.utime(item, (time.time() - 2 * DAY, time.time() - 2 * DAY))
        young = self.sandbox("smoke-young", age=3600)
        live = self.sandbox("smoke-live", finished=False, live=True, age=2 * DAY)
        other = config.TMP / "update-old.log"
        other.write_text("stream\n")
        os.utime(other, (time.time() - 2 * DAY, time.time() - 2 * DAY))
        dry = self.gc("--dry-run")
        for path in (old, killed, bare):
            self.assertIn(f"gc: would remove smoke-sandbox {path}", dry)
            self.assertTrue(path.is_dir())
        for path in (young, live):
            self.assertNotIn(str(path), dry)
        out = self.gc()
        for path in (old, killed, bare):
            self.assertFalse(path.exists(), path)
        for path in (young, live, other):
            self.assertTrue(path.exists(), path)
        self.assertRegex(out, r"gc: removed 0 merged worktrees and 3 smoke sandboxes, "
                              r"[0-9.]+ [kMG]?B freed")
        self.assertNotIn("no eligible", out)

    def aged(self, path, age):
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_gc_takes_orphan_and_unmerged_worktrees_with_their_reasons(self):
        # A smoke suite's checkout whose repo and record both went with the sandbox.
        sandbox = self.make_repo("sandbox-repo")
        smoke = config.WT / "20260904-2106-smoke-make-hello-pass"
        self.git(sandbox, "worktree", "add", "-q", str(smoke), "-b", "ak/smoke")
        shutil.rmtree(sandbox)
        self.aged(smoke, 2 * DAY)
        # One registered in a repo that is still here, with no run record either.
        stray = config.WT / "stray"
        self.git(self.repo, "worktree", "add", "-q", str(stray), "-b", "ak/stray")
        self.aged(stray, 2 * DAY)
        fresh = config.WT / "fresh"
        self.git(self.repo, "worktree", "add", "-q", str(fresh), "-b", "ak/fresh")
        # A run directory that never got its run.json is no record either; one whose record
        # is being written, or cannot be read, still is.
        bare, writing, unreadable = (config.WT / name for name in ("bare", "writing", "unreadable"))
        for wt in (bare, writing, unreadable):
            self.git(self.repo, "worktree", "add", "-q", str(wt), "-b", "ak/" + wt.name)
            (config.RUNS / wt.name).mkdir()
            (config.RUNS / wt.name / "task.md").write_text("task\n")
        (config.RUNS / "writing" / "run.tmp").write_text("{")
        (config.RUNS / "unreadable" / "run.json").write_text("{")
        for wt in (bare, writing, unreadable):
            self.aged(wt, 2 * DAY)
            self.aged(config.RUNS / wt.name, 2 * DAY)
        # Passed, its merge refused, and a week and a day since: the tree goes, the branch stays.
        failed_merge = dict(merged=False, merge_failed=True,
                            merge_note="required checks failed; the PR is open at x",
                            finished_at=time.time() - 8 * DAY)
        refused, refused_wt, refused_branch = self.receipt("refused", self.repo, **failed_merge)
        # --no-merge ends a delivery without a merge too.
        unasked, unasked_wt, _ = self.receipt("unasked", self.other, merged=False, no_merge=True,
                                              finished_at=time.time() - 9 * DAY)
        recent, recent_wt, _ = self.receipt("recent", self.repo,
                                            **{**failed_merge, "finished_at": time.time() - DAY})
        # A pass whose delivery never ended is the one `ak run resume` still delivers.
        pending, pending_wt, _ = self.receipt("pending", self.other, merged=False,
                                              finished_at=time.time() - 20 * DAY)
        dry = self.gc("--dry-run")
        self.assertIn(f"gc: would remove orphan-worktree {smoke}: no run record", dry)
        self.assertIn(f"gc: would remove orphan-worktree {stray}: no run record", dry)
        self.assertIn(f"gc: would remove orphan-worktree {bare}: no run record", dry)
        self.assertIn(f"gc: would remove unmerged-worktree {refused_wt}: passed, never merged, "
                      "ended 8 days ago", dry)
        self.assertIn(f"gc: would remove unmerged-worktree {unasked_wt}: passed, never merged, "
                      "ended 9 days ago", dry)
        for wt in (fresh, recent_wt, pending_wt, writing, unreadable):
            self.assertNotIn(str(wt), dry)
        out = self.gc()
        for wt in (smoke, stray, bare, refused_wt, unasked_wt):
            self.assertFalse(wt.exists(), wt)
        self.assertIn(f"gc: remove unmerged-worktree {refused_wt}: passed, never merged", out)
        self.assertNotIn(str(stray), self.listed(self.repo))
        self.assertNotIn(str(refused_wt), self.listed(self.repo))
        self.assertTrue(self.branch_exists(self.repo, refused_branch))
        for directory in (refused, unasked):
            self.assertTrue((directory / "result.md").is_file())
        for wt in (fresh, recent_wt, pending_wt, writing, unreadable):
            self.assertTrue(wt.is_dir(), wt)
        self.assertIn("no eligible artifacts", self.gc())

    def test_a_tree_gc_cannot_take_is_reported_once_and_never_again(self):
        if os.geteuid() == 0:
            self.skipTest("root removes a read-only directory")
        # Root's files from a container build: this user cannot empty that directory.
        wt = config.WT / "20260907-0101-root-owned-build"
        locked = self.locked_tree(wt)
        (wt / "src").mkdir()
        (wt / "src" / "ours").write_text("ours\n")
        for path in (wt / "src" / "ours", wt / "src", wt / "build", wt):
            self.aged(path, 2 * DAY)
        out = self.gc()
        self.assertEqual(out.count(f"gc: left {wt}: "), 1, out)
        self.assertIn(f"`sudo rm -rf {wt}` takes them", out)
        self.assertFalse((wt / "src").exists())     # what this user owns is gone already
        self.assertTrue((locked / "layer").exists())
        self.assertIn(str(wt), run.leftovers())
        # The next day's pass neither lists it nor tries it again.
        self.assertNotIn(str(wt), self.gc("--dry-run"))
        self.assertNotIn(str(wt), self.gc())
        self.assertEqual(run.gc(lambda _message: None, automatic=True), [])

    def locked_tree(self, wt):
        """A directory this user cannot empty inside `wt`, the way root's build output is."""
        locked = wt / "build" / "cache"
        locked.mkdir(parents=True)
        (locked / "layer").write_text("root's\n")
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        return locked

    def test_an_unmerged_tree_goes_only_under_its_runs_recovery_lock(self):
        failed_merge = dict(merged=False, merge_failed=True, merge_note="PR is closed",
                            finished_at=time.time() - 8 * DAY)
        directory, wt, _ = self.receipt("locked", self.repo, **failed_merge)
        held, clear = [], run.clear_tree
        def watched(tree, report):
            held.append(str(directory) in getattr(run._RECOVERY_HELD, "paths", set()))
            return clear(tree, report)
        with patch.object(run, "clear_tree", side_effect=watched):
            self.gc()
        self.assertEqual(held, [True])
        self.assertFalse(wt.exists())
        # A resume that commits `running` after the plan and before the removal keeps it.
        resumed, resumed_wt, _ = self.receipt("resumed", self.repo, **failed_merge)
        planned = [item for item in run.gc_plan() if item["path"] == str(resumed_wt)]
        self.assertEqual([item["kind"] for item in planned], ["unmerged-worktree"])
        run.save_state(resumed, {**run.read_state(resumed), "state": "running"})
        with patch.object(run, "gc_candidates", return_value=iter(planned)):
            self.assertEqual(run.gc(lambda _message: None), [])
        self.assertTrue(resumed_wt.is_dir())

    def test_every_path_reports_a_tree_it_cannot_empty_once(self):
        if os.geteuid() == 0:
            self.skipTest("root removes a read-only directory")
        # A failed run's checkout a week old, through the collector's ended-worktree step.
        failed, failed_wt, failed_branch = self.receipt(
            "failed", self.repo, state="fail", verdict="FAIL", merged=False,
            finished_at=time.time() - 8 * DAY)
        self.locked_tree(failed_wt)
        # A merged checkout, through the sweep `ak run gc` makes past the collector's proof.
        merged, merged_wt, _ = self.receipt("merged", self.other)
        self.locked_tree(merged_wt)
        out = self.gc()
        for wt in (failed_wt, merged_wt):
            self.assertEqual(out.count(f"gc: left {wt}: "), 1, out)
            self.assertIn(str(wt), run.leftovers())
            self.assertFalse((wt / "tracked").exists())   # what this user owns is gone
        self.assertTrue(self.branch_exists(self.repo, failed_branch))
        # Neither is listed or tried again, by the collector or by the sweep.
        for again in (self.gc("--dry-run"), self.gc()):
            for wt in (failed_wt, merged_wt):
                self.assertNotIn(str(wt), again)
        self.assertEqual(run.gc(lambda _message: None, automatic=True), [])
        # A month on, the record goes whole and its reported tree is not tried again.
        now = time.time()
        ancient, ancient_wt, _ = self.receipt(
            "ancient", self.repo, merged=False, merge_note="PR is closed",
            started_at=now - 31 * DAY, finished_at=now - 31 * DAY)
        (ancient_wt / "ours.txt").write_text("would go with any attempt\n")
        # as the first report left it: its pointer gone with what was ours, git's entry pruned
        (ancient_wt / ".git").unlink()
        self.git(self.repo, "worktree", "prune")
        left = run.leftovers()
        left[str(ancient_wt)] = now
        config._write_json(config.STATE / "gc-leftovers.json", left)
        out = self.gc()
        self.assertIn(f"gc: remove old-run {ancient}", out)
        self.assertFalse(ancient.exists())
        self.assertTrue((ancient_wt / "ours.txt").exists())
        self.assertNotIn(str(ancient_wt), out.replace(f"old-run {ancient}", ""))

    def test_a_refused_removal_is_never_followed_by_one_by_hand(self):
        if os.geteuid() == 0:
            self.skipTest("root removes a read-only directory")
        # A loop still going refuses its tree, however little of it this user could remove.
        going = config.WT / "going"
        going.mkdir(parents=True)
        (going / "ours.txt").write_text("in use\n")
        self.locked_tree(going)
        state = {"run_id": "going", "state": "fail", "repo": str(self.repo),
                 "worktree": str(going), "branch": "ak/going", **run.process_owner(os.getppid())}
        self.assertFalse(run.drop_tree(state, going, lambda _message: None))
        self.assertTrue((going / "ours.txt").exists())
        # ~/.agentkit/wt reached through a link into ~/code: the month-old record goes, and
        # the tree it names is the owner's, refused and never emptied by hand.
        real = config.CODE / "checkouts"
        real.mkdir(parents=True)
        linked = self.root / "linked-wt"
        linked.symlink_to(real, target_is_directory=True)
        self.stack.enter_context(patch.object(config, "WT", linked))
        tree = linked / "ancient"
        tree.mkdir()
        (tree / "ours.txt").write_text("the owner's\n")
        self.locked_tree(tree)
        directory, now = config.RUNS / "ancient", time.time()
        directory.mkdir()
        run.save_state(directory, {"run_id": "ancient", "state": "fail", "verdict": "FAIL",
                                   "repo": str(self.repo), "worktree": str(tree),
                                   "branch": "ak/ancient", "merged": False,
                                   "launched_session": None, "started_at": now - 31 * DAY,
                                   "finished_at": now - 31 * DAY, "pid": DEAD,
                                   "process_identity": None})
        out = self.gc()
        self.assertIn(f"gc: remove old-run {directory}", out)
        self.assertTrue((real / "ancient" / "ours.txt").exists())
        self.assertNotIn("gc: left", out)
        self.assertEqual(run.leftovers(), {})

    def test_a_scratch_workspace_goes_only_with_its_run_directory(self):
        # Its files are what the run delivered: neither the collector nor the sweep takes
        # a workspace whose run directory stays, delivered or failed and a week past.
        now = time.time()
        def scratch(name, age, **extra):
            directory, work = config.RUNS / name, config.WORK / name
            directory.mkdir(parents=True)
            work.mkdir(parents=True)
            (work / "crosscheck.md").write_text("the deliverable\n")
            run.save_state(directory, {"run_id": name, "title": name, "state": "pass",
                                       "verdict": "PASS", "scratch": True, "repo": None,
                                       "worktree": str(work), "launched_session": None,
                                       "started_at": now - age, "finished_at": now - age,
                                       "pid": DEAD, "process_identity": None, "rounds": 1,
                                       **extra})
            (directory / "result.md").write_text("result\n")
            return directory, work
        _, delivered = scratch("delivered", 60)
        _, failed = scratch("failed", 8 * DAY, state="fail", verdict="FAIL",
                            handed_back=now - 8 * DAY + 1)
        ancient, ancient_work = scratch("ancient", 31 * DAY)
        planned = {item["path"] for item in run.gc_plan() + run.sweep_plan()}
        self.assertFalse({str(delivered), str(failed)} & planned, planned)
        out = self.gc()
        for work in (delivered, failed):
            self.assertTrue((work / "crosscheck.md").is_file(), out)
        # the month-old one goes in the step that takes its run directory
        self.assertIn(f"gc: remove old-run {ancient}", out)
        self.assertFalse(ancient.exists())
        self.assertFalse(ancient_work.exists())

    def test_gc_prunes_harness_entries_of_gone_sandboxes_and_checkouts(self):
        gone_smoke = str(config.TMP / "smoke-20260901-000000" / "agentkit-smoke")
        gone_box = str(config.TMP / "smoke-20260923-112603" / "home" / ".local" / "Xauthority")
        live_smoke = config.TMP / "smoke-20260923-120000" / "seat"
        live_smoke.mkdir(parents=True)
        gone_wt = str(config.WT / "20260901-0101-gone-work")
        other_tmp = str(config.TMP / "check4-20260903-190608" / "run-repo")
        code = str(config.CODE / "atoll")
        claude = self.root / ".claude.json"
        data = {"numStartups": 7, "projects": {
                    gone_smoke: {"hasTrustDialogAccepted": True},
                    code: {"hasTrustDialogAccepted": True, "allowedTools": ["Bäsh"]},
                    str(live_smoke): {"hasTrustDialogAccepted": True},
                    gone_wt: {"hasTrustDialogAccepted": True},
                    other_tmp: {"hasTrustDialogAccepted": True}},
                "mcpServers": {
                    "desktop": {"type": "stdio", "command": "python3",
                                "env": {"DISPLAY": ":99", "XAUTHORITY": gone_box}},
                    "browser": {"type": "stdio", "command": "npx",
                                "env": {"XAUTHORITY": str(self.root / "Xauthority")}}},
                "theme": "dark"}
        claude.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        claude.chmod(0o600)
        codex = self.root / ".codex" / "config.toml"
        codex.parent.mkdir()
        head = 'model = "gpt"\n# the owner\'s note\n'
        keep = (f'[projects."{code}"]\ntrust_level = "trusted"\n\n'
                f'[projects."{live_smoke}"]\ntrust_level = "trusted"\n\n')
        codex.write_text(
            head + f'[projects."{gone_smoke}"]\ntrust_level = "trusted"\n\n' + keep
            + f'[projects."{gone_wt}"]\ntrust_level = "trusted"\n\n'
            + "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---\n"
            + '[mcp_servers.browser]\ncommand = "npx"\n'
            + f'env = {{ DISPLAY = ":99", XAUTHORITY = "{gone_box}" }}\n\n'
            + "# --- end agentkit browser bridge ---\n\n"
            + '[hooks.state."x:stop:0:0"]\ntrusted_hash = "sha256:1"\n')
        dry = self.gc("--dry-run")
        self.assertIn(f"gc: would prune harness-entries {claude}: 2 trust entries and "
                      "1 MCP servers name a gone smoke sandbox or checkout", dry)
        self.assertIn(f"gc: would prune harness-entries {codex}: 2 trust entries and "
                      "1 MCP servers", dry)
        out = self.gc()
        self.assertIn(f"gc: prune harness-entries {claude}", out)
        del data["projects"][gone_smoke], data["projects"][gone_wt], data["mcpServers"]["desktop"]
        self.assertEqual(claude.read_text(), json.dumps(data, indent=2, ensure_ascii=False))
        self.assertEqual(claude.stat().st_mode & 0o777, 0o600)
        self.assertEqual(codex.read_text(), head + keep
                         + "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---\n"
                         + "# --- end agentkit browser bridge ---\n\n"
                         + '[hooks.state."x:stop:0:0"]\ntrusted_hash = "sha256:1"\n')
        self.assertNotIn("harness-entries", self.gc("--dry-run"))
        # Any layout the harness or a hand wrote: compact, another indent, inline tables.
        # Only the stale members go; every other byte stays where it was.
        for layout in ({}, {"separators": (",", ":")}, {"indent": 4}, {"indent": "\t"}):
            claude.write_text(json.dumps({"projects": {gone_smoke: {}, code: {"a": 1}},
                                          "mcpServers": {"desktop": {"env": {"X": gone_box}}},
                                          "theme": "dark"}, **layout))
            self.assertIn(f"gc: prune harness-entries {claude}", self.gc())
            self.assertEqual(claude.read_text(), json.dumps(
                {"projects": {code: {"a": 1}}, "mcpServers": {}, "theme": "dark"}, **layout))
        inline = (f'model = "gpt"\n'
                  f'mcp_servers = {{ browser = {{ command = "npx" }}, '
                  f'desktop = {{ command = "python3", env = {{ XAUTHORITY = "{gone_box}" }} }} }}\n'
                  f'\n[projects]\n"{code}" = {{ trust_level = "trusted" }}  # the owner\'s\n'
                  f'"{gone_smoke}" = {{ trust_level = "trusted" }}\n'
                  f'"{gone_wt}".trust_level = "trusted"\n')
        codex.write_text(inline)
        self.assertIn(f"gc: would prune harness-entries {codex}: 2 trust entries and "
                      "1 MCP servers", self.gc("--dry-run"))
        self.gc()
        self.assertEqual(codex.read_text(),
                         'model = "gpt"\nmcp_servers = { browser = { command = "npx" } }\n'
                         f'\n[projects]\n"{code}" = {{ trust_level = "trusted" }}  # the owner\'s\n')
        # A file that does not parse is left exactly as it is.
        broken = f'[projects."{gone_smoke}"]\ntrust_level = "trusted"\n[unclosed\n'
        codex.write_text(broken)
        truncated = json.dumps({"projects": {gone_smoke: {}}})[:-1]
        claude.write_text(truncated)
        self.assertNotIn("harness-entries", self.gc())
        self.assertEqual(codex.read_text(), broken)
        self.assertEqual(claude.read_text(), truncated)

if __name__ == "__main__":
    unittest.main(verbosity=2)
