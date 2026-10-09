"""A seat's open `ak notify needs` question holds up only its own decision.

The seat works on what does not wait on the answer, so run hand-backs and the line that ends
its `ak wait` still reach it, and the question stays open until the owner's own prompt answers
it; a recovery nudge waits for that answer.  The fixture is fixtures.seats: a temporary HOME, a
fake tmux and pane.
"""

import unittest

from fixtures.seats import LINE, SEAT, Seats
from agentkit import notify, watch

QUESTION = "Which schema should acme use?"
HANDBACK = "run 20260101-0900-acme-parser finished PASS merged. Decide the next step."


class QuestionHoldsOnlyItself(Seats):
    def setUp(self):
        super().setUp()
        notify.record(SEAT, "needs", QUESTION)

    def asked(self):
        return (notify.last(SEAT) or {}).get("text")

    def test_a_run_hand_back_reaches_a_seat_whose_question_is_open(self):
        self.assertTrue(watch.type_at_prompt(self.seat, HANDBACK, lambda _: None, cfg=self.cfg))
        self.assertEqual(self.typed, [HANDBACK])
        self.assertEqual(self.asked(), QUESTION)

    def test_the_end_of_its_wait_reaches_it_too(self):
        self.wait_line()
        self.tick()
        self.assertEqual(self.typed, [LINE])
        self.assertTrue(self.told())
        self.assertEqual(self.asked(), QUESTION)

    def test_a_recovery_nudge_still_waits_for_the_answer(self):
        self.assertFalse(watch.type_into(self.seat, "continue", lambda _: None))
        self.assertEqual(self.typed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
