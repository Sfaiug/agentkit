"""A seat's bar is written in one tmux command list, so a start or a redraw waits on one call.

Offline: a fake tmux that records each call it is asked.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar
from agentkit.guard import commands


class BarInOneCall(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        return 0, ""

    def test_a_seats_bar_is_one_call_with_its_title_last(self):
        statusbar.dress("acme", "opus")
        bar = [args for args in self.calls if "status-format[0]" in args]
        self.assertEqual(len(bar), 1)
        commands = " ".join(bar[0]).split(" ; ")
        self.assertTrue(all(command.startswith("set-option -t =acme: ") for command in commands))
        options = [command.split(" ")[3] for command in commands]
        self.assertEqual(options[-1], "set-titles-string")
        for option in (*(option for option, _ in statusbar.LAYOUT), *statusbar.TOPS,
                       *statusbar.WHYS, statusbar.KEY):
            self.assertIn(option, options)


class LongQuestion(Sandbox):
    """tmux 3.5a refuses a call past its 16 KiB message, header included, and sets nothing."""

    def setUp(self):
        super().setUp()
        self.options = {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        if sum(len(word.encode()) + 1 for word in args) + 16 > 16 * 1024:
            return 1, "command too long"
        for command in commands(args):
            if command[0] == "set-option":
                self.options[command[3]] = command[4]
        return 0, ""

    def test_a_seat_asking_a_long_question_still_says_so_on_its_bar(self):
        question = "May I merge acme? " + "The context of the question. " * 100
        statusbar._write("acme", "opus", word="needs you", lasts=[question] * len(statusbar.BARS))
        self.assertIn("needs you", self.options["set-titles-string"])
        self.assertIn("The context of the question.", self.options[statusbar.WHY])


if __name__ == "__main__":
    unittest.main(verbosity=2)
