"""Line changes and the tick start fresh landers; stops never wake.

Offline: sandbox records, fake process placement, host readings, checks and wakes.
"""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, host, land, orch, record, run, watch
import test_lander_wakes as wakes


class LanderLifecycle(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-lander-lifecycle-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "caller", "AK_PARENT_RUN": "caller",
            "AK_RUN_LOG": "caller.log", "AK_RUN_DEPTH": "2", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "caller-seat", "AGENTKIT_RUN_DIR": "caller",
            "AGENTKIT_JOB_DIR": "caller-job", "AK_RUN_SCOPE": "caller-scope",
            "AK_RUN_ROLE": "executor", "AGENTKIT_UNATTENDED": "1"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "mem_total_mb": 16000, "free_mb": 8000}))
        self.ceiling = self.stack.enter_context(patch.object(
            orch, "slice_memory_max_mb", return_value=10000))
        self.oom = self.stack.enter_context(patch.object(orch, "scope_oom_policy", return_value=True))
        self.stack.enter_context(patch.object(config, "run_memory_max_mb", return_value=None))
        self.starts = []
        self.spawn = self.stack.enter_context(patch.object(
            orch, "start_in_slice", side_effect=self.start))
        self.turn = config.RUNS / ".merge-acme.lock"

    def start(self, argv, unit, env, output, log=lambda _: None, **kw):
        self.starts.append((argv, unit, env, output, kw))
        return 999

    def member(self, name="fix-api", turn=None, **extra):
        directory = config.RUNS / name
        directory.mkdir()
        record.save_state(directory, {
            "run_id": name, "state": "waiting", "pid": 1234,
            "repo": str(self.root / "acme"), "base": "origin/main",
            "review": {"verdict": "PASS", "head_sha": "head"},
            "waiting_on": {"line": (turn or self.turn).name, "joined": 1}, **extra})
        return directory

    def test_join_starts_an_independent_pass_with_the_landing_allowance(self):
        self.member()
        self.assertEqual(len(self.starts), 1)
        argv, unit, env, output, kw = self.starts[0]
        self.assertEqual(argv, [sys.executable, str(REPO / "bin" / "ak"),
                                "run", "--lander", self.turn.name])
        self.assertTrue(unit.startswith("agentkit-lander-acme-"))
        self.assertEqual(kw["target_slice"], orch.run_slice_name())
        self.assertTrue(kw["nice"])
        self.assertIn("MemoryMax=4000M", kw["properties"])
        self.assertIn("MemorySwapMax=4000M", kw["properties"])
        self.assertEqual(output, self.turn.with_suffix(".log"))
        self.assertEqual(env["AK_RUN_DEPTH"], "0")
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_SCOPE",
                    "AK_RUN_ROLE", config.RUN_DIR_ENV, config.JOB_DIR_ENV,
                    config.SESSION_ENV, config.UNATTENDED_ENV):
            self.assertNotIn(key, env)

    def test_recorded_suite_need_can_exceed_the_current_run_allowance(self):
        self.member(memory_cap_mb=6000, peak_rss_mb=7200.25)
        properties = self.starts[0][4]["properties"]
        self.assertIn("MemoryMax=7201M", properties)
        self.assertIn("MemorySwapMax=7201M", properties)

    def test_a_live_first_member_finishes_cleanup_before_a_pass_starts(self):
        self.member()
        self.starts.clear()
        with patch.object(record, "process_active", return_value=True):
            self.assertFalse(land.start_line(self.turn))
        self.assertEqual(self.starts, [])

    def test_a_suite_oom_keeps_the_lander_scope_running(self):
        self.member(memory_cap_mb=6000)
        _, properties = run.run_scope_limits(cap_mb=6000)
        self.assertEqual(self.starts[0][4]["properties"], properties)
        self.assertIn("OOMPolicy=continue", properties)

    def test_an_older_manager_gets_no_unsupported_oom_property(self):
        self.oom.return_value = False
        self.member()
        self.assertNotIn("OOMPolicy=continue", self.starts[0][4]["properties"])

    def test_a_host_without_a_slice_derives_memory_from_its_own_reading(self):
        self.ceiling.return_value = None
        self.member()
        self.assertIn("MemoryMax=6400M", self.starts[0][4]["properties"])

    def test_rejoin_and_departure_start_after_the_new_record_is_visible(self):
        directory = self.member()
        self.member("fix-docs")
        self.starts.clear()
        with record.record(directory) as state:
            state["waiting_on"]["fix"] = {"line": "failed", "log": "lander.log"}
        state = record.read_state(directory)
        record.save_state(directory, {**state, "state": "running"})
        lp = run.Loop.__new__(run.Loop)
        lp.state, lp.write = state, lambda: record.save_state(directory, lp.state)
        with patch.object(run, "turn_path", return_value=self.turn):
            self.assertFalse(run.rejoin_line(lp, "origin/main", "fixed", back=True))
        self.assertNotIn("fix", record.read_state(directory)["waiting_on"])
        with record.record(directory) as state:
            state.update(state="pass", merged=True)
            state.pop("waiting_on")
        self.assertEqual(len(self.starts), 3)
        self.assertEqual([member.name for member, _ in land.line(self.turn)], ["fix-docs"])
        record.save_state(directory, record.read_state(directory))
        self.assertEqual(len(self.starts), 3, "an unchanged save starts no extra pass")

    def test_a_woken_members_bookkeeping_does_not_start_another_suite(self):
        directory = self.member()
        self.member("fix-docs")
        self.starts.clear()
        for changes in ({"state": "queued"}, {"state": "running"},
                        {"scope": "agentkit-run-fix-api", "memory_cap_mb": 6000},
                        {"review": {"verdict": "PASS", "head_sha": "rebased"}},
                        {"final_check": {"outcome": "passed", "tree_sha": "tree"}}):
            with record.record(directory) as state:
                state.update(changes)
        self.assertEqual(self.starts, [])

    def test_moving_between_lines_starts_both(self):
        directory = self.member()
        self.member("fix-docs")
        self.starts.clear()
        other = config.RUNS / ".merge-other.lock"
        with record.record(directory) as state:
            state["waiting_on"]["line"] = other.name
        self.assertEqual({start[0][-1] for start in self.starts}, {self.turn.name, other.name})

    def test_a_held_singleton_defers_the_join_until_the_tick(self):
        with self.turn.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.member()
            watch.resume_waiting(log=lambda _: None)
            self.spawn.assert_not_called()
        watch.resume_waiting(log=lambda _: None)
        self.assertEqual(len(self.starts), 1)

    def test_tick_starts_each_line_once_and_retries_saved_verdict_wakes(self):
        self.member()
        self.member("fix-docs")
        other = config.RUNS / ".merge-other.lock"
        self.member("fix-tests", turn=other,
                    waiting_on={"line": other.name, "joined": 2, "land": "tree"})
        self.starts.clear()
        watch.resume_waiting(log=lambda _: None)
        self.assertEqual(len(self.starts), 2)
        self.assertEqual({start[0][-1] for start in self.starts}, {self.turn.name, other.name})
        watch.resume_waiting(dry_run=True, log=lambda _: None)
        self.assertEqual(len(self.starts), 2)

    def test_a_failed_launch_leaves_members_for_the_next_tick(self):
        self.spawn.side_effect = OSError("manager unavailable")
        directory = self.member()
        self.assertEqual(record.read_state(directory)["state"], "waiting")
        self.spawn.side_effect = self.start
        watch.resume_waiting(log=lambda _: None)
        self.assertEqual(len(self.starts), 1)

    def test_each_pass_starts_the_installed_entry_point_after_an_upgrade(self):
        installed = self.root / ".local" / "bin" / "ak"
        installed.parent.mkdir(parents=True)
        releases = [self.root / "release-1-ak", self.root / "release-2-ak"]
        for release in releases:
            release.touch()
        installed.symlink_to(releases[0])
        with patch.object(land, "check_line", side_effect=AssertionError("in-process check")):
            self.member()
            self.assertEqual(Path(self.starts[-1][0][1]).resolve(), releases[0])
            installed.unlink()
            installed.symlink_to(releases[1])
            watch.resume_waiting(log=lambda _: None)
            self.assertEqual(Path(self.starts[-1][0][1]).resolve(), releases[1])
        self.assertEqual(len(self.starts), 2)
        self.assertEqual([start[0][1] for start in self.starts], [str(installed)] * 2)
        self.assertNotEqual(self.starts[0][1], self.starts[1][1])

    def test_the_child_entry_checks_just_its_line(self):
        with patch.object(land, "check_line") as check:
            self.assertEqual(run.main(["--lander", self.turn.name]), 0)
        check.assert_called_once_with(self.turn, print)
        with self.assertRaises(config.Error):
            run.main(["--lander", "../.merge-other.lock"])

    def test_stopping_during_a_check_prevents_the_verdict_and_wake(self):
        directory = self.member()

        def stop(*_args):
            with record.record(directory) as state:
                state.update(state="stopped", verdict="STOPPED")
                state.pop("waiting_on")
            return {"land": "tree"}

        with (patch.object(run, "fetch"), patch.object(run, "git", return_value="target"),
              patch.object(land, "_check_member", side_effect=stop),
              patch.object(watch, "launch_resume") as wake):
            land.check_line(self.turn)
        self.assertEqual(record.read_state(directory)["state"], "stopped")
        self.assertEqual(land.line(self.turn), [])
        wake.assert_not_called()


