"""A menu waits out reads that are merely slow before it starts over (`Live.stuck`): a read is
timed from the ask it answers, the watcher's record checks before it included, and STUCK times
the slowest lately is waited, in the menu started again too.  On the clock `menu.CLOCK` reads,
injected; tests/test_key_a_menu_whose_reads_stopped_starts_over.py starts one over from outside.
"""

import os
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import menu

GROUPS = ([], [], 0, {})


class SlowReads(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 0.0
        self.stack.enter_context(patch.object(menu, "CLOCK", lambda: self.now))

    def live(self):
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        live.last = [[], None]
        return live

    def test_a_round_is_timed_from_its_ask_its_record_checks_and_all(self):
        live, rounds, said = self.live(), [], []

        def wait(_timeout):
            live.done.set() if len(rounds) == 3 else live.ask()
            return True

        def recorded():               # 40 s of stats before each read; the third asked about
            rounds.append(self.now)
            self.now += 31
            if len(rounds) == 3:
                said.append(live.stuck())
            self.now += 9
            return [self.now]

        def rows(*_args):
            self.now += 1
            return [], [], GROUPS

        with patch.object(live.asked, "wait", side_effect=wait), \
                patch.object(live, "recorded", side_effect=recorded), \
                patch.object(live, "configure"), patch.object(menu, "rows", side_effect=rows):
            live._watch()
        self.assertEqual(rounds, [0, 41, 82])
        self.assertEqual(said, [""])

    def test_a_twenty_second_read_is_waited_out_two_hundred_seconds_after_a_restart_too(self):
        live = self.live()

        def rows(*_args):
            self.now += 20
            return [], [], GROUPS

        with patch.object(menu, "rows", side_effect=rows):
            live.read()
        with patch.dict(os.environ, live.hand_on()):
            again = self.live()
        for menu_ in (live, again):
            menu_.ask()
            self.now += 199
            self.assertEqual(menu_.stuck(), "")
            self.now += 1
            self.assertIn("menu started over", menu_.stuck())


if __name__ == "__main__":
    unittest.main()
