"""A tmux that never answers ends ak's call to it as a refusal, so the tick that asked goes on.

Offline: a fake tmux first on PATH that sleeps far past the ceiling, and a ceiling shortened for
the test.  No real tmux, server or seat.
"""

import os
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import orch

HUNG = "#!/bin/sh\nexec sleep 5\n"   # exec: the timeout's kill reaches the sleeper itself


class TmuxCallEnds(Sandbox):
    def setUp(self):
        super().setUp()
        folder = self.root / "hung-bin"
        folder.mkdir()
        (folder / "tmux").write_text(HUNG)
        (folder / "tmux").chmod(0o755)
        self.stack.enter_context(patch.dict(
            os.environ, {"PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"}))
        self.stack.enter_context(patch.object(orch, "TMUX_CEILING", 0.5, create=True))

    def test_a_call_without_a_timeout_ends_as_a_refusal(self):
        rc, out = orch.tmux_out("list-sessions", "-F", "#{session_name}")
        self.assertEqual(rc, 124)
        self.assertEqual(out, "tmux did not answer list-sessions within 0.5 s")

    def test_a_callers_own_timeout_ends_the_same_way(self):
        rc, out = orch.tmux_out("send-keys", "-t", "%1", "-l", "the owner's words", timeout=0.2)
        self.assertEqual(rc, 124)
        self.assertNotIn("owner's words", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
