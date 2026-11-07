"""A Sandbox test asks a tmux server of its own, never the one every test on the machine shares:
a `fix-api` session another test held there once refused that name to `ak orch new` in
tests/test_plan_lines.py (`tmux already holds a session named 'fix-api'`).

Real tmux: the machine's shared server is one on a socket directory of this test's own.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch

TMUX = shutil.which("tmux")


@unittest.skipUnless(TMUX, "no tmux installed")
class OwnServer(unittest.TestCase):
    def test_a_session_on_the_shared_test_server_is_no_name_a_sandbox_holds(self):
        shared = tempfile.mkdtemp(prefix="akt-", dir="/tmp")   # a socket path fits 104 bytes
        self.addCleanup(shutil.rmtree, shared, True)
        server, env = [TMUX, "-L", "agentkit-test"], {**os.environ, "TMUX_TMPDIR": shared}
        env.pop("TMUX", None)
        subprocess.run([*server, "-f", "/dev/null", "new-session", "-d", "-s", "fix-api",
                        "sleep 600"], env=env, check=True, timeout=10)
        self.addCleanup(subprocess.run, [*server, "kill-server"], env=env, capture_output=True,
                        timeout=10)
        held = []

        class Inside(Sandbox):
            def runTest(self):
                held.append(orch.held_names())

        result = unittest.TestResult()
        with patch.dict(os.environ, {"TMUX_TMPDIR": shared}):
            Inside().run(result)
        self.assertEqual(result.errors + result.failures, [])
        self.assertEqual(held, [set()])


if __name__ == "__main__":
    unittest.main()
