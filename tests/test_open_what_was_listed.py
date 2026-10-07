"""Opening a seat asks tmux nothing its caller has already listed.

Offline: a fake tmux that records each call, and a seat listing that counts its asks.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch


class OpenWhatWasListed(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.listed = self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        return 0, ""

    def test_a_seat_named_from_the_listed_names_lists_no_seat_again(self):
        # the name question listed the seats; tmux is still asked whether it holds the name
        with patch.object(orch, "fresh_command", return_value=(["claude"], None)), \
                patch.object(orch, "user_manager", return_value=False):
            orch.create(self.cfg, "acme", self.root, taken={"other"},
                        selection=({}, ("opus", "chosen", ["opus"])))
        self.listed.assert_not_called()
        self.assertEqual(self.calls[0], ("list-sessions", "-F", "#{session_name}"))
        self.assertIn("new-session", self.calls[2])

    def test_opening_a_listed_seat_asks_tmux_only_to_switch_to_it(self):
        listed = {"name": "acme", "path": str(self.root), "created": 1, "attached": False,
                  "exited": False, "legacy": False}
        with patch.dict(os.environ, {"TMUX": f"/tmp/tmux-1/{orch.socket_name()},1,0"}), \
                patch.object(orch.sys.stdin, "isatty", return_value=True), \
                patch.object(orch.sys.stdout, "isatty", return_value=True):
            self.assertEqual(orch.attach("acme", wait=True, session=listed), 0)
        # the switch, then only that seat's own screen, read for the opening's baseline
        self.listed.assert_not_called()
        self.assertEqual(self.calls[0], ("switch-client", "-t", "=acme"))
        self.assertEqual({args[0] for args in self.calls[1:]} - {"capture-pane"}, set())

    def test_an_unnamed_seat_is_named_from_what_tmux_holds_once_the_question_is_answered(self):
        # a seat called `new` opens while the name question waits
        held = iter(({"other"}, {"other", "new"}))
        with patch.object(orch, "taken_names", side_effect=lambda: next(held)), \
                patch.object(orch, "ask_name", return_value=None), \
                patch.object(orch, "typed_here", return_value=True), \
                patch.object(orch, "maintenance"), \
                patch.object(orch, "create", return_value=None) as create:
            self.assertEqual(orch.main([]), 0)
        self.assertEqual(create.call_args.args[1], "new-2")
        self.assertIn("new", create.call_args.kwargs["taken"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
