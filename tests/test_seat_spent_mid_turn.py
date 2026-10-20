"""A seat caught empty mid-turn moves at once and goes on, and never reads idle.

Claude Code's `You've hit your session limit` sat on the seat's screen for three minutes before
ak believed it, reading idle meanwhile; a turn Claude Code wrapped up for the limit moved only
once the meters, read every quarter hour, said 100%; and the owner's unsent text under either
kept the seat where it was for good.  A spent window is now acted on when first seen, a wrap-up
note is one, and the text goes on with the seat.  `test_spent_seat_moves_past_question`'s stage.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from test_spent_seat_moves_past_question import REFUSED, SpentSeat  # noqa: E402
from test_seat_account import NAME  # noqa: E402
from agentkit import config, watch  # noqa: E402


class SpentMidTurn(SpentSeat):
    def account(self):
        return config.session_records()[NAME]["account"]

    def test_a_spent_window_on_the_screen_moves_the_seat_when_first_seen(self):
        self.meters(20, 20)       # only the refusal on its screen says the window is spent
        self.pane = REFUSED
        self.tick()
        self.assertEqual(self.account(), "second")
        self.assertEqual(self.went_on(), ([], watch.ACCOUNT_LINE))
        self.assertNotEqual(self.answer()["word"], "idle")

    def test_a_turn_wrapped_up_at_home_moves_though_the_meters_still_read_room(self):
        self.meters(20, 20)       # only the note in its transcript says the window is spent
        self.wrapped()
        self.tick()
        self.assertEqual(self.account(), "second")
        self.assertEqual(self.went_on(), ([], watch.ACCOUNT_LINE))

    def test_a_wrapped_up_turn_with_no_other_account_waits_and_goes_on_at_its_reset(self):
        self.cfg["providers"]["anthropic"].pop("accounts")
        self.meters(20, 0, single=True)
        self.wrapped()
        self.tick()
        answer = self.answer()
        self.assertNotEqual(answer["word"], "idle")
        self.assertTrue(answer["resumes_at"])
        self.assertEqual(self.commands, [])
        self.now = answer["resumes_at"] + 1
        self.meters(0, 0, single=True)
        self.tick()
        self.assertEqual(len(self.commands), 1)     # its conversation, resumed where it stopped
        self.assertEqual(self.went_on(), ([], watch.ACCOUNT_LINE))

    def test_the_owners_unsent_text_goes_on_with_the_seat(self):
        self.meters(20, 20)
        self.pane = REFUSED.replace("❯\u00a0\n", "❯\u00a0half a thought about the parser\n")
        self.assertIn("parser", self.pane)
        with patch.object(watch, "carry_draft") as carried:
            self.tick()
        self.assertEqual(watch.seat_read(NAME)["state"], "draft")
        carried.assert_called_once()
        self.assertEqual(self.account(), "second")
        self.assertEqual(len(self.commands), 1)

    def test_a_resumed_seat_is_never_told_its_subscription_ran_out(self):
        # the same account after its reset is no other subscription: the line says what is true
        self.assertNotIn("subscription", watch.ACCOUNT_LINE)
        self.assertIn("Continue that turn", watch.ACCOUNT_LINE)


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stage's run from their own files."""
    return unittest.TestSuite(SpentMidTurn(name) for name in loader.getTestCaseNames(SpentMidTurn)
                              if name in vars(SpentMidTurn))


if __name__ == "__main__":
    unittest.main()
