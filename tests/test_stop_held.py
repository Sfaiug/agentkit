"""A seat's stop holds its `closing` lock while it goes (orch.stop_lock), and while it does no
other stop of the seat starts and nothing opens it, whatever screen or command offered it: the
stop (`orch.cmd_stop`) and the opening (`orch.resume`, `orch.attach`) each look at the lock
themselves.

`x`'s stop runs in a process of its own, handed the lock its menu took (orch.STOPPING), and goes
on under it.  Offline: a temporary HOME, no tmux; the lock is held here, in this process, as a
second open of the file is its own holder.
"""

import fcntl
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, notify, orch, stop


class StopHeld(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": "/", "created": 1})
        self.stack.enter_context(patch.object(stop, "stop_owned_runs"))
        self.stack.enter_context(patch.object(notify, "forget_card"))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=False))
        os.environ.pop(orch.STOPPING, None)
        self.lock = orch.stop_lock("fix-api")
        self.addCleanup(self.lock.close)

    def test_a_second_stop_is_refused_while_the_first_goes(self):
        self.assertTrue(orch.stop_held("fix-api"))
        self.assertIsNone(orch.stop_lock("fix-api"))
        with self.assertRaisesRegex(config.Error, "fix-api is stopping already"):
            orch.cmd_stop(["fix-api"])
        self.assertIn("fix-api", config.session_records())     # nothing taken off the list
        self.lock.close()
        self.assertFalse(orch.stop_held("fix-api"))
        self.assertEqual(orch.cmd_stop(["fix-api"]), 0)        # its own lock, and given back
        self.assertFalse(orch.stop_held("fix-api"))

    def test_x_s_own_stop_goes_on_under_the_lock_its_menu_handed_it(self):
        with patch.dict(os.environ, {orch.STOPPING: "fix-api"}):
            self.assertEqual(orch.cmd_stop(["fix-api"]), 0)
        self.assertTrue(orch.stop_held("fix-api"))             # still the menu's, till it ends

    def test_nothing_opens_a_seat_whose_stop_goes(self):
        said, past, started, later = [], {"name": "fix-api", "closed": 1, "resumable": True}, [], []

        def start(*_a, **_kw):             # a stop beginning now would end what opens
            with config.seat_file("closing", "new-api").open("a") as stop:
                try:
                    fcntl.flock(stop, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    started.append("a stop could begin")
                except BlockingIOError:
                    started.append("no stop can begin")

        with patch.object(menu, "pause", said.append), patch.object(orch, "maintenance"), \
                patch.object(orch, "find", return_value=None), \
                patch.object(orch, "_start_harness", side_effect=start), \
                patch.object(orch, "attach"):
            menu.open_session(self.cfg, past, False)             # the past screen's
            with self.assertRaisesRegex(config.Error, "fix-api is still stopping"):
                orch.main(["fix-api"])                           # `ak orch fix-api`
            self.lock.close()
            config.rename_session("fix-api", "new-api")          # a screen read before the rename
            renamed = orch.stop_lock("new-api")
            menu.open_session(self.cfg, past, False)
            renamed.close()
            with patch.object(orch, "fresh_command", side_effect=lambda *_a, **_kw: (
                    later.append(orch.stop_lock("new-api")) or (["fake-harness"], None))):
                menu.open_session(self.cfg, past, False)         # a stop begun once it looked
            later.pop().close()
            menu.open_session(self.cfg, past, False)
        self.assertEqual(said, ["fix-api is still stopping"] + ["new-api is still stopping"] * 2)
        self.assertEqual(started, ["no stop can begin"])

    def test_the_main_screen_s_attach_neither(self):
        said, switched = [], []

        def switch(*_a, **_kw):            # a stop beginning now would end what it goes onto
            with config.seat_file("closing", "fix-api").open("a") as stop:
                try:
                    fcntl.flock(stop, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    switched.append("a stop could begin")
                except BlockingIOError:
                    switched.append("no stop can begin")
            return 0, ""

        with patch.object(menu, "pause", said.append), \
                patch.object(orch, "inside", return_value=True), \
                patch.object(orch.sys.stdin, "isatty", return_value=True), \
                patch.object(orch.sys.stdout, "isatty", return_value=True), \
                patch.object(orch, "tmux_out", side_effect=switch), \
                patch.object(orch, "seen_by_user"):
            menu.open_session(self.cfg, {"name": "fix-api"}, False)
            self.lock.close()
            menu.open_session(self.cfg, {"name": "fix-api"}, False)
        self.assertEqual((said, switched), (["fix-api is still stopping"], ["no stop can begin"]))

if __name__ == "__main__":
    unittest.main()
