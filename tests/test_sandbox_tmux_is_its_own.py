"""A Sandbox test asks a tmux server of its own, never the one every test on the machine shares,
and so does a thread its cleanup still waits for: a `fix-api` session another test held there
once refused that name to `ak orch new` in tests/test_plan_lines.py.

Real tmux: the shared server is one in the machine's socket directory, where tmux falls back
once a TMUX_TMPDIR is gone, under a name of this process's own.
"""

import os
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch

TMUX = shutil.which("tmux")


@unittest.skipUnless(TMUX, "no tmux installed")
class OwnServer(unittest.TestCase):
    def test_a_session_on_the_shared_server_is_no_name_a_sandbox_holds(self):
        shared, env = f"akt-shared-{os.getpid()}", {**os.environ, "TMUX_TMPDIR": "/tmp"}
        env.pop("TMUX", None)
        server = [TMUX, "-L", shared]
        # a server's socket stays once it is killed
        self.addCleanup(Path(f"/tmp/tmux-{os.getuid()}", shared).unlink, missing_ok=True)
        subprocess.run([*server, "-f", "/dev/null", "new-session", "-d", "-s", "fix-api",
                        "sleep 600"], env=env, check=True, timeout=10)
        self.addCleanup(subprocess.run, [*server, "kill-server"], env=env, capture_output=True,
                        timeout=10)
        held = []

        class Late(threading.Thread):
            """A menu's read still going when its test ends, until the cleanup joins it."""
            def __init__(self):
                super().__init__(target=lambda: self.joined.wait(15)
                                 and held.append(orch.held_names()))
                self.joined = threading.Event()

            def join(self, timeout=None):
                self.joined.set()
                super().join(timeout)

        class Inside(Sandbox):
            def runTest(self):
                held.append(orch.held_names())
                Late().start()

        result = unittest.TestResult()
        with patch.dict(os.environ, {"TMUX_TMPDIR": "/tmp"}), \
                patch.object(orch, "socket_name", return_value=shared):
            Inside().run(result)
        self.assertEqual(result.errors + result.failures, [])
        self.assertEqual(held, [set(), set()])


if __name__ == "__main__":
    unittest.main()
