"""The tests a piece red on a machine named run here at once, one piece at a time, taking no turn on
this host. What then runs whole here, a piece that named none or one whose named tests passed alone,
waits for a turn."""

import threading
import time
import unittest
from unittest.mock import patch

import test_mac_failure_reruns_its_files as fixture
from agentkit import helper, worker


class RedTestsRerunAtOnce(unittest.TestCase):
    setUp, suite = fixture.MacFailureRerunsItsFiles.setUp, fixture.MacFailureRerunsItsFiles.suite
    turn = fixture.MacFailureRerunsItsFiles.turn

    def goes(self, failed=helper.failed, **env):
        """The suite's code, the most goes here at once, and each go: its piece, the tests it ran
        alone and the turns taken before it."""
        boxed, lock, running, most, goes = worker.boxed, threading.Lock(), [], [], []

        def watched(*args, only=None, **kw):
            with lock:
                running.append(1)
                most.append(len(running))
                goes.append((kw["env"]["AK_SHARD"], only, len(self.turns)))
            time.sleep(0.2)
            with lock:
                running.pop()
            return boxed(*args, only=only, **kw)
        with patch.object(worker, "boxed", watched), patch.object(helper, "failed", failed):
            code, _ = self.suite("tests/test_a.py\n", **env)
        return code, max(most), goes

    def test_named_tests_take_no_turn_and_go_one_piece_at_a_time(self):
        (self.fake / "code-3").write_text("1")
        self.assertEqual(self.goes(ACME_RED="1"), (1, 1, [("1/1", ["tests/test_a.py"], 0)] * 2))

    def test_named_tests_go_before_a_piece_that_named_none_waits_for_a_turn(self):
        (self.fake / "code-3").write_text("1")
        named = helper.failed

        def failed(away, shard, *args):    # piece 3/6 names none
            return [] if shard == "3/6" else named(away, shard, *args)
        self.assertEqual(self.goes(failed, ACME_RED="1"),
                         (1, 1, [("1/1", ["tests/test_a.py"], 0), ("3/6", None, 1)]))

    def test_a_piece_whose_named_tests_pass_alone_waits_for_a_turn_to_run_whole(self):
        self.assertEqual(self.goes(), (0, 1, [("1/1", ["tests/test_a.py"], 0), ("2/6", None, 1)]))


if __name__ == "__main__":
    unittest.main()
