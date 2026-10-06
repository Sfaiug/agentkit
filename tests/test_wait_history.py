"""A run's history row keeps how long it waited for compute and for other runs to merge.  Offline.

A temporary HOME and the real repository lock, held by a thread of this test; the slot and
heavy-suite-turn waits are also timed in tests/test_slots.py and tests/test_gate_turns.py.
"""

from contextlib import ExitStack, closing
import fcntl
import os
from pathlib import Path
import signal
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import (browser, config, gate, history, host, land, orch, record, run,  # noqa: E402
                      scoreboard, terminal, watch, worktrees)

DAY = 86400


class WaitHistory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-wait-history-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # no checkout to size: the board's size row is another test's
        self.stack.enter_context(patch.object(config, "REPO", self.root / "agentkit"))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "NO_COLOR": "1"}))
        config.ensure_dirs()
        self.now = time.time()

    def finished(self, run_id, days_ago, total, *, state="pass", **waits):
        finished_at = self.now - days_ago * DAY
        history.start_run(run_id, repo="/home/fixture/code/acme", started_at=finished_at - total)
        for wait, seconds in waits.items():
            history.add_wait(run_id, wait, seconds)
        # the loop restamps its record's start once its slot is won; run time still counts
        # from the launch, the slot wait with it
        history.finish_run(run_id, final_state=state, started_at=finished_at - total / 2,
                           finished_at=finished_at)

    def before_the_waits(self, run_id, days_ago, total):
        """A finished row as an agentkit that kept no waits wrote it."""
        history._ensure_migrated()
        with closing(sqlite3.connect(history.path())) as connection:
            connection.execute(
                "INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, "
                "total_seconds) VALUES (?, 'acme', 'pass', ?, ?, ?)",
                (run_id, self.now - days_ago * DAY - total, self.now - days_ago * DAY, total))
            connection.commit()

    def before_the_check_waits(self, run_id, days_ago, total, **waits):
        """A finished row as an agentkit that kept every wait but its landing checks' wrote it."""
        self.finished(run_id, days_ago, total, **waits)
        with closing(sqlite3.connect(history.path())) as connection:
            connection.execute("UPDATE runs SET lander_wait_seconds=NULL WHERE run_id=?", (run_id,))
            connection.commit()

    def board_row(self):
        """The scoreboard's waits row, both weeks on its one line."""
        with patch.object(terminal, "content_width", return_value=400):
            return next(line for line in scoreboard.render() if line.startswith("waits"))

    def waits(self, run_id):
        row = history.get(run_id)
        return row["slot_wait_seconds"], row["suite_wait_seconds"], row["merge_wait_seconds"]

    def line_loop(self):
        repo = self.root / "acme"
        repo.mkdir()
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        self.clock = [self.now - 60]
        state = {"run_id": directory.name, "repo": str(repo), "worktree": str(repo),
                 "base": "main", "target": "main", "state": "running", "pid": os.getpid(), "started_at": self.clock[0],
                 "review": {"verdict": "PASS", "head_sha": "reviewed", "tree_sha": "checked-tree"}}
        lp = SimpleNamespace(wt=repo, run_dir=directory, state=state, base_sha="old-base",
                             target="main", log=lambda _: None)
        lp.write = lambda: record.save_state(directory, lp.state)

        def git(wt, *args, **_kw):
            if args[:3] == ("remote", "get-url", "origin"):
                return str(repo)
            if args[0] == "rev-parse":
                return "target-tree" if args[-1].endswith("^{tree}") else "new-base"
            raise AssertionError(("unexpected git call", args))

        def git_out(wt, *args, **_kw):
            if args[0] == "rebase":
                return 0, ""
            if args[:2] == ("diff", "--quiet"):
                return 1, ""
            raise AssertionError(("unexpected git_out call", args))

        for module, name, options in (
                (time, "time", {"side_effect": lambda: self.clock[0]}),
                (time, "monotonic", {"side_effect": lambda: self.clock[0]}),
                (run, "git", {"side_effect": git}),
                (run, "git_out", {"side_effect": git_out}),
                (run, "fetch", {}), (run, "require_review_pass", {}),
                (run, "stop_run_tree", {}), (run, "set_base", {}),
                (run, "how_to_integrate", {"return_value": "rebase"}),
                (run, "passed_review_head", {"return_value": "reviewed"}),
                (run, "commit_identity", {"return_value": {
                    "head_sha": "landed", "tree_sha": "checked-tree"}}),
                (run, "declared_suite", {"return_value": ""}),
                (record, "process_active", {"return_value": False}),
                (land, "start_line", {"return_value": False})):
            self.stack.enter_context(patch.object(module, name, **options))
        self.checked = self.stack.enter_context(patch.object(
            land, "_check_members", side_effect=lambda turn, candidates, *args, **_kw: {
                member: {"land": "checked-tree"} for member, _ in candidates}))
        self.wake = self.stack.enter_context(patch.object(watch, "launch_resume"))
        history.start_run(directory.name, repo=repo, started_at=self.clock[0])
        lp.write()
        return lp, run.turn_path(lp, "origin/main")

    def resume_line(self, lp):
        lp.state = record.read_state(lp.run_dir)
        lp.state.update(state="running", pid=os.getpid())
        history.start_run(lp.run_dir.name, repo=lp.wt)
        lp.write()

    def deliver_line(self, lp):
        lp.state["merged"] = True
        return True

    def test_parked_line_wait_behind_the_lander_lock_reaches_history_and_scoreboard(self):
        lp, turn = self.line_loop()
        # Checks can overlap delivery now; hold the checker to keep the review probe parked.
        with turn.with_suffix(".lander.lock").open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            self.assertFalse(run.join_line(lp, "origin/main", lambda: True))
            run.release_line(lp.run_dir, lp.log)
            self.assertIsNone(record.read_state(lp.run_dir)["pid"])
            self.assertEqual(len(land.line(turn)), 1)
            land.check_line(turn)
            self.wake.assert_not_called()
            self.assertNotIn("land", record.read_state(lp.run_dir)["waiting_on"])
            self.clock[0] += 120
            land.check_line(turn)
            self.wake.assert_not_called()
            self.assertNotIn("land", record.read_state(lp.run_dir)["waiting_on"])
        land.check_line(turn)
        self.wake.assert_called_once()
        self.assertEqual(record.read_state(lp.run_dir)["waiting_on"]["land"], "checked-tree")
        self.resume_line(lp)
        self.assertTrue(run.land_from_line(lp, "origin/main", lambda: self.deliver_line(lp)))
        self.clock[0] += 30
        lp.state.update(state="pass", finished_at=self.clock[0])
        lp.write()
        run.history_finish(lp.state)
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 120.0))
        self.assertAlmostEqual(scoreboard.compute(self.clock[0])["waits"][0]["merge_hours"],
                               120 / 3600)

    def test_line_wait_includes_delivery_lock_and_delivery_only_once(self):
        lp, turn = self.line_loop()
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 100
        land.check_line(turn)
        self.resume_line(lp)
        flock = fcntl.flock
        with turn.open("a") as holder:
            flock(holder, fcntl.LOCK_EX)

            def take_lock(lock, operation):
                if operation == fcntl.LOCK_EX and lock.name == str(turn):
                    self.clock[0] += 20
                    flock(holder, fcntl.LOCK_UN)
                return flock(lock, operation)

            def deliver():
                self.clock[0] += 10
                return self.deliver_line(lp)

            with patch.object(run.fcntl, "flock", side_effect=take_lock):
                self.assertTrue(run.land_from_line(lp, "origin/main", deliver))
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 130.0))
        lp.write()
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 130.0))

    def test_admission_after_a_landing_wake_is_a_slot_wait_inside_the_line_wait(self):
        lp, turn = self.line_loop()
        joined = self.clock[0]
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 100
        land.check_line(turn)
        self.wake.assert_called_once()
        state = record.read_state(lp.run_dir)
        state.update(resume_from=state["state"], state="queued", slot_waiting=True,
                     queued_at=self.clock[0], pid=os.getpid(), finished_at=None)
        record.save_state(lp.run_dir, state)
        (lp.run_dir / "log.txt").write_text("resume\n")
        tries = []

        def claim(state, limit, readings=None):
            if not tries:
                tries.append(1)
                state.update(slot_waited=True, slot_wait_kind="count")
                return False
            state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                         pid=os.getpid())
            state.pop("resume_from", None)
            return True

        def sleep(_seconds):
            self.clock[0] += 50

        with patch.object(gate, "claim_slot", side_effect=claim), \
                patch.object(time, "sleep", side_effect=sleep), \
                patch.object(run, "redress_seat"), \
                patch.object(gate, "slot_note", return_value="waiting for a slot"):
            gate.wait_for_slot(lp.run_dir)
        lp.state = record.read_state(lp.run_dir)
        # the waiter counted its slot wait; the place it held stays open through admission
        self.assertEqual(self.waits(lp.run_dir.name), (50.0, 0.0, 0.0))
        self.clock[0] += 10
        self.assertTrue(run.land_from_line(lp, "origin/main", lambda: self.deliver_line(lp)))
        self.assertEqual(self.waits(lp.run_dir.name), (50.0, 0.0, self.clock[0] - joined))

    def test_rejoins_and_resumes_count_each_line_interval_and_exclude_fix_waits(self):
        lp, turn = self.line_loop()
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        joined = record.read_state(lp.run_dir)["waiting_on"]["joined"]
        self.clock[0] += 40
        self.resume_line(lp)
        self.assertFalse(run.rejoin_line(lp, "origin/main", "target changed"))
        self.assertEqual(lp.state["waiting_on"]["joined"], joined)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 60
        failure = {"line": "check failed", "log": str(lp.run_dir / "lander.log")}
        Path(failure["log"]).write_text("check failed")
        self.checked.side_effect = None
        self.checked.return_value = {lp.run_dir: {"fix": failure}}
        land.check_line(turn)
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 100.0))
        # Admission and checks after a fix wake belong only to the compute waits.
        self.clock[0] += 20
        history.add_wait(lp.run_dir.name, "slot", 20)
        self.resume_line(lp)

        def fix(*_args):
            self.clock[0] += 30
            history.add_wait(lp.run_dir.name, "suite", 30)
            return True

        with patch.object(run, "integrate", return_value=True), \
                patch.object(run, "fix_final_check", side_effect=fix):
            self.assertFalse(run.land_from_line(lp, "origin/main", lambda: True))
        self.assertEqual(self.waits(lp.run_dir.name), (20.0, 30.0, 100.0))
        # A repaired member keeps its place; its merge wait restarts at the rejoin.
        self.assertEqual(lp.state["waiting_on"]["joined"], joined)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 70
        self.checked.return_value = {lp.run_dir: {"land": "checked-tree"}}
        land.check_line(turn)
        self.resume_line(lp)
        self.clock[0] += 5
        self.assertTrue(run.land_from_line(lp, "origin/main", lambda: self.deliver_line(lp)))
        self.assertEqual(self.waits(lp.run_dir.name), (20.0, 30.0, 175.0))

    def test_leaving_the_line_closes_the_wait_and_a_resume_keeps_only_its_new_time(self):
        lp, _ = self.line_loop()
        run.join_line(lp, "origin/main", lambda: True)
        self.clock[0] += 30
        lp.state.update(state="pass", merge_failed=True)
        lp.write()
        self.assertEqual(self.waits(lp.run_dir.name)[2], 30.0)
        self.clock[0] += 40
        with record.record(lp.run_dir) as state:
            state["waiting_on"]["land"] = "checked-tree"
        self.resume_line(lp)
        self.clock[0] += 20
        lp.state.pop("waiting_on")
        lp.write()
        self.assertEqual(self.waits(lp.run_dir.name)[2], 50.0)
        self.clock[0] += 40
        lp.write()
        self.assertEqual(self.waits(lp.run_dir.name)[2], 50.0)

    def leave_by_recovery(self, departure):
        """A delivery stopped mid-landing, then recovery records it; the probe of PR #464's review."""
        lp, turn = self.line_loop()
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 40
        land.check_line(turn)
        self.resume_line(lp)
        self.clock[0] += 10

        def stopped_delivery():
            raise run.Stopped("delivery command was interrupted")

        with self.assertRaises(run.Stopped):
            run.land_from_line(lp, "origin/main", stopped_delivery)
        with patch.object(run, "redress_seat"), patch.object(run, "write_result"):
            if departure == "exhausted":
                run.mark_state(lp.run_dir, departure, "the provider's window is spent", lp.log)
            elif departure == "interrupted":
                record.save_state(lp.run_dir, run.interrupt(record.read_state(lp.run_dir),
                                                            "a killed turn"))
            else:
                run.park_stalled(lp.run_dir, record.read_state(lp.run_dir),
                                 {"step": "merge", "time": self.clock[0]})
        self.assertEqual(land.line(turn), [])
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 50.0))
        # Time off the line is nobody's merge wait; its resume waits for a slot, then in line.
        self.clock[0] += 300
        resumed = record.read_state(lp.run_dir)
        resumed.update(resume_from=departure, state="queued", slot_waiting=True,
                       queued_at=self.clock[0], finished_at=None)
        record.save_state(lp.run_dir, resumed)
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 50.0))
        self.clock[0] += 20
        self.resume_line(lp)
        self.clock[0] += 5
        lp.state["merged"] = True
        lp.write()
        # its resume's slot admission holds its place: line time, and no waiter counted a slot
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 75.0))

    def test_running_out_of_quota_while_delivering_ends_the_line_wait(self):
        self.leave_by_recovery("exhausted")

    def test_a_dead_delivery_ends_the_line_wait(self):
        self.leave_by_recovery("interrupted")

    def test_a_stalled_delivery_ends_the_line_wait(self):
        self.leave_by_recovery("stalled")

    def test_a_slot_wait_counts_however_admission_ends(self):
        """A steady second reading admits after one poll; a stop ends the wait instead.

        A waiter that dies has counted every poll but the one it died in, and nothing the
        record goes through afterwards adds to it: only a waiting process counts its wait,
        by the monotonic clock, so a wall clock corrected an hour each poll adds nothing.
        """
        self.clock, self.wall = [1000.0], [1000.0]
        readings = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                    "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "8"}))
        for module, name, options in (
                (time, "time", {"side_effect": lambda: self.wall[0]}),
                (time, "monotonic", {"side_effect": lambda: self.clock[0]}),
                (gate, "SLOT_POLL", {"new": 30}),
                (gate, "frozen_runs", {"return_value": 0}),
                (run, "redress_seat", {}), (run, "record_result", {}),
                (record, "process_owner", {"return_value": {"pid": os.getpid()}}),
                (host, "host_readings", {"return_value": readings}),
                (config, "check_stop_owner", {}),
                (orch, "user_manager", {"return_value": False}),
                (run, "marker_pids", {"return_value": []}),
                (worktrees, "stop_checkout", {"return_value": True}),
                (browser, "close_owned", {})):
            self.stack.enter_context(patch.object(module, name, **options))
        for run_id, running in (("fix-api", 0), ("fix-ui", 1), ("fix-db", 1)):
            directory = config.RUNS / run_id
            directory.mkdir()
            (directory / "log.txt").write_text("launch\n")
            history.start_run(run_id, repo="acme", started_at=self.wall[0])
            record.save_state(directory, {"run_id": run_id, "state": "queued",
                                          "slot_waiting": True, "queued_at": self.wall[0],
                                          "started_at": self.wall[0], "pid": os.getpid(),
                                          "run_depth": 0})

            polls = []

            def sleep(seconds, run_id=run_id, running=running, polls=polls):
                polls.append(seconds)
                self.wall[0] += seconds + 3600
                if run_id == "fix-db":
                    if len(polls) == 3:
                        self.clock[0] += 10
                        raise SystemExit("killed mid-poll")
                    self.clock[0] += seconds
                    return
                self.clock[0] += seconds
                if running:
                    self.assertEqual(run.cmd_stop([run_id, "--keep"]), 0)

            with patch.object(gate, "slot_counts", return_value=(running, 0)), \
                    patch.object(time, "sleep", side_effect=sleep):
                if run_id == "fix-db":
                    with self.assertRaises(SystemExit):
                        gate.wait_for_slot(directory)
                elif running:
                    with self.assertRaises(config.Error):
                        gate.wait_for_slot(directory)
                    self.assertEqual(record.read_state(directory)["state"], "stopped")
                else:
                    gate.wait_for_slot(directory)
            if run_id == "fix-db":
                # the tick finds it dead and holds it for a resume; its record waits on
                self.clock[0] += 600
                self.wall[0] += 600
                with record.record(directory) as state:
                    state["deaths"] = [{"pid": os.getpid(), "at": self.wall[0]}]
                self.assertEqual(self.waits(run_id), (60.0, 0.0, 0.0))
                continue
            self.assertEqual(self.waits(run_id), (30.0, 0.0, 0.0))

    def test_a_queued_resumes_wait_waits_for_its_ending(self):
        """A resume's slot wait is the next attempt's, never divided by its last ending's run time."""
        self.clock = [1000.0]
        for module, name, options in (
                (time, "time", {"side_effect": lambda: self.clock[0]}),
                (time, "monotonic", {"side_effect": lambda: self.clock[0]}),
                (gate, "SLOT_POLL", {"new": 600}),
                (gate, "slot_counts", {"return_value": (1, 0)}),
                (gate, "slot_note", {"return_value": "waiting for a slot"}),
                (run, "redress_seat", {})):
            self.stack.enter_context(patch.object(module, name, **options))
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1"}))
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        (directory / "log.txt").write_text("resume\n")
        history.start_run(directory.name, repo="acme", started_at=1000.0)
        history.finish_run(directory.name, final_state="error", finished_at=1060.0)
        self.clock[0] = 1070.0
        record.save_state(directory, {"run_id": directory.name, "state": "queued",
                                      "slot_waiting": True, "queued_at": 1070.0,
                                      "started_at": 1000.0, "resume_from": "error",
                                      "pid": os.getpid(), "run_depth": 0})

        real_sleep = time.sleep

        def sleep(seconds):
            if seconds != 600:
                return real_sleep(seconds)      # a subprocess's own poll, not the slot's
            self.assertEqual(scoreboard.compute(self.clock[0])["waits"], [None, None])
            self.clock[0] += seconds
            if self.clock[0] > 2000:
                raise SystemExit("stopped waiting")

        with patch.object(time, "sleep", side_effect=sleep), self.assertRaises(SystemExit):
            gate.wait_for_slot(directory)
        self.assertEqual(self.waits(directory.name), (600.0, 0.0, 0.0))
        # every ending saves its record first and publishes its row after
        with record.record(directory) as state:
            state.update(state="pass", finished_at=self.clock[0])
        self.assertEqual(scoreboard.compute(self.clock[0])["waits"], [None, None])
        history.finish_run(directory.name, final_state="pass", finished_at=self.clock[0])
        self.assertAlmostEqual(scoreboard.compute(self.clock[0])["waits"][0]["compute"],
                               600 / 1270)

    def test_a_failed_launchs_death_leaves_a_parked_member_counting(self):
        """A failed queued launch dies with no pid, and a parked member has none either."""
        lp, turn = self.line_loop()
        lp.state["deaths"] = [{"at": self.clock[0], "pid": None, "resumed_at": self.clock[0]}]
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        self.assertIsNone(record.read_state(lp.run_dir)["pid"])
        self.clock[0] += 100
        land.check_line(turn)
        self.resume_line(lp)
        self.assertTrue(run.land_from_line(lp, "origin/main", lambda: self.deliver_line(lp)))
        self.assertEqual(self.waits(lp.run_dir.name), (0.0, 0.0, 100.0))

    def test_recovery_that_keeps_the_line_place_keeps_its_merge_wait(self):
        """A green delivery the line still holds waits in it through its recovery."""
        self.clock = [1000.0]
        for module, name, options in (
                (time, "time", {"side_effect": lambda: self.clock[0]}),
                (record, "process_active", {"return_value": False}),
                (run, "memory_cap_reason", {"return_value": None}),
                (land, "start_line", {"return_value": False})):
            self.stack.enter_context(patch.object(module, name, **options))
        worktree = self.root / "acme"
        worktree.mkdir()
        turn = config.RUNS / ".merge-fixture.lock"
        for recovery in ("backoff", "interrupted", "exhausted", "waiting_login"):
            with self.subTest(recovery):
                self.clock[0] = 1000.0
                directory = config.RUNS / f"fix-{recovery}"
                directory.mkdir()
                (directory / "log.txt").touch()
                history.start_run(directory.name, repo=worktree, started_at=self.clock[0])
                state = {"run_id": directory.name, "state": "running", "pid": 101,
                         "repo": str(worktree), "worktree": str(worktree),
                         "started_at": self.clock[0], "waiting_on": {
                             "line": turn.name, "joined": self.clock[0], "land": "checked-tree"}}
                if recovery == "backoff":
                    state["deaths"] = [{"pid": 100, "at": 970.0, "resumed_at": 970.0}]
                record.save_state(directory, state)
                self.clock[0] = 1060.0
                if recovery == "backoff":
                    with patch.object(watch, "launch_resume") as launch:
                        watch.resume_dead_loops({}, now=self.clock[0], log=lambda _: None)
                        launch.assert_not_called()
                    state = record.read_state(directory)
                    self.assertEqual(state["resume_after"], 1570.0)
                else:
                    state = record.read_state(directory)
                    if recovery == "interrupted":
                        state["deaths"] = [{"pid": 101, "at": self.clock[0]}]
                        run.interrupt(state, "loop died")
                    elif recovery == "exhausted":
                        state.update(state="exhausted", quota_dry=True)
                    else:
                        state.update(state="waiting_login", waiting_for="fixture")
                    record.save_state(directory, state)
                self.assertIn(directory, [member for member, _ in land.line(turn)])
                # Its resume's slot admission keeps its place, then it delivers from it.
                self.clock[0] = 1570.0
                state.update(state="queued", slot_waiting=True, pid=102, queued_at=self.clock[0])
                record.save_state(directory, state)
                self.clock[0] = 1580.0
                state.update(state="running", slot_waiting=False)
                record.save_state(directory, state)
                self.clock[0] = 1585.0
                state.update(state="pass", merged=True, finished_at=self.clock[0])
                record.save_state(directory, state)
                self.assertEqual(self.waits(directory.name), (0.0, 0.0, 585.0))

    def test_a_queued_delivery_held_dead_keeps_its_line_place_counting(self):
        """Its slot wait stops while the tick holds it; its place in the line does not."""
        self.clock = [900.0]
        for module, name, options in (
                (time, "time", {"side_effect": lambda: self.clock[0]}),
                (record, "process_active", {"return_value": False}),
                (run, "memory_cap_reason", {"return_value": None}),
                (land, "start_line", {"return_value": False})):
            self.stack.enter_context(patch.object(module, name, **options))
        worktree = self.root / "acme"
        worktree.mkdir()
        turn = config.RUNS / ".merge-fixture.lock"
        for failure, pid in (("dead-waiter", 101), ("failed-launch", None)):
            with self.subTest(failure):
                self.clock[0] = 900.0
                directory = config.RUNS / f"fix-{failure}"
                directory.mkdir()
                (directory / "log.txt").touch()
                history.start_run(directory.name, repo=worktree, started_at=self.clock[0])
                state = {"run_id": directory.name, "state": "waiting", "pid": None,
                         "repo": str(worktree), "worktree": str(worktree),
                         "started_at": self.clock[0], "waiting_on": {
                             "line": turn.name, "joined": self.clock[0], "land": "checked-tree"}}
                record.save_state(directory, state)
                self.clock[0] = 1000.0
                state.update(state="queued", slot_waiting=True, pid=pid, queued_at=self.clock[0],
                             deaths=[{"pid": 100, "at": 970.0, "resumed_at": 970.0}])
                if pid is None:
                    state.update(process_identity=None, launch_pending=False,
                                 launch_error="fixture cannot launch")
                record.save_state(directory, state)
                self.clock[0] = 1060.0
                with patch.object(watch, "launch_resume") as launch:
                    watch.resume_dead_loops({}, now=self.clock[0], log=lambda _: None)
                    launch.assert_not_called()
                state = record.read_state(directory)
                self.assertEqual(state["resume_after"], 1570.0)
                self.assertIn(directory, [member for member, _ in land.line(turn)])
                self.clock[0] = 1570.0
                state.update(pid=102)
                record.save_state(directory, state)
                self.clock[0] = 1580.0
                state.update(state="running", slot_waiting=False)
                record.save_state(directory, state)
                self.clock[0] = 1585.0
                state.update(state="pass", merged=True, finished_at=self.clock[0])
                record.save_state(directory, state)
                self.assertEqual(self.waits(directory.name), (0.0, 0.0, 685.0))

    def test_a_landing_checks_wait_for_a_heavy_turn_is_kept_beside_the_line_wait(self):
        clock = [1000.0]
        for target, value in ((time, "time"), (time, "monotonic")):
            self.stack.enter_context(patch.object(target, value, lambda: clock[0]))
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1"}))
        for module, name, options in (
                (config, "max_gates", {"return_value": 1}),
                (run, "commit_identity", {"return_value": {"head_sha": "a", "tree_sha": "b"}}),
                (run, "git_out", {"return_value": (0, "")}),
                (gate, "run_done_when", {"return_value": (True, "passed")}),
                (land, "start_line", {"return_value": False})):
            self.stack.enter_context(patch.object(module, name, **options))
        scratch = self.root / "scratch"
        scratch.mkdir()
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        history.start_run(directory.name, repo="acme", started_at=clock[0])
        state = {"run_id": directory.name, "state": "waiting", "pid": None,
                 "repo": str(self.root / "acme"), "started_at": clock[0],
                 "waiting_on": {"line": ".merge-fixture.lock", "joined": clock[0]}}
        record.save_state(directory, state)
        with gate.gate_lock(None, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            def release(_seconds):
                clock[0] += 1800
                # The lander counts it as it polls, beside the line time the record keeps.
                self.assertEqual(history.get(directory.name)["lander_wait_seconds"], 0.0)
                fcntl.flock(holder, fcntl.LOCK_UN)
            with patch.object(time, "sleep", release):
                self.assertTrue(land._check(directory, state, scratch, ["true"],
                                            directory / "lander.log", lambda _: None)[0])
        self.assertEqual(history.get(directory.name)["lander_wait_seconds"], 1800.0)
        clock[0] += 1800
        with record.record(directory) as current:
            current.update(state="pass", merged=True, finished_at=clock[0])
        history.finish_run(directory.name, final_state="pass", finished_at=clock[0])
        self.assertEqual(self.waits(directory.name), (0.0, 0.0, 3600.0))
        self.assertEqual(history.get(directory.name)["lander_wait_seconds"], 1800.0)
        with patch.object(time, "time", return_value=clock[0]):
            self.assertIn("1.0 hours in a landing line, where checks waited 0.5 hours for a suite turn",
                          self.board_row())

    def test_a_landing_check_stops_counting_once_its_member_leaves_the_line(self):
        clock = [1000.0]
        for target, value in ((time, "time"), (time, "monotonic")):
            self.stack.enter_context(patch.object(target, value, lambda: clock[0]))
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1"}))
        for module, name, options in (
                (config, "max_gates", {"return_value": 1}),
                (run, "commit_identity", {"return_value": {"head_sha": "a", "tree_sha": "b"}}),
                (run, "git_out", {"return_value": (0, "")}),
                (gate, "run_done_when", {"return_value": (True, "passed")}),
                (land, "start_line", {"return_value": False})):
            self.stack.enter_context(patch.object(module, name, **options))
        scratch = self.root / "scratch"
        scratch.mkdir()
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        history.start_run(directory.name, repo="acme", started_at=clock[0])
        state = {"run_id": directory.name, "state": "waiting", "pid": None,
                 "repo": str(self.root / "acme"), "started_at": clock[0],
                 "waiting_on": {"line": ".merge-fixture.lock", "joined": clock[0]}}
        record.save_state(directory, state)
        polls = []
        with gate.gate_lock(None, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            def poll(_seconds):
                polls.append(clock[0])
                if len(polls) == 2:
                    # stopped from the line: its check no longer waits for finished work
                    record.save_state(directory, {**state, "state": "stopped"})
                clock[0] += 1800 if len(polls) == 1 else 600
                if len(polls) == 3:
                    fcntl.flock(holder, fcntl.LOCK_UN)
            with patch.object(time, "sleep", poll):
                land._check(directory, state, scratch, ["true"], directory / "lander.log",
                            lambda _: None)
        self.assertEqual(len(polls), 3)
        self.assertEqual(history.get(directory.name)["lander_wait_seconds"], 1800.0)

    def test_stopping_a_parked_member_closes_its_wait_once(self):
        lp, _ = self.line_loop()
        run.join_line(lp, "origin/main", lambda: True)
        run.release_line(lp.run_dir, lp.log)
        self.clock[0] += 30
        with record.record(lp.run_dir) as state:
            state.update(state="stopped", finished_at=self.clock[0])
            state.pop("waiting_on")
        self.assertEqual(self.waits(lp.run_dir.name)[2], 30.0)
        self.clock[0] += 40
        with record.record(lp.run_dir) as state:
            state["reported"] = True
        self.assertEqual(self.waits(lp.run_dir.name)[2], 30.0)

    def test_waits_add_up_across_resumes_and_an_older_row_stays_unrecorded(self):
        history.start_run("fix-api", repo="/home/fixture/code/acme")
        self.assertEqual(self.waits("fix-api"), (0.0, 0.0, 0.0))
        history.add_wait("fix-api", "slot", 30)
        history.start_run("fix-api", repo="/home/fixture/code/acme")     # a resume
        history.add_wait("fix-api", "slot", 12)
        history.add_wait("fix-api", "suite", 5)
        history.add_wait("fix-api", "merge", 60)
        self.assertEqual(self.waits("fix-api"), (42.0, 5.0, 60.0))
        self.before_the_waits("fix-ui", 1, 600)
        history.start_run("fix-ui", repo="/home/fixture/code/acme")      # resumed after the change
        history.add_wait("fix-ui", "slot", 30)
        self.assertEqual(self.waits("fix-ui"), (None, None, None))

    def test_history_sets_the_last_seven_days_beside_the_seven_before(self):
        self.finished("fix-api", 1, 3000, slot=30, suite=60)
        self.finished("fix-ui", 2, 1000, slot=30, merge=5400)
        self.finished("fix-db", 9, 2000, slot=300)
        self.finished("fix-doc", 4, 2000, state="not_needed", slot=180)  # waited, delivered nothing
        self.finished("fix-cli", 3, 1000, state="stopped", slot=1000)   # a stopped run teaches nothing
        self.finished("fix-old", 20, 1000, slot=1000)                   # older than both weeks
        self.before_the_waits("fix-log", 1, 100000)                    # not recorded, not zero
        board = scoreboard.compute(self.now)
        self.assertEqual(board["products"][0]["runs"], 3)     # the not-needed run is no ending to score
        recent, before = board["waits"]
        self.assertAlmostEqual(recent["compute"], 0.05)
        self.assertAlmostEqual(recent["merge_hours"], 1.5)
        self.assertAlmostEqual(before["compute"], 0.15)
        self.assertAlmostEqual(before["merge_hours"], 0.0)
        row = self.board_row()
        self.assertIn("5% of run time waiting for a slot or its own suite turn; 1.5 hours in a landing line", row)
        self.assertIn("15% of run time waiting for a slot or its own suite turn; 0.0 hours in a landing line", row)
        self.assertLess(row.index("5% of"), row.index("15% of"))     # the last 7 days come first

    def test_a_week_of_rows_from_before_the_waits_is_not_recorded(self):
        self.before_the_waits("fix-api", 1, 3000)
        self.before_the_waits("fix-ui", 9, 3000)
        self.assertEqual(scoreboard.compute(self.now)["waits"], [None, None])
        self.finished("fix-db", 2, 1000, slot=100)
        row = self.board_row()
        self.assertIn("10% of run time waiting for a slot or its own suite turn; 0.0 hours in a landing line", row)
        self.assertTrue(row.endswith("not recorded"), row)

    def test_a_week_with_a_row_from_before_the_check_waits_reads_them_as_not_recorded(self):
        self.finished("fix-api", 1, 3600, merge=3600)
        self.before_the_check_waits("fix-ui", 2, 3600, merge=3600)
        self.finished("fix-db", 9, 3600, merge=1800, lander=1440)
        recent, before = scoreboard.compute(self.now)["waits"]
        self.assertIsNone(recent["lander_hours"])
        self.assertAlmostEqual(recent["merge_hours"], 2.0)    # the line time it did keep still counts
        self.assertAlmostEqual(before["lander_hours"], 0.4)
        row = self.board_row()
        self.assertIn("2.0 hours in a landing line, where checks' waits for a suite turn are not "
                      "recorded", row)
        self.assertIn("0.5 hours in a landing line, where checks waited 0.4 hours for a suite turn", row)

if __name__ == "__main__":
    unittest.main()
