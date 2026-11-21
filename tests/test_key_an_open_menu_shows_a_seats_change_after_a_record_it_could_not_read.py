"""An open menu shows a seat's change after a record it could not read.

Every open screen's rows come from one thread, and a round of it that raised anything but the few
kinds its read was caught for ended it: that screen showed its last good read until it was
closed.  A seat's record whose `usage_wait` is no dict -- a hand edit, a torn disk, a later
format -- raised on every read.  The seat's record is written so, the screen given more than the
longest it goes between looks at its records to meet it, then written whole, and the seat's row
then shows its new word.  Black-box: the program `AK_BIN` names runs in a person's terminal
(tests/fixtures/akterm.py) beside a seat of tests/fixtures/akseat.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_an_open_menu_draws_a_word_a_seat_held_half_a_second import SPENT
from test_key_idle_screen_reads_only_what_changed import row

STIR = 1.0        # seconds: the longest an open screen goes between looks at its seats' records
OUT = {**SPENT, "word": "out of usage"}     # as ak records it: the word beside the wait it is from


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnOpenMenuShowsASeatsChangeAfterARecordItCouldNotRead(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        Seat(self.home, "acme")
        self.menu = Terminal(self.home, size=(100, 24))
        self.menu.wait(row("acme", "○ idle"), bound=120)
        self.record = self.home.path / ".agentkit/state/seat-acme.json"
        deadline = time.monotonic() + 120
        # The first look's word, which would land over ours: the look writes what it read first,
        # then its word, each through the `.tmp` ours goes through.
        while not self.record.exists() or "word" not in json.loads(self.record.read_text()):
            self.assertLess(time.monotonic(), deadline, "the screen never looked at acme")
            time.sleep(0.05)

    def say(self, state):
        """The seat's record replaced by one holding `state`, as ak writes one."""
        self.home.write(self.record.with_suffix(".tmp"), state).replace(self.record)

    def test_the_row_shows_the_record_once_it_is_whole_again(self):
        self.say({**OUT, "usage_wait": "x"})
        time.sleep(3 * STIR)                # met, which draws nothing
        self.say(OUT)
        self.menu.wait(row("acme", "out of usage"))


if __name__ == "__main__":
    unittest.main()
