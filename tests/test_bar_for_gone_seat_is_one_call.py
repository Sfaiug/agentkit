"""Dressing the bar of a seat whose tmux session is gone costs one tmux call: the listing.

Every menu draw redresses each seat it shows, and a stopped seat's options were told in one
call, then again one by one, each failing: about twenty calls per such seat per draw.  Text
tmux refuses for its length is still told in pieces.  Offline with a fake tmux that answers
as tmux 3.5a does: it fills in the fields a listing asks for, shows a client outside a UTF-8
locale each tab as `_`, stops a call at the command that fails, and refuses one past 16 KiB.
"""

import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar
from agentkit.guard import commands


class GoneSeat(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls, self.options = [], {}
        self.up, self.utf8, self.sessions = True, True, {"acme": ("$0", "1")}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "processes", return_value={}))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        if not self.up:
            return 1, "no server running on /tmp/tmux-1000/agentkit-test"
        if args[:2] == ("list-sessions", "-F"):
            out = "\n".join(re.sub(r"#\{[^}]*\}", lambda field: {
                "#{session_id}": sid, "#{session_name}": name, f"#{{{orch.MARK}}}": mark}[field[0]],
                args[2]) for name, (sid, mark) in self.sessions.items())
            return 0, out if self.utf8 else re.sub(r"[\x00-\x1f]", "_", out)
        if args[0] == "list-panes":
            return 0, ""
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
        for case, up, utf8 in (("beside a seat and somebody's session", True, True),
                               ("for a client outside a UTF-8 locale", True, False),
                               ("with no server up", False, True)):
            with self.subTest(case):
                self.calls.clear()
                self.up, self.utf8 = up, utf8
                self.sessions["acme-watch"] = ("$1", "")   # no mark: what it is takes asking
                statusbar.redress({"name": "gone"}, {"word": "idle", "reason": ""}, self.cfg)
                self.assertEqual([args[0] for args in self.calls], ["list-sessions"])

    def test_a_live_seats_text_longer_than_a_message_is_told_in_pieces(self):
        for utf8 in (True, False):
            with self.subTest(utf8=utf8):
                self.calls.clear()
                self.utf8, self.options = utf8, {}
                question = "May I merge acme's fix? " + "The context of the question. " * 700
                statusbar._write("acme", "opus", word="needs you",
                                 versions=[question] * len(statusbar.WHYS))
                self.assertTrue(any(args[:2] == ("set-option", "-a") for args in self.calls))
                for version in statusbar.WHYS:
                    self.assertEqual(self.options[version], "  " + question, version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
