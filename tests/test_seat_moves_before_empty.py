"""A seat with several subscriptions moves before its own runs low, between turns, typing nothing,
and input that comes in as it moves is never lost.

Its 5h window ran out mid-turn on one subscription while another had room: the turn was cut off,
and a line typed into the new one told it to go on.  test_seat_account's offline seat, with a 5h
window beside the week.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_seat_account as base
from agentkit import config, orch, usage, watch

NAME, CONVERSATION = base.NAME, base.CONVERSATION
HOUR = 3600


class MovesBeforeEmpty(unittest.TestCase):
    setUp, tick, type_into = base.SeatAccount.setUp, base.SeatAccount.tick, base.SeatAccount.type_into

    def tmux(self, *args, **kwargs):
        if args[0] == "respawn-pane":
            self.at_kill()
        return base.SeatAccount.tmux(self, *args, **kwargs)

    def at_kill(self):
        """What comes in between the launch's last look and the kill."""

    def meters(self, first, second, gone=2 * HOUR):
        """Each subscription's 5h window that used%, `gone` of it past, beside a quiet week."""
        def reading(used):
            meters = ({"name": "session", "used": used, "window_secs": usage.SESSION_SECS,
                       "resets_at": self.now + usage.SESSION_SECS - gone},
                      {"name": "weekly_all", "used": 30, "window_secs": 604800,
                       "resets_at": self.now + 3 * 86400})
            return {"provider": "anthropic", "resets": 0,
                    "meters": [usage._normalized(meter, self.now) for meter in meters]}
        accounts = {"default": reading(first), "second": reading(second)}
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "reset_checked_at": self.now, "providers": {
                "anthropic": {**accounts["default"], "accounts": accounts},
                "openai": {"resets": 0, "meters": []}}}))

    def account(self):
        return config.session_records()[NAME]["account"]

    def prompt(self, *_args):
        """A prompt from the owner's phone a moment later, as hooks/seat-state.sh writes it
        down: its fact, then its stamp."""
        self.now += 1
        config.record_hook_fact(NAME, {"session": NAME, "event": "UserPromptSubmit",
                                       "at": self.now, "kind": "", "text": ""})
        config.stop_path(NAME).write_text(json.dumps({"session": NAME, "turn": self.now}))

    def moving(self, before=lambda: None, after=lambda: None):
        """A tick that moves the seat, with what comes in as the harness is about to be
        replaced, after every slow step but the respawn's own, and once the new one is up."""
        start = orch._start_harness

        def starting(*args, **kwargs):
            before()
            start(*args, **kwargs)
            after()
        with patch.object(orch, "_start_harness", side_effect=starting):
            self.tick()

    def test_a_seat_between_turns_moves_before_its_window_runs_low_and_types_nothing(self):
        # 90% of the window in two hours: the quarter hour until the next reading eats the rest
        self.meters(90, 10)
        self.tick()
        self.assertEqual(self.account(), "second")
        self.assertIn(CONVERSATION, self.commands[0])
        self.tick()
        self.assertEqual((len(self.commands), self.typed), (1, []))
        self.assertIsNone(watch.seat_read(NAME).get("midturn"))

    def test_room_its_drain_does_not_eat_or_every_subscription_low_keeps_it_where_it_is(self):
        self.meters(90, 10, gone=4.5 * HOUR)
        self.tick()
        self.meters(97, 96)
        self.tick()
        self.assertEqual((self.account(), self.commands, self.typed), ("default", [], []))

    def test_a_turn_the_owners_text_or_a_pane_unread_before_the_kill_keep_it(self):
        self.meters(97, 10)
        draft = (base.REPO / "tests/fixtures/claude-draft-pane.txt").read_text()
        for came_in in (lambda: setattr(self, "pane", draft), self.prompt,
                        lambda: setattr(self, "pane", "")):
            self.pane = "❯"
            self.moving(before=came_in)
            self.assertEqual((self.account(), self.commands), ("default", []))
            self.assertIn("kept", self.logs[-1])

    def test_a_pane_unread_while_its_new_login_is_proven_keeps_it(self):
        self.meters(97, 10)

        def login(*_a, **_kw):
            self.pane = ""
            return True, "fake seat login"
        self.auth.side_effect = login
        self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))

    def test_a_prompt_past_the_last_look_goes_on_in_the_new_harness(self):
        self.meters(97, 10)
        self.at_kill = self.prompt
        self.tick()
        self.assertEqual((self.account(), len(self.commands)), ("second", 1))
        self.assertEqual(watch.seat_read(NAME)["midturn"]["line"], watch.MIDTURN_LINE)

    def test_a_prompt_the_new_harness_takes_is_no_turn_cut_off(self):
        self.meters(97, 10)
        self.moving(after=self.prompt)
        watch.continue_turns(self.cfg, self.logs.append)
        self.assertEqual((self.account(), len(self.commands)), ("second", 1))
        self.assertEqual((watch.seat_read(NAME).get("midturn"), self.typed), (None, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