class LanderDelivery(unittest.TestCase):
    def setUp(self):
        start_line = land.start_line
        self.case = wakes.LanderWakes()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.case.stack.enter_context(patch.object(
            record, "process_active", side_effect=lambda state: bool(state.get("pid"))))
        self.case.stack.enter_context(patch.object(host, "host_readings", return_value={
            "mem_total_mb": 16000}))
        self.case.stack.enter_context(patch.object(orch, "slice_memory_max_mb", return_value=10000))
        self.case.stack.enter_context(patch.object(orch, "scope_oom_policy", return_value=True))
        self.starts = []

        def start(*_args, **_kw):
            self.case.assert_free()
            self.starts.append((len(self.case.merges),
                                record.read_state(self.case.directory).get("waiting_on")))
            return 999

        self.case.stack.enter_context(patch.object(orch, "start_in_slice", side_effect=start))
        land.start_line.side_effect = start_line

    def prepare(self, method="squash"):
        self.case.park(method)
        other = config.RUNS / "fix-docs"
        other.mkdir()
        record.save_state(other, {
            "run_id": other.name, "state": "waiting", "repo": str(self.case.wt),
            "base": "origin/main", "review": {"verdict": "PASS", "head_sha": "other"},
            "waiting_on": {"line": self.case.turn.name, "joined": 20}})
        self.starts.clear()

    def landed(self, method):
        self.prepare(method)
        self.assertEqual(run.cmd_resume([self.case.directory.name]), 0)
        self.assertTrue(record.read_state(self.case.directory)["merged"])
        self.assertEqual([member.name for member, _ in land.line(self.case.turn)], ["fix-docs"])
        self.assertEqual(self.starts, [(1, None)], "the next pass starts only after delivery")

    def test_squash_starts_the_next_pass_after_releasing_the_lock(self):
        self.landed("squash")

    def test_rebase_starts_the_next_pass_after_releasing_the_lock(self):
        self.landed("rebase")

    def test_merge_starts_the_next_pass_after_releasing_the_lock(self):
        self.landed("merge")

    def test_work_already_on_target_starts_the_next_pass_after_unlock(self):
        self.prepare()
        run.git(self.case.wt, "push", "origin", "HEAD:main")
        self.assertEqual(run.cmd_resume([self.case.directory.name]), 0)
        self.assertTrue(record.read_state(self.case.directory)["on_target"])
        self.assertEqual(self.starts, [(0, None)])

    def test_a_changed_target_rejoins_and_starts_the_next_pass_after_unlock(self):
        self.prepare()
        (self.case.owner / "other.txt").write_text("external move\n")
        self.case.commit(self.case.owner, "move target")
        run.git(self.case.owner, "push", "origin", "main")
        self.assertEqual(run.cmd_resume([self.case.directory.name]), 0)
        wait = record.read_state(self.case.directory)["waiting_on"]
        self.assertEqual(wait, {"line": self.case.turn.name, "joined": 10})
        self.assertEqual(self.starts, [(0, wait)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
