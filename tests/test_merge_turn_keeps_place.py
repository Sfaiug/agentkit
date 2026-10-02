"""A landing keeps its merge rank across laps, releases and an in-place pickup.

Offline: real queue flocks in a temporary HOME, injected git, process identities,
providers and exec. No real processes, units or installed checkout are touched.
"""

from contextlib import ExitStack, redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, host, record, run, worker


class KeepsPlace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-keeps-place-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": ""}))
        config.ensure_dirs()
        self.identity = {"boot": "this-boot", "ticks": 1}
        self.stack.enter_context(patch.object(host, "process_identity", return_value=self.identity))
        self.stack.enter_context(patch.object(host, "alive", return_value=True))
        self.stack.enter_context(patch.object(run, "raise_cpu_weight", return_value=None))
        self.stack.enter_context(patch.object(run, "merge_turn_files", return_value={"work.py"}))
        self.stack.enter_context(patch.object(run, "git", return_value="base"))
        self.stack.enter_context(patch.object(run, "fetch", return_value=(0, "")))
        self.stack.enter_context(patch.object(run, "wait_for_dependency", return_value=True))
        self.stack.enter_context(patch.object(run, "disjoint_move", return_value=False))
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        self.stack.enter_context(patch.object(run, "_PICKUP_START", "old"))
        self.stack.enter_context(patch.object(run, "installed_head", return_value="old"))
        self.errors, self.threads = [], []

    def loop(self, name, state=None):
        directory = config.RUNS / name
        directory.mkdir(exist_ok=True)
        wt = self.root / name
        wt.mkdir(exist_ok=True)
        state = state if state is not None else {
            "run_id": name, "state": "running", **record.process_owner(),
            "repo": str(wt), "worktree": str(wt), "base": "origin/main", "rounds": 3,
        }
        lp = SimpleNamespace(state=state, run_dir=directory, wt=wt, once=(),
                             base_sha="base", log=lambda _msg: None)
        lp.write = lambda: record.save_state(directory, state)
        lp.write()
        return lp

    def start(self, body):
        def caught():
            try:
                body()
            except BaseException as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=caught, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def finish(self):
        for thread in self.threads:
            thread.join(10)
            self.assertFalse(thread.is_alive(), "a merge waiter never finished")
        self.assertEqual(self.errors, [])
        self.assertFalse(list(config.RUNS.glob("*.wait")))

    def until(self, check):
        deadline = time.monotonic() + 10
        while not check():
            self.assertLess(time.monotonic(), deadline, "the merge waiter never arrived")
            time.sleep(0.01)

    def waiting(self, lp):
        self.until(lambda: run.merge_turn_note(record.read_state(lp.run_dir) or {}))

    def take(self, lp, order):
        with run.merge_turn(lp, "origin/main"):
            order.append(lp.run_dir.name)

    def test_target_move_keeps_later_waiters_behind_during_the_next_lap_gap(self):
        for first in (False, True):
            with self.subTest(first=first):
                early = self.loop(f"early-{first}")
                early.state["first"] = first
                late = self.loop(f"late-{first}")
                gap, resume, late_probed = threading.Event(), threading.Event(), threading.Event()
                order, ranks = [], []
                real_ahead = run.merge_turn_ahead

                def ahead(path, rank, **kw):
                    found = real_ahead(path, rank, **kw)
                    if threading.current_thread() is later and gap.is_set():
                        late_probed.set()
                    return found

                def pickup(lp, **kw):
                    if kw["extra"]["land_lap"] == 2:
                        gap.set()
                        self.assertTrue(resume.wait(10), "the next lap was never released")
                    return False

                def verify():
                    if ranks:
                        self.assertEqual(early.state.get("merge_rank"), ranks[0])
                    return True

                tips = iter(("moved", "base"))
                def git(_wt, *args, **_kw):
                    return next(tips) if args[0] == "rev-parse" else "base"

                def deliver():
                    order.append(early.run_dir.name)
                    return True

                path = run.turn_path(early, "origin/main")
                with patch.object(run, "pickup_new_code", side_effect=pickup), \
                        patch.object(run, "git", side_effect=git), \
                        patch.object(run, "merge_turn_ahead", side_effect=ahead), path.open("a") as held:
                    fcntl.flock(held, fcntl.LOCK_EX)
                    self.start(lambda: run.land(early, "origin/main", verify, deliver))
                    self.waiting(early)
                    ranks.append(early.state.get("merge_rank"))
                    later = self.start(lambda: self.take(late, order))
                    self.waiting(late)
                    fcntl.flock(held, fcntl.LOCK_UN)
                    try:
                        self.assertTrue(gap.wait(10), "the target never moved")
                        self.assertTrue(late_probed.wait(10), "the later waiter never probed the gap")
                        self.assertEqual(order, [], "a later waiter passed the landing between laps")
                    finally:
                        resume.set()
                    self.finish()
                self.assertEqual(order, [early.run_dir.name, late.run_dir.name])
                self.assertNotIn("merge_rank", record.read_state(early.run_dir))

    def test_releasing_for_a_fixer_or_reviewer_reuses_the_first_rank(self):
        early, late = self.loop("early"), self.loop("late")
        early.state["landing"] = True
        with run.merge_turn(early, "origin/main", reserve=True):
            rank = early.state.get("merge_rank")
            with run.released_gate_turn():
                self.assertIsNone(getattr(run._MERGE_HELD, "hold", None))
        order = []
        with run.turn_path(early, "origin/main").open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.start(lambda: self.take(late, order))
            self.waiting(late)

            def retake():
                with run.merge_turn(early, "origin/main", reserve=True):
                    self.assertEqual(early.state.get("merge_rank"), rank)
                    order.append("early")
                early.state.pop("landing")
                early.state.pop("merge_rank", None)
                early.write()

            self.start(retake)
            self.waiting(early)
            fcntl.flock(held, fcntl.LOCK_UN)
            self.finish()
        self.assertEqual(order, ["early", "late"])

    def test_a_reserved_lap_publishes_its_place_before_freeing_the_turn(self):
        early, late = self.loop("early"), self.loop("late")
        early.state["landing"] = True
        clearing, resume, taken = threading.Event(), threading.Event(), threading.Event()
        write = early.write

        def slow_write():
            saved = record.read_state(early.run_dir) or {}
            if saved.get("merge_hold") and not early.state.get("merge_hold"):
                clearing.set()
                self.assertTrue(resume.wait(10), "the holding mark was never saved")
            write()
        early.write = slow_write

        def first():
            with run.merge_turn(early, "origin/main", reserve=True):
                pass
            early.state.pop("landing")
            early.state.pop("merge_rank")
            early.write()

        def later():
            with run.merge_turn(late, "origin/main"):
                taken.set()

        self.start(first)
        try:
            self.assertTrue(clearing.wait(10), "the reserved lap never released")
            self.start(later)
            self.assertFalse(taken.wait(0.1), "a later run passed before the place was published")
        finally:
            resume.set()
        self.finish()
        self.assertTrue(taken.is_set())

    def test_pickup_keeps_a_live_place_until_the_resumed_landing_takes_it(self):
        early, late = self.loop("early"), self.loop("late")
        early.state["landing"] = True
        with run.merge_turn(early, "origin/main"):
            rank = early.state.get("merge_rank")
        order = []

        def execv(_path, _argv):
            self.start(lambda: self.take(late, order))
            self.waiting(late)
            self.assertEqual(order, [], "the place disappeared during exec")

        self.assertTrue(run.pickup_new_code(early, execv=execv, current="new",
                                            extra={"land_lap": 2}))

        def drive(_cfg, _directory, _opts, _log, prior=None, **_kw):
            resumed = self.loop("early", prior)
            self.assertEqual(resumed.state.get("merge_rank"), rank)
            return 0 if run.land(resumed, "origin/main", lambda: True,
                                 lambda: order.append("early") or True) else 1

        with patch.object(run, "drive", side_effect=drive), redirect_stdout(io.StringIO()):
            self.assertEqual(run.resume_run(["early"]), 0)
        self.finish()
        self.assertEqual(order, ["early", "late"])

    def test_a_rank_from_an_earlier_boot_is_not_reused(self):
        lp = self.loop("early")
        lp.state["landing"] = True
        old = {"of": run.turn_path(lp, "origin/main").name,
               "boot": "old-boot", "rank": "0" * 21, "joined": 1}
        lp.state["merge_rank"] = old
        with run.merge_turn(lp, "origin/main"):
            self.assertNotEqual(lp.state.get("merge_rank"), old)
            self.assertEqual(lp.state["merge_rank"]["boot"], "this-boot")

    def test_a_dead_stopped_or_old_boot_landing_does_not_hold_the_line(self):
        early, late = self.loop("early"), self.loop("late")
        early.state["landing"] = True
        with run.merge_turn(early, "origin/main"):
            pass
        for change in ({"process_identity": {"boot": "old", "ticks": 1}},
                       {"merge_rank": {**early.state["merge_rank"], "boot": "old-boot"}},
                       {"state": "stopped"}):
            with self.subTest(change=change):
                record.save_state(early.run_dir, {**early.state, **change})
                self.assertIsNone(run.merge_turn_ahead(run.turn_path(late, "origin/main"), "1" * 21))

    def test_a_finished_or_failed_landing_clears_its_rank(self):
        for result in (True, False):
            with self.subTest(result=result):
                lp = self.loop(f"landing-{result}")
                lp.once = ("true",)
                def verify():
                    self.assertIn("merge_rank", record.read_state(lp.run_dir))
                    return result
                self.assertEqual(run.land(lp, "origin/main", verify, lambda: True), result)
                self.assertNotIn("landing", record.read_state(lp.run_dir))
                self.assertNotIn("merge_rank", record.read_state(lp.run_dir))

    def test_equal_ranks_go_in_join_order_even_when_pids_sort_backwards(self):
        path = run.turn_path(self.loop("early"), "origin/main")
        places = []
        try:
            with patch.object(run.os, "getpid", return_value=9999):
                places.append(run.merge_turn_queue(path, "1" * 21, {"work.py"}))
            with patch.object(run.os, "getpid", return_value=1111):
                places.append(run.merge_turn_queue(path, "1" * 21, {"work.py"}))
            self.assertEqual(sorted(place[0] for place in places), [place[0] for place in places])
            self.assertEqual(run.merge_turn_ahead(path, "1" * 21), places[0][0])
        finally:
            for name, place in places:
                name.unlink(missing_ok=True)
                place.close()


if __name__ == "__main__":
    unittest.main()
