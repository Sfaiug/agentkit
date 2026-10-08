"""A question or summary that ends in `;` keeps it on its seat's bar.

tmux reads a `;` ending a call's word as the end of that command, so line two said `Review these
steps` where the seat had asked `Review these steps;`.  tmux 3.5a itself, on a server of its own
in this test's HOME.
"""

import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import orch, statusbar


class ClosingSemicolon(Sandbox):
    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        self.sockets = self.root / "sockets"
        self.sockets.mkdir()
        # the socket named from its own directory: below sockaddr_un's limit in any checkout
        self.env = {**os.environ, "TMUX_TMPDIR": str(self.sockets), "TERM": "xterm-256color"}
        self.env.pop("TMUX", None)
        self.argv = ["tmux", "-S", "agentkit-test"]
        self.addCleanup(subprocess.run, [*self.argv, "kill-server"], env=self.env,
                        cwd=self.sockets, capture_output=True)
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.assertEqual(self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "acme",
                                   "sleep 600")[0], 0)

    def tmux(self, *args, **_kw):
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def test_line_two_says_what_the_seat_said_to_its_last_character(self):
        for word, said in (("needs you", "Review these steps;"),
                           ("done", "Finished these steps;")):
            statusbar._write("acme", "opus", word=word, lasts=[said] * len(statusbar.BARS))
            for version in statusbar.WHYS:
                with self.subTest(word=word, version=version):
                    self.assertEqual(self.tmux("show-options", "-v", "-t", "=acme:", version),
                                     (0, "  " + said))
            # and the rest of the bar is told after it, the title last
            self.assertEqual(self.tmux("show-options", "-v", "-t", "=acme:",
                                       "set-titles-string"), (0, f"acme · {word}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
