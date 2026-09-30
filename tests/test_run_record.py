"""A write to a live run's record survives the loop's next save; `run.record` is how it lands.

The watcher's freeze marks and stall entries and a rename's `launched_session` are written
while the loop runs, holding a record of its own in memory: its next save merges what it
changed and keeps the rest.  The tick's passes change a record only through `run.record`,
and one it cannot read is left as it is.  Offline: a sandbox HOME, no real process, tmux or
seat.
"""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, orch, run, watch, worker


class Fixture(Sandbox):
    def setUp(self):
        super().setUp()
        # a worker running this file carries its own run's marker; nothing here may end it
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.run_dir = config.RUNS / "20260929-1710-fix-api"
        self.run_dir.mkdir(parents=True)
        run.save_state(self.run_dir, {
            "run_id": self.run_dir.name, "state": "running", "pid": 999999999,
            "launched_session": "lagoon", "base": "main", "rounds": 3, "executor": "opus",
            "reviewer": "astra", "round_summaries": [], "stalls": [], "silence_minutes": 17})
        self.lp = run.Loop({}, self.run_dir, run.read_state(self.run_dir), {}, lambda _: None,
                           self.root, "", [], "", [])
        self.stack.enter_context(patch.object(run, "run_dirs", return_value=[self.run_dir]))
        self.stack.enter_context(patch.object(run, "process_active", return_value=True))

    def loop_saves(self, step):
        self.lp.step(step)
        state = run.read_state(self.run_dir)
        self.assertEqual(state["step"], step)
        return state


class LiveRun(Fixture):
    def test_freeze_marks_survive_the_loops_next_save(self):
        with patch.object(watch, "frozen_cgroup", return_value="/agentkit.slice"):
            watch.recover_runs({}, log=lambda _: None, now=5000)
        self.assertEqual(self.loop_saves("execute")["frozen_since"], 5000)
        with patch.object(watch, "frozen_cgroup", return_value=None):
            watch.recover_runs({}, log=lambda _: None, now=6000)
        state = self.loop_saves("done-when")
        self.assertEqual(state["thawed_at"], 6000)
        self.assertNotIn("frozen_since", state)

    def test_a_stall_entry_survives_the_loops_next_save(self):
        child, argv = 999999998, ["bash", "-c", "sleep 600"]
        with patch.object(watch, "step_for_run",
                          return_value=("done-when", "done-when", child, argv)), \
                patch.object(watch, "loop_children", return_value=[(child, argv)]), \
                patch.object(watch, "run_last_write", return_value=1000), \
                patch.object(watch, "kill_tree") as kill, \
                patch.object(watch, "launch_resume") as resume:
            grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
            watch.recover_runs({}, log=lambda _: None, now=1000 + 17 * 60 + grace + 1)
        kill.assert_called_once()
        resume.assert_not_called()
        self.assertEqual([entry["action"] for entry in self.loop_saves("execute")["stalls"]],
                         ["killed step"])

    def test_a_renamed_launched_session_survives_the_loops_next_save(self):
        seat = {"name": "lagoon", "path": str(self.root), "created": 100, "attached": True,
                "exited": False, "legacy": False}
        config.save_session(self.cfg, "lagoon", "opus", ["astra"], {"cwd": str(self.root)})

        def tmux(*args, **kwargs):
            if args[0] == "rename-session":
                seat["name"] = args[-1]
            return 0, ""
        with patch.object(orch, "sessions", side_effect=lambda: [dict(seat)]), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "announce_state"), patch.object(watch, "sync_title"):
            self.assertEqual(orch.rename("lagoon", "quay", log=lambda _: None), "quay")
        self.assertEqual(self.loop_saves("execute")["launched_session"], "quay")

    def test_a_write_before_the_loop_is_built_survives_its_first_save(self):
        handed = run.read_state(self.run_dir)
        with patch.object(watch, "frozen_cgroup", return_value="/agentkit.slice"):
            watch.recover_runs({}, log=lambda _: None, now=5000)
        self.lp = run.Loop({}, self.run_dir, handed, {}, lambda _: None, self.root, "", [], "",
                           [])
        self.assertEqual(self.loop_saves("execute")["frozen_since"], 5000)

    def test_a_stop_between_two_saves_still_ends_the_loop(self):
        state = run.read_state(self.run_dir)
        run.save_state(self.run_dir, {**state, "state": "stopped"})
        with self.assertRaises(run.StopRequested):
            self.lp.step("execute")
        self.assertEqual(run.read_state(self.run_dir)["state"], "stopped")


