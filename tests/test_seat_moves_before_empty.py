"""A seat with several subscriptions moves before its own runs low, between turns, typing nothing.

Its 5h window ran out mid-turn on one subscription while another had room: the turn was cut
off, and a line typed into the new one told it to go on.  test_seat_account's offline seat,
with a 5h window beside the week.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_seat_account as base
from agentkit import config, usage, watch

NAME, CONVERSATION = base.NAME, base.CONVERSATION
HOUR = 3600


class MovesBeforeEmpty(unittest.TestCase):
    setUp, tick, tmux, type_into = (base.SeatAccount.setUp, base.SeatAccount.tick,
                                    base.SeatAccount.tmux, base.SeatAccount.type_into)

    def meters(self, first, second, single=False, gone=2 * HOUR, scoped=0):
        """Each subscription's 5h window that used%, `gone` of it past, beside a quiet week;
        the second's Fable week `scoped`% used."""
        def reading(used, scoped=0):
            return {"provider": "anthropic", "resets": 0, "meters": [usage._normalized(meter, self.now)
                    for meter in ({"name": "session", "used": used, "window_secs": usage.SESSION_SECS,
                                   "resets_at": self.now + usage.SESSION_SECS - gone},
                                  {"name": "weekly_all", "used": 30, "window_secs": 604800,
                                   "resets_at": self.now + 3 * 86400},
                                  {"name": "weekly_scoped", "used": scoped, "window_secs": 604800,
                                   "resets_at": self.now + 3 * 86400})]}
        first, second = reading(first), reading(second, scoped)
        anthropic = first if single else {**first, "accounts": {"default": first, "second": second}}
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "reset_checked_at": self.now,
            "providers": {"anthropic": anthropic, "openai": {"resets": 0, "meters": []}}}))

    def account(self):
        return config.session_records()[NAME]["account"]

    def test_a_seat_between_turns_moves_before_its_window_runs_low_and_types_nothing(self):
        # 90% of the window in two hours: the quarter hour until the next reading eats the rest
        self.meters(90, 10)
        self.tick()
        self.assertEqual(self.account(), "second")
        self.assertIn(CONVERSATION, self.commands[0])
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertIsNone(watch.seat_read(NAME).get("midturn"))
        self.assertEqual(len(self.commands), 1)

    def test_room_its_drain_does_not_eat_keeps_the_seat_where_it_is(self):
        self.meters(90, 10, gone=4.5 * HOUR)
        self.tick()
        self.assertEqual((self.account(), self.commands, self.typed), ("default", [], []))

    def test_a_turn_in_flight_or_every_subscription_low_keeps_the_seat_spending_its_own(self):
        self.meters(97, 96)
        self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))
        self.meters(97, 10)
        self.pane = (base.REPO / "tests/fixtures/claude-working-pane.txt").read_text()
        self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))

    def test_a_worker_turn_starts_on_the_subscription_that_is_not_running_low(self):
        # the usual login is a worker's last pick only while the others have as much room
        self.meters(10, 97)
        self.assertEqual(usage.account(self.cfg, "anthropic", model="opus"), ("default", True))
        self.meters(97, 10)
        self.assertEqual(usage.account(self.cfg, "anthropic", model="opus"), ("second", True))
        # Fable's own week running low on the spare leaves an Opus turn there
        self.meters(10, 10, scoped=97)
        self.assertEqual(usage.account(self.cfg, "anthropic", model="opus"), ("second", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
