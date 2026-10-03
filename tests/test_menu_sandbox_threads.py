"""Menu sandbox cleanup waits for threads that enumerate exposes while still starting."""

import threading
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config


class SandboxThreads(unittest.TestCase):
    def test_a_starting_thread_finishes_before_its_home_and_mocks_go(self):
        begin, booting, release = (threading.Event() for _ in range(3))
        observed = []

        class PendingStart(Sandbox):
            def runTest(self):
                begin.set()
                self.assertTrue(booting.wait(5))
                self.assertIn(child, threading.enumerate())
                self.assertFalse(child.is_alive())

        case = PendingStart()
        child = threading.Thread(target=lambda: observed.append(
            (case.root.is_dir(), config.HOME == case.root / "home")), daemon=True)
        bootstrap, started_wait = child._bootstrap_inner, child._started.wait

        def pause_bootstrap():
            booting.set()
            release.wait(15)
            bootstrap()

        def wait_for_start(timeout=None):
            # The starter stays blocked; cleanup's wait lets the child finish starting.
            if threading.current_thread() is threading.main_thread():
                release.set()
            return started_wait(timeout)

        def start_child():
            begin.wait(15)
            child.start()

        with patch.object(child, "_bootstrap_inner", pause_bootstrap), \
                patch.object(child._started, "wait", wait_for_start):
            starter = threading.Thread(target=start_child, daemon=True)
            starter.start()  # before Sandbox's snapshot: this test owns the starter
            try:
                result = unittest.TestResult()
                case.run(result)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                self.assertEqual(observed, [(True, True)])
            finally:
                begin.set()
                release.set()
                starter.join(15)
                child.join(15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