class MergePipeline(Fixture):
    """The merge pipeline's saves merge what the loop changed, as `Loop.save` does."""

    def survives(self, save):
        self.lp.save()
        with run.record(self.run_dir) as current:
            current["frozen_since"] = 5000
        save()
        state = run.read_state(self.run_dir)
        self.assertEqual(state["frozen_since"], 5000)
        return state

    def test_a_note(self):
        state = self.survives(lambda: run.note(self.lp, "the PR is closed", failed=True))
        self.assertEqual(state["merge_note"], "the PR is closed")

    def test_parking_waiting(self):
        state = self.survives(lambda: run.park_waiting(self.lp, "red", "origin/main", "abc"))
        self.assertEqual((state["state"], state["waiting_on"]),
                         ("waiting", {"ref": "origin/main", "sha": "abc"}))

    def test_the_merge_turns_release(self):
        self.lp.state["merge_hold"] = {"pid": 1, "of": "acme main"}
        self.assertNotIn("merge_hold", self.survives(run._MergeHold(None, self.lp, True).release))

    def test_a_final_check(self):
        self.lp.once, self.lp.every = ["true"], []
        with patch.object(run, "git", return_value="a" * 40), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "commit_identity", return_value={"head_sha": "a" * 40,
                                                                   "tree_sha": "b" * 40}), \
                patch.object(run, "run_done_when", return_value=(True, "$ true\n[exit 0]")):
            state = self.survives(lambda: self.assertTrue(run.final_check(self.lp, "origin/main")))
        self.assertEqual(state["final_check"]["outcome"], "passed")

    def test_a_stop_still_ends_a_pipeline_save_and_a_release_still_lets_go(self):
        run.save_state(self.run_dir, {**run.read_state(self.run_dir), "state": "stopped"})
        with self.assertRaises(run.StopRequested):
            run.note(self.lp, "the PR is closed")
        self.lp.state["merge_hold"] = {"pid": 1, "of": "acme main"}
        run._MergeHold(None, self.lp, True).release()     # its fallback, not a raise
        self.assertNotIn("merge_hold", self.lp.state)
        self.assertEqual(run.read_state(self.run_dir)["state"], "stopped")


class Contract(Fixture):
    def writes(self):
        return patch.object(run, "_write_state", wraps=run._write_state)

    def test_a_record_writes_once_and_only_when_something_changed(self):
        with self.writes() as write:
            with run.record(self.run_dir) as state:
                self.assertEqual(state["state"], "running")
            write.assert_not_called()
            with run.record(self.run_dir) as state:
                state["thawed_at"] = 7000
                state.pop("stalls")
            write.assert_called_once()
        state = run.read_state(self.run_dir)
        self.assertEqual(state["thawed_at"], 7000)
        self.assertNotIn("stalls", state)

    def test_flush_writes_early_and_the_exit_writes_only_what_came_after(self):
        with self.writes() as write:
            with run.record(self.run_dir) as state:
                state["stall_resume_at"] = 7000
                state.flush()
                self.assertEqual(run.read_state(self.run_dir)["stall_resume_at"], 7000)
                state.flush()
            self.assertEqual(write.call_count, 1)

    def test_an_exception_writes_nothing(self):
        with self.assertRaises(KeyError):
            with run.record(self.run_dir) as state:
                state["thawed_at"] = 7000
                raise KeyError("thawed_at")
        self.assertNotIn("thawed_at", run.read_state(self.run_dir))

    def test_a_record_keeps_the_stop_guard(self):
        run.save_state(self.run_dir, {**run.read_state(self.run_dir), "state": "stopped"})
        with self.assertRaises(run.StopRequested):
            with run.record(self.run_dir) as state:
                state["state"] = "running"
        self.assertEqual(run.read_state(self.run_dir)["state"], "stopped")
        # a stopped record still takes a mark that leaves it stopped: a rename's, say
        with run.record(self.run_dir) as state:
            state["launched_session"] = "quay"
        self.assertEqual(run.read_state(self.run_dir)["launched_session"], "quay")

    def test_a_delivery_and_a_save_never_share_a_temporary_file(self):
        temps, real = [], Path.replace

        def replacing(path, target):
            temps.append(path.name)
            return real(path, target)
        state = run.read_state(self.run_dir)
        with patch.object(Path, "replace", replacing):
            run.save_state(self.run_dir, {**state, "step": "execute"})
            with run.record(self.run_dir) as current:
                current["step"] = "done-when"
            run.mark_delivery(self.run_dir, state, handback_pending=True)
        self.assertEqual(len(temps), 3)
        self.assertEqual(temps[0], temps[1])
        self.assertNotEqual(temps[1], temps[2])
        self.assertTrue(run.read_state(self.run_dir)["handback_pending"])

    def test_an_unreadable_record_is_left_as_it_is_and_the_caller_learns_it(self):
        path = self.run_dir / "run.json"
        path.write_text('{"state": "runn')
        with self.assertRaises(run.Unreadable), self.writes() as write:
            with run.record(self.run_dir) as state:
                state["thawed_at"] = 7000
        write.assert_not_called()
        self.assertEqual(path.read_text(), '{"state": "runn')
        path.unlink()
        with self.assertRaises(run.Unreadable):
            with run.record(self.run_dir) as state:
                state["thawed_at"] = 7000
        self.assertFalse(path.exists())


