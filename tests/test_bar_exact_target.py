"""A seat's bar is written to that seat alone, never to another whose name it begins.

tmux reads a plain session name as the start of any session's, so a write for a gone `new-1`
would land on `new-10`.  Runs tmux itself, on a server of its own for this test.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import orch, statusbar


class ExactTarget(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        # a short directory of its own: a socket path has a length limit
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "exact"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(subprocess.run, ["tmux", "-L", "exact", "kill-server"],
                        env={**os.environ, "TMUX_TMPDIR": sockets}, capture_output=True)

    def start(self, name):
        rc, out = orch.tmux_out("new-session", "-d", "-s", name, "sleep 600")
        self.assertEqual(rc, 0, out)

    def top(self, name):
        rc, out = orch.tmux_out("show-options", "-qv", "-t", f"={name}:", statusbar.TOP)
        self.assertEqual(rc, 0, out)
        return out

    def test_a_gone_seats_bar_never_lands_on_a_seat_its_name_begins(self):
        self.start("new-10")
        statusbar.dress("new-1", "fable")
        self.assertEqual(self.top("new-10"), "")
        self.start("new-1")
        statusbar.dress("new-1", "fable")
        self.assertIn("new-1", self.top("new-1"))
        self.assertEqual(self.top("new-10"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
