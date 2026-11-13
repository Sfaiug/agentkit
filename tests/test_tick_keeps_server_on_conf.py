"""A tmux server that is already up takes ak's current conf from the tick, `terminal-features`
aside, which adds to itself each time it is loaded.

A server started on an older `Ctrl-b m` (one from a tmux before FLOATS, whose popup is handed no
client name) has the current one after the tick's repair, `orch.set_hook_options`, with no seat
opened; and repairs run over and over leave its `terminal-features` as the conf first set it.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS.parent), str(TESTS)]
from fixtures.akbin import REAL_TMUX, Home
from agentkit import config, orch, terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AServerOnAnOlderConf(unittest.TestCase):
    def test_the_tick_gives_it_the_current_menu_key_and_adds_no_terminal_features(self):
        home = self.enterContext(Home(tmux_log=False))
        self.enterContext(patch.dict(os.environ, home.env, clear=True))
        self.enterContext(patch.object(config, "HOME", home.path / ".agentkit"))
        self.enterContext(patch.object(config, "STATE", home.path / ".agentkit/state"))
        with patch.object(orch, "tmux_version", return_value=(3, 2)):
            conf = orch.tmux_conf()
        started = home.tmux("-f", str(conf), "new-session", "-d", "-s", "acme", "sleep 120")
        self.assertEqual(started.code, 0, started.err)
        self.assertNotIn(terminal.FEATURES_ENV, home.tmux("list-keys", "-T", "prefix", "m").out)
        features = home.tmux("show-options", "-s", "terminal-features").out
        with patch.object(orch, "tmux_version", return_value=orch.FLOATS):
            for _ in range(3):
                orch.set_hook_options()
        self.assertIn(terminal.FEATURES_ENV, home.tmux("list-keys", "-T", "prefix", "m").out)
        self.assertEqual(home.tmux("show-options", "-s", "terminal-features").out, features)


if __name__ == "__main__":
    unittest.main()
