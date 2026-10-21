"""A seat with several subscriptions moves before its own runs low, between turns, typing nothing.

Its 5h window ran out mid-turn on one subscription while another had room: the turn was cut
off, its subagents and workflows with it, and a line typed into the new one told it to go on.
The owner's choice of 21 Oct 2026: it moves between turns instead, its pane taking no keys from
ak's last look until the new harness runs, and a prompt from the phone in that instant may be
lost.  test_seat_account's offline seat, with a 5h window beside the week.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_seat_account as base
from agentkit import config, orch, usage, watch

NAME, CONVERSATION = base.NAME, base.CONVERSATION
HOUR = 3600
DRAFT = (base.REPO / "tests/fixtures/claude-draft-pane.txt").read_text()


class MovesBeforeEmpty(unittest.TestCase):
    tick, type_into = base.SeatAccount.tick, base.SeatAccount.type_into

    def setUp(self):
        base.SeatAccount.setUp(self)
        self.calls, self.at_look, self.keys_off = [], lambda: None, False

    def tmux(self, *args, **kwargs):
        """The seat's server, which takes a command list whole: what the owner does as ak
        freezes the pane comes in with it."""
        self.calls.append(args)
        command = []
        for word in (*args, ";"):
            if word != ";":
                command.append(word)
                continue
            if command[:2] in (["select-pane", "-d"], ["select-pane", "-e"]):
                self.keys_off = command[1] == "-d"
                if self.keys_off:
                    self.at_look()
            command = []
        return base.SeatAccount.tmux(self, *args, **kwargs)

    def meters(self, first, second, gone=2 * HOUR):
        """Each subscription's 5h window that used%, `gone` of it past, beside a quiet week."""
        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [usage._normalized(meter, self.now)
                    for meter in ({"name": "session", "used": used, "window_secs": usage.SESSION_SECS,
                                   "resets_at": self.now + usage.SESSION_SECS - gone},
                                  {"name": "weekly_all", "used": 30, "window_secs": 604800,
                                   "resets_at": self.now + 3 * 86400})]}
        first, second = reading(first), reading(second)
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "reset_checked_at": self.now, "providers": {
                "anthropic": {**first, "accounts": {"default": first, "second": second}},
                "openai": {"resets": 0, "meters": []}}}))

    def account(self):
        return config.session_records()[NAME]["account"]

    def test_a_seat_between_turns_moves_before_its_window_runs_low_and_types_nothing(self):
        # 90% of the window in two hours: the quarter hour until the next reading eats the rest
        self.meters(90, 10)
        self.tick()
        self.assertEqual(self.account(), "second")
        self.assertIn(CONVERSATION, self.commands[0])
        freeze = next(n for n, args in enumerate(self.calls) if args[:2] == ("select-pane", "-d"))
        respawn = next(n for n, args in enumerate(self.calls) if args[0] == "respawn-pane")
        self.assertLess(freeze, respawn)
        self.assertEqual(self.calls[freeze][-2:], ("-C", f"select-pane -e -t ={NAME}:"))
        self.assertFalse(self.keys_off)             # the new harness takes keys at once
        self.tick()
        self.assertEqual((self.typed, len(self.commands)), ([], 1))
        self.assertIsNone(watch.seat_read(NAME).get("midturn"))

    def test_room_its_drain_does_not_eat_or_every_subscription_low_keeps_it(self):
        for first, second, gone in ((90, 10, 4.5 * HOUR), (97, 96, 2 * HOUR)):
            self.meters(first, second, gone)
            self.tick()
            self.assertEqual((self.account(), self.commands, self.typed), ("default", [], []))

    def test_keys_or_a_turn_keep_it_where_it_is(self):
        self.meters(97, 10)
        os.utime(self.tty, (self.now - 60, self.now - 60))     # typed into a minute ago
        self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))
        self.pane = (base.REPO / "tests/fixtures/claude-working-pane.txt").read_text()
        os.utime(self.tty, (self.now - watch.DRAFT_STILL, self.now - watch.DRAFT_STILL))
        self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))

    def test_input_or_a_close_at_the_last_look_keeps_it_and_its_keys(self):
        def draft():
            self.pane = DRAFT

        def typed():
            os.utime(self.tty, (self.now, self.now))

        def closed():
            self.seat["exited"] = True
            orch.mark_owner_closed(NAME)

        def unread():
            self.unread = True

        def unreadable():
            self.pane = ""
        self.unread = False
        with patch.object(watch, "pane_unread", side_effect=lambda _seat: self.unread):
            for change in (draft, typed, closed, unread, unreadable):
                with self.subTest(change.__name__):
                    base.SeatAccount.setUp(self)
                    self.calls, self.at_look, self.keys_off, self.unread = [], change, False, False
                    self.meters(97, 10)
                    self.tick()
                    self.assertEqual((self.account(), self.commands), ("default", []))
                    self.assertFalse(self.keys_off)
                    self.assertTrue(any("kept" in line for line in self.logs))
                    self.assertEqual(watch.seat_closed_by_owner(NAME), change is closed)

    def test_a_respawn_tmux_refuses_gives_the_pane_its_keys_back(self):
        self.meters(97, 10)
        refuse = self.tmux

        def refused(*args, **kwargs):
            return (1, "no server") if args[0] == "respawn-pane" else refuse(*args, **kwargs)
        with patch.object(orch, "tmux_out", side_effect=refused):
            self.tick()
        self.assertEqual((self.account(), self.commands), ("default", []))
        self.assertFalse(self.keys_off)


if __name__ == "__main__":
    unittest.main(verbosity=2)
