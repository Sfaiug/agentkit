"""Dressing the bar of a seat whose tmux session is gone costs one tmux call: the listing.

Every menu draw redresses each seat it shows, and a stopped seat's options were told in one
call, then again one by one, each failing: about twenty calls per such seat per draw.  Text
tmux refuses for its length is still told in pieces.  Offline with a fake tmux that answers
as tmux 3.5a does: it stops a call at the command that fails, and refuses one past 16 KiB.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar
from agentkit.guard import commands


class GoneSeat(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls, self.options, self.up = [], {}, True
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        if not self.up:
            return 1, "no server running on /tmp/tmux-1000/agentkit-test"
        if args[0] == "list-sessions":
            return 0, "$0\tacme\t1"
        if sum(len(word.encode()) + 1 for word in args) + 16 > 16 * 1024:
            return 1, "command too long"
        for command in commands(args):
            if command[0] == "set-option":
                more = command[1] == "-a"
                target, option, text = command[3 if more else 2:][:3]
                if target != "=acme:":
                    return 1, f"no such session: {target}"
                self.options[option] = self.options.get(option, "") * more + text
        return 0, ""

    def test_redressing_a_gone_seat_is_one_call(self):
        for up in (True, False):   # beside another seat's session, or with no server up at all
            with self.subTest(up=up):
                self.calls.clear()
                self.up = up
                statusbar.redress({"name": "gone"}, {"word": "idle", "reason": ""}, self.cfg)
                self.assertEqual([args[0] for args in self.calls], ["list-sessions"])

    def test_a_live_seats_text_longer_than_a_message_is_told_in_pieces(self):
        question = "May I merge acme's fix? " + "The context of the question. " * 700
        statusbar._write("acme", "opus", word="needs you",
                         versions=[question] * len(statusbar.WHYS))
        self.assertTrue(any(args[:2] == ("set-option", "-a") for args in self.calls))
        for version in statusbar.WHYS:
            self.assertEqual(self.options[version], "  " + question, version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
