"""Delivery lock contention is waiting, not silence. Offline, with a fake live process."""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, record, run, watch

PID = 999999991


class DeliveryWait(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-delivery-wait-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": ""}))
        self.stack.enter_context(patch.object(run.os, "getpid", return_value=PID))
        self.stack.enter_context(patch.object(record, "process_active", return_value=True))
        self.stack.enter_context(patch.object(run, "git", return_value="base"))
        config.ensure_dirs()
        directory = config.RUNS / "acme-waiter"
        directory.mkdir()
        (directory / "log.txt").touch()
        state = {"run_id": directory.name, "state": "running", "pid": PID,
                 "repo": str(self.root / "acme"), "rounds": 3, "base": "origin/main"}
        self.lp = SimpleNamespace(state=state, run_dir=directory, wt=self.root / "acme",
                                  base_sha="base", log=lambda _: None)
        self.lp.write = lambda: record.save_state(directory, state)
        self.lp.write()

    def age_files(self):
        old = time.time() - 3600
        for path in self.lp.run_dir.rglob("*"):
            os.utime(path, (old, old))
        return old

    def test_land_wait_is_not_stalled_and_clears_before_delivery(self):
        lp = self.lp
        waiting = threading.Event()
        flock = fcntl.flock
        path = run.turn_path(lp, "origin/main")

        def observe_wait(lock, operation):
            if operation == fcntl.LOCK_EX and getattr(lock, "name", None) == str(path):
                waiting.set()
            return flock(lock, operation)

        results, errors = [], []
        verify = Mock(return_value=True)

        def delivered():
            self.assertNotIn("delivery_wait", record.read_state(lp.run_dir))
            return True

        deliver = Mock(side_effect=delivered)

        def land():
            try:
                results.append(run.land(lp, "origin/main", verify, deliver))
            except BaseException as error:
                errors.append(error)

        with path.open("a") as holder:
            flock(holder, fcntl.LOCK_EX)
            with patch.object(run, "pickup_new_code", return_value=False), \
                    patch.object(run, "fetch", return_value=(0, "")), \
                    patch.object(run.fcntl, "flock", side_effect=observe_wait):
                waiter = threading.Thread(target=land, daemon=True)
                waiter.start()
                try:
                    self.assertTrue(waiting.wait(10), errors)
                    deliver.assert_not_called()
                    self.age_files()
                    state = record.read_state(lp.run_dir)
                    self.assertGreater(watch.stall_clock(lp.run_dir, state), time.time() - 60)
                finally:
                    flock(holder, fcntl.LOCK_UN)
                    waiter.join(10)
                self.assertFalse(waiter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [True])
        verify.assert_called_once()
        deliver.assert_called_once()
        self.assertNotIn("delivery_wait", record.read_state(lp.run_dir))
        old = self.age_files()
        self.assertLess(watch.stall_clock(lp.run_dir, record.read_state(lp.run_dir)), old + 1)

    def test_dead_or_resumed_wait_does_not_exempt_silence(self):
        old = self.age_files()
        for alive, pid in ((False, PID), (True, PID + 1)):
            with self.subTest(alive=alive, pid=pid), \
                    patch.object(record, "process_active", return_value=alive):
                state = {**self.lp.state, "delivery_wait": pid}
                self.assertLess(watch.stall_clock(self.lp.run_dir, state), old + 1)

    def test_interrupted_lock_wait_clears_its_mark(self):
        path = run.turn_path(self.lp, "origin/main")
        flock = fcntl.flock
        errors = iter((BlockingIOError(), OSError("stopped")))

        def interrupt(lock, operation):
            if getattr(lock, "name", None) == str(path):
                raise next(errors)
            return flock(lock, operation)

        with patch.object(run.fcntl, "flock", side_effect=interrupt):
            with self.assertRaises(OSError):
                with run.merge_lock(self.lp, "origin/main"):
                    self.fail("an interrupted waiter cannot deliver")
        self.assertNotIn("delivery_wait", record.read_state(self.lp.run_dir))
        self.assertEqual(getattr(run._PICKUP_HELD, "count", 0), 0)


if __name__ == "__main__":
    unittest.main()