class Tick(Fixture):
    """Each pass changes a record through `record`, onto the record as it stands under the lock.

    `between` changes run.json right after the pass's first read, before its locked one.  A
    torn record there is left byte for byte, and so is a key another writer set when the locked
    read fails for a moment: the pass never writes the copy it read first, and says why.
    """
    NOW = 10000

    def setUp(self):
        super().setUp()
        self.base = run.read_state(self.run_dir)
        for target, name, value in (
                (run, "process_active", False),        # every loop here is gone
                (run, "is_superseded", True),          # a later merged run did the work
                (run, "tick_admission", True),
                (run, "exhausted_wait", "window"),
                (run, "run_workers", []),
                (run, "executable_models", []),
                (run, "run_scope_limits", (None, [])),
                (run, "spawn_bg", 0),
                (config, "role_groups", (None, None)),
                (worker, "auth_ok", (True, "")),       # the login is back
                (watch, "tell_parked", True),          # the parking's notice lands
                (orch, "start_in_slice", 4242)):
            self.stack.enter_context(patch.object(target, name, return_value=value))
        self.stack.enter_context(patch.object(watch.usage, "readiness",
                                              side_effect=lambda cfg, providers: providers))

    def passes(self):
        gone, now = str(self.root / "gone"), self.NOW
        return (
            ("resume_dead_loops", {"worktree": gone},
             lambda log: watch.resume_dead_loops(log=log, now=now)),
            ("recover_runs", {"state": "stalled"},
             lambda log: watch.recover_runs({}, log=log, now=now)),
            ("resume_waiting_login", {"state": "waiting_login", "waiting_for": "claude"},
             lambda log: watch.resume_waiting_login(log=log, now=now)),
            ("resume_exhausted", {"state": "exhausted"},
             lambda log: watch.resume_exhausted({}, {}, [], log=log, now=now)),
            ("resume_errored", {"state": "error", "error_retry_at": now},
             lambda log: watch.resume_errored(log=log, now=now)),
            ("resume_waiting", {"state": "waiting", "worktree": gone},
             lambda log: watch.resume_waiting(log=log, now=now)))

    def tear(self):
        (self.run_dir / "run.json").write_text('{"state": "runn')

    def another_writer(self):
        """A mark landing past the pass's lock, as `mark_delivery`'s does."""
        path = self.run_dir / "run.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "handback_pending": True}))

    def tick(self, state, run_pass, between, fail=False):
        """One pass over `state`, with `between` right after its first read; the pass's log.

        With `fail`, every read under the lock after that finds nothing, as a read can for a
        moment (too many open files) on a record that is whole.  `self.between` is what
        run.json held once `between` ran.
        """
        run.save_state(self.run_dir, {**self.base, **state})
        path, real, logs, self.between = self.run_dir / "run.json", run.read_state, [], None

        def read(run_dir):
            if self.between is None:
                first = real(run_dir)
                between()
                self.between = path.read_bytes()
                return first
            locked = str(run_dir) in getattr(run._RECOVERY_HELD, "paths", ())
            return None if fail and locked else real(run_dir)
        with patch.object(run, "read_state", side_effect=read):
            run_pass(logs.append)
        return logs

    def test_every_pass_leaves_a_record_it_cannot_read_as_it_is_and_says_so(self):
        for name, state, run_pass in self.passes():
            for between, fail in ((self.tear, False), (self.another_writer, True)):
                with self.subTest(name, between=between.__name__):
                    logs = self.tick(state, run_pass, between, fail)
                    self.assertEqual((self.run_dir / "run.json").read_bytes(), self.between)
                    self.assertTrue(any(line.startswith("WARN")
                                        and "run.json cannot be read" in line
                                        for line in logs), logs)

    def test_every_pass_keeps_a_key_another_writer_set_while_it_decided(self):
        for name, state, run_pass in self.passes():
            with self.subTest(name):
                self.tick(state, run_pass, self.another_writer)
                self.assertNotEqual((self.run_dir / "run.json").read_bytes(), self.between)
                self.assertTrue(run.read_state(self.run_dir)["handback_pending"])

    def test_a_launch_leaves_a_record_it_cannot_read_as_it_is_and_says_so(self):
        launch = lambda log: watch.launch_resume(self.run_dir.name, log)
        for between, fail in ((self.tear, False), (self.another_writer, True)):
            with self.subTest(between.__name__):
                with self.assertRaises(run.Unreadable):
                    self.tick({}, launch, between, fail)
                self.assertEqual((self.run_dir / "run.json").read_bytes(), self.between)
        self.tick({"scope": "none"}, launch, self.another_writer)
        state = run.read_state(self.run_dir)
        self.assertTrue(state["handback_pending"])
        self.assertIsNone(state["scope"])     # the launch's own placement, empty in a fake start


if __name__ == "__main__":
    unittest.main(verbosity=2)
