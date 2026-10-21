"""A seat's stop holds its `closing` lock while it goes (orch.stop_lock), and while it does no
other stop of the seat starts and nothing opens it, whatever screen or command offered it: the
stop (`orch.cmd_stop`) and the opening (`orch.resume`, `orch.attach`) each look at the lock
themselves.

`x`'s stop runs in a process of its own, handed the lock its menu took (orch.STOPPING), and goes
on under it.  Offline: a temporary HOME, no tmux; the lock is held here, in this process, as a
second open of the file is its own holder.
"""

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
        said, past = [], {"name": "fix-api", "closed": 1, "resumable": True}
        with patch.object(menu, "pause", said.append), patch.object(orch, "launch") as launch, \
                patch.object(orch, "maintenance"), patch.object(orch, "find", return_value=None):
            for seat in (past, {"name": "fix-api"}):     # the past screen's, the main screen's
                menu.open_session(self.cfg, seat, False)
            with self.assertRaisesRegex(config.Error, "fix-api is still stopping"):
                orch.main(["fix-api"])                   # `ak orch fix-api`
            self.lock.close()
            config.rename_session("fix-api", "new-api")  # a screen read before the rename
            renamed = orch.stop_lock("new-api")
            self.addCleanup(renamed.close)
            menu.open_session(self.cfg, past, False)
            self.assertEqual((said, launch.called),
                             (["fix-api is still stopping"] * 2 + ["new-api is still stopping"],
                              False))
            renamed.close()
            with patch.object(orch, "attach"):
                menu.open_session(self.cfg, past, False)
        launch.assert_called_once()

if __name__ == "__main__":
    unittest.main()
