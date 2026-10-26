"""A seat with no blocking Stop whose conversation ak cannot name reads `needs you` at its question.

Nothing can prove such a seat's closing message held its question, so its stop rests there with
nothing typed, never `working` with a reminder every stop.  Black-box, as
tests/test_key_question_delivery_after_stop.py.
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
