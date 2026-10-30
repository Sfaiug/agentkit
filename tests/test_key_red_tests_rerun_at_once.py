"""The tests a piece red on a machine named run here at once, one piece at a time, taking no turn on
this host. A piece that named none still waits for a turn."""

import threading
import time
import unittest
from unittest.mock import patch

import test_mac_failure_reruns_its_files as fixture
from agentkit import worker


class RedTestsRerunAtOnce(unittest.TestCase):
    setUp, suite = fixture.MacFailureRerunsItsFiles.setUp, fixture.MacFailureRerunsItsFiles.suite
    turn = fixture.MacFailureRerunsItsFiles.turn

    def test_named_tests_take_no_turn_and_go_one_piece_at_a_time(self):
        (self.fake / "code-3").write_text("1")
        boxed, lock, running, most = worker.boxed, threading.Lock(), [], []

        def watched(*args, **kw):
            with lock:
                running.append(1)
                most.append(len(running))
            time.sleep(0.2)
            with lock:
                running.pop()
            return boxed(*args, **kw)
        with patch.object(worker, "boxed", watched):
            code, text = self.suite("tests/test_a.py\n", ACME_RED="1")
        self.assertEqual(code, 1, text)
        self.assertIn("listed [tests/test_a.py]", text)
        self.assertEqual((self.turns, max(most)), ([], 1))

    def test_a_piece_that_named_none_waits_for_a_turn(self):
        self.suite()
        self.assertTrue(self.turns)


if __name__ == "__main__":
    unittest.main()
