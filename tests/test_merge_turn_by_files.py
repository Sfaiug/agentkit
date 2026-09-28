"""A reserved re-check blocks only overlapping branches; delivery stays serial.

Real local git remotes, kernel flocks and a temporary HOME. The shared landing
fixture stubs only providers and PR operations, and really squash-merges on origin.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from test_land_reserve import LandingCase, REPO, commit, make_origin, make_run
from agentkit import config, run, watch


class MergeTurnByFiles(LandingCase):
    def test_disjoint_runs_land_during_recheck_and_overlap_waits_for_holder(self):
        remote, owner = make_origin(self.root)
        one = make_run(self.root, remote, "acme", [
            f"echo every >> {self.counter}", f"echo once >> {self.counter} # once"],
            {"shared.txt": "acme\n2\n3\n4\n5\n"})
        overlap = make_run(self.root, remote, "overlap", ["true"],
                           {"shared.txt": "1\n2\noverlap\n4\n5\n"})
        two = make_run(self.root, remote, "bravo", ["true"])
        three = make_run(self.root, remote, "charlie", ["true"])
        commit(owner, "shared.txt", "1\n2\n3\n4\noutside")
        run.git(owner, "push", "origin", "main")

        def move(lp):
            if lp is one:
                self.queuing = None
                commit(owner, "shared.txt", "1\n2\n3\n4\nfive")
                run.git(owner, "push", "origin", "main")
        self.queuing = move
        checking, finish_check = threading.Event(), threading.Event()
        delivering, finish_delivery = threading.Event(), threading.Event()
        real_checks = run.run_done_when

        def checks(cmds, wt, *args, **kwargs):
            hold = getattr(run._MERGE_HELD, "hold", None)
            if Path(wt) == one.wt and hold is not None and not checking.is_set():
                checking.set()
                self.assertTrue(finish_check.wait(30), "holder's check was never released")
            return real_checks(cmds, wt, *args, **kwargs)

        def required(lp, url):
            if lp is two:
                delivering.set()
                self.assertTrue(finish_delivery.wait(30), "borrower was never released")
            return True

        results, threads = {}, []
        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "wait_checks", side_effect=required):
            try:
                threads.append(self.land(one, results))
                self.assertTrue(checking.wait(20), "holder never reached its reserved check")
                threads.append(self.land(overlap, results))
                self.until(lambda: run.merge_turn_note(run.read_state(overlap.run_dir) or {}),
                           "the overlapping branch to wait")
                threads.append(self.land(two, results))
                self.assertTrue(delivering.wait(20), "the disjoint borrower could not deliver")
                threads.append(self.land(three, results))
                self.until(lambda: run.merge_turn_note(run.read_state(three.run_dir) or {}),
                           "the second borrower to wait for delivery")
                self.assertEqual(run.merge_turn_note(run.read_state(two.run_dir)), "")
                self.assertEqual(run.merge_hold_note(run.read_state(one.run_dir)),
                                 "holding the merge turn of acme main to land")
                self.assertEqual(run.merge_turn_note(run.read_state(one.run_dir)), "")
                shown = io.StringIO()
                with redirect_stdout(shown):
                    run.cmd_status([])
                self.assertIn("holding the merge turn of acme main to land", shown.getvalue())
                self.assertIn("waiting for the merge turn of overlap main", shown.getvalue())
                self.assertNotIn("waiting for the merge turn of bravo main", shown.getvalue())
                finish_delivery.set()
                for thread in threads[2:]:
                    thread.join(20)
                    self.assertFalse(thread.is_alive(), "disjoint run waited for the holder")
                self.assertEqual(results, {two.state["run_id"]: True,
                                           three.state["run_id"]: True})
                self.assertEqual(self.merges, [("bravo", True), ("charlie", True)])
            finally:
                finish_delivery.set()
                finish_check.set()
                for thread in threads:
                    thread.join(30)
                    self.assertFalse(thread.is_alive(), "a landing never finished")
        self.assertEqual(results, {lp.state["run_id"]: True for lp in (one, two, three, overlap)})
        self.assertEqual(self.merges, [("bravo", True), ("charlie", True),
                                      ("acme", True), ("overlap", True)])
        self.assertEqual(self.counter.read_text().splitlines(), ["every", "once"] * 2)
        self.assertIn("none touching this branch's files; landing on the verified checks",
                      (one.run_dir / "log.txt").read_text())
        self.assertNotIn("waiting for the merge turn", (two.run_dir / "log.txt").read_text())
        self.assertFalse(list(config.RUNS.glob("*.hold")))
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertEqual((owner / "shared.txt").read_text(), "acme\n2\noverlap\n4\nfive\n")

    def test_holder_taking_back_its_turn_is_not_silent_and_lands_verified(self):
        remote, owner = make_origin(self.root)
        one = make_run(self.root, remote, "acme", [
            f"echo every >> {self.counter}", f"echo once >> {self.counter} # once"],
            {"shared.txt": "acme\n2\n3\n4\n5\n"})
        two = make_run(self.root, remote, "bravo", ["true"])
        commit(owner, "shared.txt", "1\n2\n3\n4\noutside")
        run.git(owner, "push", "origin", "main")

        def move(lp):
            if lp is one:
                self.queuing = None
                commit(owner, "shared.txt", "1\n2\n3\n4\nfive")
                run.git(owner, "push", "origin", "main")
        self.queuing = move
        checking, finish_check = threading.Event(), threading.Event()
        delivering, finish_delivery = threading.Event(), threading.Event()
        real_checks = run.run_done_when

        def checks(cmds, wt, *args, **kwargs):
            hold = getattr(run._MERGE_HELD, "hold", None)
            if Path(wt) == one.wt and hold is not None and not checking.is_set():
                checking.set()
                self.assertTrue(finish_check.wait(30), "holder's check was never released")
            return real_checks(cmds, wt, *args, **kwargs)

        def required(lp, url):
            if lp is two:
                delivering.set()
                self.assertTrue(finish_delivery.wait(30), "borrower was never released")
            return True

        results, threads = {}, []
        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "wait_checks", side_effect=required):
            try:
                threads.append(self.land(one, results))
                self.assertTrue(checking.wait(20), "holder never reached its reserved check")
                threads.append(self.land(two, results))
                self.assertTrue(delivering.wait(20), "the disjoint borrower could not deliver")
                # the holder finishes its re-check while the borrower still delivers
                finish_check.set()
                self.until(lambda: run.merge_retaking(run.read_state(one.run_dir) or {}),
                           "the holder to wait for its lent turn back")
                state = run.read_state(one.run_dir) or {}
                self.assertEqual(run.merge_turn_note(state), "")
                self.assertEqual(run.merge_hold_note(state),
                                 "holding the merge turn of acme main to land")
                self.assertEqual(run.slot_counts({"run_id": "probe"}), (2, 0))
                shown = io.StringIO()
                with redirect_stdout(shown):
                    run.cmd_status([])
                self.assertIn("holding the merge turn of acme main to land", shown.getvalue())
                self.assertNotIn("waiting for the merge turn of acme main", shown.getvalue())
                # a delivery holds the lock through required checks of up to an hour
                # with no child of the holder's running; the wait is still no stall
                old = time.time() - 25 * 60
                for path in one.run_dir.rglob("*"):
                    os.utime(path, (old, old))
                state = run.read_state(one.run_dir) or {}
                self.assertGreater(watch.stall_clock(one.run_dir, state), time.time() - 60)
                finish_delivery.set()
                for thread in threads:
                    thread.join(20)
                    self.assertFalse(thread.is_alive(), "a landing never finished")
            finally:
                finish_delivery.set()
                finish_check.set()
                for thread in threads:
                    thread.join(30)
                    self.assertFalse(thread.is_alive(), "a landing never finished")
        self.assertEqual(results, {lp.state["run_id"]: True for lp in (one, two)})
        self.assertEqual(self.merges, [("bravo", True), ("acme", True)])
        self.assertEqual(self.counter.read_text().splitlines(), ["every", "once"] * 2)
        self.assertIn("taking back the merge turn of acme main",
                      (one.run_dir / "log.txt").read_text())
        self.assertIn("none touching this branch's files; landing on the verified checks",
                      (one.run_dir / "log.txt").read_text())
        self.assertNotIn("merge_retake", run.read_state(one.run_dir))
        self.assertFalse(list(config.RUNS.glob("*.hold")))

    def take_turn(self, lp, entered, errors, upstream="origin/main", reserve=False):
        def body():
            try:
                with run.merge_turn(lp, upstream, reserve=reserve):
                    entered.set()
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        return thread

    def test_renames_deletions_and_unusual_paths_overlap(self):
        remote, owner = make_origin(self.root)
        names = ["old.txt", "gone.txt", " space\nname.txt"]
        for name in names:
            commit(owner, name, name)
        run.git(owner, "push", "origin", "main")
        holder = make_run(self.root, remote, "acme", ["true"])
        run.git(holder.wt, "mv", "old.txt", "new.txt")
        run.git(holder.wt, "rm", "gone.txt")
        commit(holder.wt, names[-1], "changed")
        threads, errors, events = [], [], []
        with run.merge_turn(holder, "origin/main", reserve=True):
            run.set_base(holder, holder.base_sha)
            try:
                for index, name in enumerate([*names, "new.txt"]):
                    lp = make_run(self.root, remote, f"touch-{index}", ["true"], {name: "edit\n"})
                    entered = threading.Event()
                    events.append(entered)
                    threads.append(self.take_turn(lp, entered, errors))
                    self.until(lambda: run.merge_turn_note(run.read_state(lp.run_dir) or {}),
                               f"the branch touching {name!r} to wait")
                    self.assertFalse(entered.is_set())
            finally:
                run.drop_reserved_turn()
                for thread in threads:
                    thread.join(20)
                    self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(all(event.is_set() for event in events))

    def test_disjoint_reservations_and_other_targets_can_take_the_turn(self):
        remote, owner = make_origin(self.root)
        one = make_run(self.root, remote, "acme", ["true"])
        two = make_run(self.root, remote, "bravo", ["true"])
        entered, errors = threading.Event(), []
        with run.merge_turn(one, "origin/main", reserve=True):
            run.set_base(one, one.base_sha)
            thread = self.take_turn(two, entered, errors, reserve=True)
            thread.join(20)
            self.assertFalse(thread.is_alive())
            self.assertTrue(entered.is_set())
            entered.clear()
            thread = self.take_turn(one, entered, errors, upstream="origin/dev")
            thread.join(20)
            self.assertFalse(thread.is_alive())
            self.assertTrue(entered.is_set())
        self.assertEqual(errors, [])

    def test_unknown_diff_waits_and_interruption_clears_the_reservation(self):
        remote, owner = make_origin(self.root)
        one = make_run(self.root, remote, "acme", ["true"])
        two = make_run(self.root, remote, "bravo", ["true"])
        entered, errors = threading.Event(), []
        real_git = run.git

        def unknown(wt, *args, **kwargs):
            if wt == two.wt and args[:1] == ("merge-base",):
                return ""
            return real_git(wt, *args, **kwargs)

        with patch.object(run, "git", side_effect=unknown):
            with self.assertRaises(run.Stopped):
                with run.merge_turn(one, "origin/main", reserve=True):
                    run.set_base(one, one.base_sha)
                    thread = self.take_turn(two, entered, errors)
                    self.until(lambda: run.merge_turn_note(run.read_state(two.run_dir) or {}),
                               "the unknown diff to wait")
                    self.assertFalse(entered.is_set())
                    raise run.Stopped("test interruption")
            thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertTrue(entered.is_set())
        self.assertEqual(errors, [])
        self.assertNotIn("merge_hold", run.read_state(one.run_dir))
        self.assertFalse(list(config.RUNS.glob("*.hold")))

    def test_dead_reservation_does_not_block_the_next_run(self):
        remote, owner = make_origin(self.root)
        one = make_run(self.root, remote, "acme", ["true"])
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agentkit import config, run
config.RUNS = Path(sys.argv[2])
directory = Path(sys.argv[3])
state = run.read_state(directory)
lp = run.Loop({}, directory, state, {}, lambda msg: None,
              Path(state['worktree']), '', [], '', [])
with run.merge_turn(lp, 'origin/main', reserve=True):
    run.set_base(lp, lp.base_sha)
    print('held', flush=True)
    sys.stdin.readline()
    os._exit(1)
"""
        holder = subprocess.Popen([sys.executable, "-c", code, str(REPO), str(config.RUNS),
                                   str(one.run_dir)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env={**os.environ, "HOME": str(self.root)})
        self.addCleanup(holder.stdin.close)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.stderr.close)
        entered, errors = threading.Event(), []
        thread = None
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            thread = self.take_turn(one, entered, errors)
            self.until(lambda: run.merge_turn_note(run.read_state(one.run_dir) or {}),
                       "an overlapping branch to wait for the child")
            holder.stdin.write("exit\n")
            holder.stdin.flush()
            self.assertEqual(holder.wait(20), 1)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait(20)
            if thread is not None:
                thread.join(20)
                self.assertFalse(thread.is_alive())
        self.assertTrue(entered.is_set())
        self.assertEqual(errors, [])
        self.assertFalse(list(config.RUNS.glob("*.hold")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
