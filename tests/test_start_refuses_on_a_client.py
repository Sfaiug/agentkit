"""`orch.start` itself refuses on a client: a caller that comes to it without asking, as one added
later would, starts nothing, and tmux is asked nothing.

Each way to a start there is asks before it writes (tests/test_key_a_client_opens_no_session.py),
so only a caller that does not ask reaches this refusal: here, the test.
Offline: fixtures.sandbox's HOME, and a tmux that fails the test when asked.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch


class Start(Sandbox):
    def test_it_refuses_naming_the_home_before_it_asks_tmux_for_anything(self):
        (config.STATE / "server").write_text("acme-box\n")
        with patch.object(orch, "tmux_out", side_effect=AssertionError("tmux was asked")), \
                self.assertRaisesRegex(config.Error, "acme-box"):
            orch.start("acme", self.root, ["true"], "opus")


if __name__ == "__main__":
    unittest.main()
