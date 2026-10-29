"""A launch waiting for its slot moves to the installed agentkit when it moves: between polls it
replaces itself with the same launch on the new code, which takes up the same receipt and so
keeps its place in line, and a change to admission reaches the runs already waiting.

Offline: temporary HOME, fake run records, an injected exec and installed version; the exec is
an exception wherever the real wait runs, and no test execs or signals a real process.
"""

from contextlib import ExitStack
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, gate, handback, history, job as jobs, record, run, waiter

OLD = "aaa1111"
NEW = "bbb2222"


class Replaced(Exception):
    """The exec: the waiting process gives way to the same launch on the new code."""


class QueuedRunWaitsOnTheInstalledCode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-queued-pickup-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.run_dir = config.RUNS / "20990101-0000-acme-fix"
        self.run_dir.mkdir()
        (self.run_dir / "log.txt").write_text("launch\n")
        self.queued_at = time.time() - 600
        record.save_state(self.run_dir, {
            "run_id": self.run_dir.name, "state": "queued", "slot_waiting": True,
            "queued_at": self.queued_at, "started_at": self.queued_at, "run_depth": 0,
            **record.process_owner()})
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.RUN_DIR_ENV: str(self.run_dir), "AK_MAX_RUNS": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0"}))
        stack.enter_context(patch.object(handback, "redress_seat"))
        stack.enter_context(patch("sys.stdout", StringIO()))
        stack.enter_context(patch.object(run, "_PICKUP_START", OLD))
        self.execs = []

    def pickup(self, current=NEW):
        return run.pickup_while_queued(self.run_dir, execv=lambda *a: self.execs.append(a),
                                       current=current)

    def test_a_waiting_launch_moves_to_the_installed_code_as_the_same_launch(self):
        self.assertTrue(self.pickup())
        self.assertEqual(self.execs, [(sys.executable, [sys.executable, str(config.REPO / "bin" / "ak"), *sys.argv[1:]])])
        self.assertIn(f"picked up agentkit {OLD}..{NEW} while waiting for a slot",
                      (self.run_dir / "log.txt").read_text())

    def test_a_launch_stays_where_it_cannot_move_as_itself(self):
        def job():
            jobs._JOB_MUTE.depth = 1
            try:
                return self.pickup()
            finally:
                jobs._JOB_MUTE.depth = 0

        def thread():
            moved = []
            worker = threading.Thread(target=lambda: moved.append(self.pickup()))
            worker.start()
            worker.join(60)
            return moved[0]

        other = str(config.RUNS / "20990101-0000-acme-other")
        for case, stays in (
                ("a foreground launch", lambda: patch.dict(os.environ, {config.RUN_DIR_ENV: ""})),
                ("another run's launch", lambda: patch.dict(os.environ,
                                                            {config.RUN_DIR_ENV: other})),
                ("the same code", lambda: patch.object(run, "installed_head", return_value=OLD)),
                ("no version", lambda: patch.object(run, "installed_head", return_value="")),
                ("no start", lambda: patch.object(run, "_PICKUP_START", None))):
            with self.subTest(case=case), stays():
                self.assertFalse(run.pickup_while_queued(
                    self.run_dir, execv=lambda *a: self.execs.append(a)))
        for case, call in (("a job's thread", job), ("a thread", thread)):
            with self.subTest(case=case):
                self.assertFalse(call())
        self.assertEqual(self.execs, [])

    def test_the_launch_taken_up_again_keeps_its_place_and_its_reason(self):
        held = [True]

        def admits(state, readings, is_first):
            if held[0]:
                state.update(slot_waited=True, slot_wait_kind="memory",
                             slot_wait_reason="waiting for ak's memory")
            return not held[0]

        def between(_behind):
            raise Replaced

        with patch.object(gate, "SLOT_POLL", 0), patch.object(gate, "_host_admits", admits):
            with self.assertRaises(Replaced):
                gate.wait_for_slot(self.run_dir, between=between)
            waiting = record.read_state(self.run_dir)
            self.assertEqual((waiting["state"], waiting["queued_at"], waiting["pid"]),
                             ("queued", self.queued_at, os.getpid()))
            held[0] = False     # the new code admits it
            state = gate.wait_for_slot(self.run_dir, between=between)
        self.assertEqual((state["state"], state["queued_at"]), ("running", self.queued_at))
        self.assertEqual(record.read_state(self.run_dir)["state"], "running")
        self.assertTrue((self.run_dir / "log.txt").read_text().startswith(
            "waited 10 min for a slot (memory)\n"))

    def test_a_launch_stopped_as_it_waits_ends_in_the_new_process(self):
        task = self.root / "acme.md"
        task.write_text("# Acme fix\n\nFix the widget.\n\n## Done when\n```bash\ntrue\n```\n")
        state = record.read_state(self.run_dir)
        state.update(state="stopped", verdict="STOPPED", slot_waiting=False)
        record.save_state(self.run_dir, state)
        with patch.object(box, "check"), patch.object(config, "active_session", return_value=None), \
                patch.object(config, "load", return_value={"defaults": {"workers": ["opus"]}}), \
                patch.object(run, "prepare") as prepare:
            with self.assertRaisesRegex(config.Error, "was stopped before it could start"):
                run.main([str(task)])
        prepare.assert_not_called()
        self.assertEqual([path.name for path in config.RUNS.iterdir() if path.is_dir()],
                         [self.run_dir.name])

    def test_the_slot_s_wait_offers_the_move_after_each_poll(self):
        offered = []

        def wait_for_slot(run_dir, between=None):
            between(None)
            return {"state": "running", "queued_at": self.queued_at}

        with patch.object(gate, "wait_for_slot", wait_for_slot), \
                patch.object(run, "pickup_while_queued", lambda *a: offered.append(a)):
            with run.run_slot(self.run_dir):
                pass
        self.assertEqual(offered, [(self.run_dir, None)])

    def test_a_launch_behind_the_first_waits_in_the_waiter_and_comes_back_counted(self):
        self.assertTrue(run.pickup_while_queued(self.run_dir, (1000.0, 5.0),
                                                execv=lambda *a: self.execs.append(a)))
        ak = [sys.executable, str(config.REPO / "bin" / "ak"), *sys.argv[1:]]
        self.assertEqual(self.execs, [(sys.executable, [
            sys.executable, "-I", "-S", waiter.__file__, str(config.RUNS / ".slots.queue"),
            str(config.HOME / "history.db"), self.run_dir.name, str(gate.SLOT_POLL),
            str(config.REPO), OLD, *ak])])
        self.assertEqual(os.environ[waiter.SLOT_WAIT_ENV], "1000.0 5.0")
        counted = []
        with patch.object(gate, "count_wait", lambda *a: counted.append(a)), \
                patch.object(gate, "_host_admits", return_value=True):
            state = gate.wait_for_slot(self.run_dir)
        self.assertEqual((state["state"], state["slot_waited"]), ("running", True))
        self.assertEqual(counted, [(self.run_dir.name, "slot", (1000.0, 5.0))])
        self.assertNotIn(waiter.SLOT_WAIT_ENV, os.environ)

    def test_a_launch_the_waiter_hands_back_still_waiting_redraws_no_bar(self):
        """Every waiter comes back when the install moves; only a launch's first wait is news."""
        def back_to_the_waiter(counted):
            raise Replaced

        for handed, redrawn in (("", 1), ("1000.0 5.0", 0)):
            with self.subTest(handed=handed):
                handback.redress_seat.reset_mock()
                os.environ[waiter.SLOT_WAIT_ENV] = handed
                with patch.object(gate, "count_wait", lambda run_id, wait, counted: counted), \
                        patch.object(gate, "_host_admits", return_value=False), \
                        patch.object(gate.time, "sleep", lambda seconds: None), \
                        self.assertRaises(Replaced):
                    gate.wait_for_slot(self.run_dir, back_to_the_waiter)
                self.assertEqual(handback.redress_seat.call_count, redrawn)


    def test_a_waiter_killed_behind_the_first_has_counted_each_poll(self):
        clock = [1000.0]

        def sleep(seconds):
            if clock[0] >= 1090:
                raise Replaced     # killed while still behind the first
            clock[0] += seconds
            (config.RUNS / ".slots.queue").write_text(json.dumps(
                {"at": clock[0], "queue": ["20990101-0000-acme-older", self.run_dir.name]}))

        history.start_run(self.run_dir.name, repo="acme", started_at=clock[0])
        os.environ[waiter.SLOT_WAIT_ENV] = "1000.0 1000.0"
        with patch.object(waiter.time, "sleep", sleep), \
                patch.object(waiter.time, "time", lambda: clock[0]), \
                patch.object(waiter.time, "monotonic", lambda: clock[0]), \
                self.assertRaises(Replaced):
            waiter.main([str(config.RUNS / ".slots.queue"), str(history.path()),
                         self.run_dir.name, "30", str(config.REPO), ""])
        self.assertEqual(history.get(self.run_dir.name)["slot_wait_seconds"], 90)
        self.assertEqual(history.phases(self.run_dir.name),
                         [{"phase": "slot wait", "started_at": 1000.0, "ended_at": 1090.0}])

    def test_an_install_move_brings_the_line_back_in_order_over_a_poll(self):
        line, clock = [f"20990101-000{n}-acme-fix" for n in range(5)], [0.0]

        def sleep(seconds):     # its first polls on: the queue stays fresh
            clock[0] += seconds
            (config.RUNS / ".slots.queue").write_text(json.dumps({"at": clock[0], "queue": line}))

        def back(apart):        # each one's polls `apart` before the one ahead's
            returns = []
            for place, run_id in enumerate(line[1:], 1):
                clock[0] = 1000.0 - apart * place
                os.environ[waiter.SLOT_WAIT_ENV] = f"{clock[0]} {clock[0]}"
                with patch.multiple(waiter.time, sleep=sleep, time=lambda: clock[0],
                                    monotonic=lambda: clock[0]), \
                        patch.object(waiter, "head", return_value=NEW), \
                        patch.object(waiter.os, "execv", side_effect=Replaced), \
                        self.assertRaises(Replaced):
                    waiter.main([str(config.RUNS / ".slots.queue"), str(history.path()), run_id,
                                 "30", str(config.REPO), OLD, "ak"])
                returns.append(clock[0])
            return returns
        # each sees the move at its first poll: in step, as one move leaves them, the line comes
        # back in order, and whatever their phases no two come back within a fifth of a poll
        in_step = back(0)
        self.assertEqual(in_step, sorted(in_step))
        for returns in (in_step, sorted(back(6))):
            self.assertGreaterEqual(min(b - a for a, b in zip(returns, returns[1:])), 6, returns)


if __name__ == "__main__":
    unittest.main()
