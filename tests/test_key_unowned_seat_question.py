"""A seat with no blocking Stop whose conversation ak cannot name reads `needs you` at its question.

Where the harness cannot say which conversation is the seat's (an Antigravity seat on a host
whose open files cannot be read, a seat opened before its harness said), nothing can prove its
closing message held the question: the stop that shows it reads `needs you` and nothing is
typed, as before ak read the conversation, rather than `working` with a reminder every stop.
Black-box: `AK_BIN` through tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py
whose hooks fire as their harness fires them.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable
from test_key_question_delivery_after_stop import QUESTION, Seats


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class UnownedSeatQuestion(Seats, unittest.TestCase):
    owned = False

    def test_its_question_reads_needs_you_with_nothing_typed(self):
        for talk in self.talks.values():
            talk.model(QUESTION)
        self.stop(QUESTION)
        self.reads("needs you", 0)
        self.assertEqual(self.home.tick().code, 0)
        self.reads("needs you", 0)


if __name__ == "__main__":
    unittest.main()
