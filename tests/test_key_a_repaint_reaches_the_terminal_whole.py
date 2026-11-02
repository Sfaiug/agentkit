"""A repaint reaches any terminal as one synchronized update, so nothing shows half-drawn.  tmux
wraps one only for a terminal it knows takes them, which `xterm-256color` does not say.

Black-box: a seat `ak orch` opens, and what a client on a pty of that TERM receives.
"""

import os
import pty
import select
import signal
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, SOCKET, Home

BEGIN = b"\x1b[?2026h"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ARepaint(unittest.TestCase):
    def test_reaches_a_plain_terminal_as_one_update(self):
        with Home() as home:
            home.fake("claude", "#!/bin/sh\nsleep 600\n")
            akconfig.write(home, {"opus": {"harness": "claude", "model": "claude-acme-7",
                                           "effort": "low"}})
            cwd = home.path / "code" / "acme"
            cwd.mkdir(parents=True)
            done = home.ak("orch", "fix-api", "--model", "opus", "--workers", "opus", tty=True, cwd=cwd)
            self.assertEqual(done.code, 0, done.err)
            pid, fd = pty.fork()
            if pid == 0:
                os.execve(REAL_TMUX, ["tmux", "-L", SOCKET, "attach-session", "-t", "=fix-api:"],
                          home._env({"TERM": "xterm-256color"}))
            heard = b""
            while BEGIN not in heard and select.select([fd], [], [], 10)[0]:
                heard += os.read(fd, 65536)
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
            self.assertIn(BEGIN, heard)


if __name__ == "__main__":
    unittest.main()
