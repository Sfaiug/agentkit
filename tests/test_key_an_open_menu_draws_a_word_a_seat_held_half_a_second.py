"""An open menu draws a word a seat held for half a second.

A screen looked at its seats' records once a second, so a word a seat's record said for less
was read only if a look happened to fall on it, and any word was drawn up to a second late.
It now looks more often, so a word that comes and goes is seen, on a screen listing sixty gone
seats too, whose records each look stats as well: one that waited for a look a multiple of what
the last one cost waited longer the more seats it listed.
The word is `working`, written to a seat's record and taken back HOLD later for a word the
screen then shows: the read the next try starts from, so no try rides on when the last look
fell.  A loaded host may still miss one, and a screen looking once a second catches the odd
one, so the word is drawn more often than not.  Black-box: the program `AK_BIN` names runs in a
person's terminal (tests/fixtures/akterm.py) beside seats of tests/fixtures/akseat.py.
"""

import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_gone_seats_cost_an_open_screen_little import GONE
from test_key_idle_screen_reads_only_what_changed import row

HOLD = 0.5        # seconds the seat's record says `working`: half of what lay between two looks
TRIES = 10
WORKING = {"wait": {"kind": "pr", "on": "https://github.com/acme/widgets/pull/7", "at": 0}}
SPENT = {"usage_wait": {"reason": "anthropic out of usage until 2026-10-21 09:00",
                        "until": time.time() + 3600, "since": 0, "continue": True}}
AFTER = ((SPENT, "out of usage"), ({}, "○ idle"))     # what a try leaves, by turns


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AWordHeldHalfASecond(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        Seat(self.home, "acme")
        for name in GONE:
            Seat(self.home, name, alive=False, planned=True)
        self.menu = Terminal(self.home, size=(100, 24))
        self.menu.wait(row("acme", "○ idle"), bound=120)

    def say(self, state):
        """The seat's record replaced by one holding `state`, as ak writes one."""
        record = self.home.path / ".agentkit/state/seat-acme.json"
        self.home.write(record.with_suffix(".tmp"), state).replace(record)

    def held(self, state, word):
        """Whether the screen drew `working`, written now and replaced HOLD later by `state`,
        which reads `word`."""
        drawn = []
        self.say(WORKING)
        threading.Timer(HOLD, self.say, [state]).start()
        self.menu.wait(lambda screen: drawn.append(row("acme", "● working")(screen))
                       or row("acme", word)(screen))
        return any(drawn)

    def test_the_word_is_drawn_more_often_than_not(self):
        drawn = sum(self.held(*AFTER[n % 2]) for n in range(TRIES))
        self.assertGreater(drawn, TRIES / 2, f"drawn {drawn} times of {TRIES}")


if __name__ == "__main__":
    unittest.main()
