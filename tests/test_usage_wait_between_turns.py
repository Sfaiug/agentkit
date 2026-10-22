"""A turn the owner began while the seat waited for usage is never reopened under or typed into.

Such a turn ran on an account that answered it, so no limit cut it: where that account has
room again the wait just ends; a move to another account waits for the turn's end.  A turn
that was running when the wait began is the one the limit cut, and goes on as before.

The fixture is `test_seat_account`'s: temporary HOME, fake tmux and meters, offline.
"""

import sys
import unittest
from unittest.mock import patch

import test_seat_account as seats
from agentkit import watch

NAME = seats.NAME


class UsageWaitBetweenTurns(unittest.TestCase):
    setUp, meters, tmux, type_into, tick = (
        seats.SeatAccount.setUp, seats.SeatAccount.meters, seats.SeatAccount.tmux,
        seats.SeatAccount.type_into, seats.SeatAccount.tick)

    def waiting(self, began):
        """Waiting for usage since ten minutes ago, with a turn running since `began` ago."""
        since = self.now - 600
        watch.seat_write(NAME, usage_wait={"reason": "anthropic out of usage", "since": since,
                                          "until": self.now + 3600, "continue": False})
        flight = patch.object(watch, "_turn_in_flight", return_value=(True, self.now - began))
        self.addCleanup(flight.stop)
        return flight.start()

    def test_the_owner_s_turn_on_a_refilled_account_just_ends_the_wait(self):
        self.meters(100, 100)
        self.waiting(began=60)
        self.tick()
        self.assertFalse(watch.seat_read(NAME)["usage_wait"]["continue"])
        self.meters(20, 20)
        self.tick()
        self.assertEqual((self.commands, self.typed), ([], []))
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])
        self.assertFalse(watch.seat_read(NAME).get("midturn"))

    def test_a_move_to_another_account_waits_for_the_owner_s_turn_to_end(self):
        self.meters(100, 20)
        flight = self.waiting(began=60)
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertTrue(watch.seat_read(NAME)["usage_wait"])
        flight.return_value = (False, None)
        self.tick()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.typed, [])

    def test_a_turn_running_when_the_wait_began_goes_on_when_usage_returns(self):
        self.meters(20, 20)
        self.waiting(began=3600)
        self.tick()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(watch.seat_read(NAME)["midturn"]["line"], watch.ACCOUNT_LINE)


if __name__ == "__main__":
    unittest.main()
