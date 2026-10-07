"""A seat whose launch command is longer than tmux takes in one message still starts.

tmux 3.5a itself, on a server in this test's HOME, refuses a command over its 16 KiB message
("command too long"), and a harness that takes its rulebook as an argument carries more.  The
harness here is a stand-in that writes down how long the argument it was handed is.
"""

import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch


class LongCommand(Sandbox):
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
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))

    def tmux(self, *args, **_kw):
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def test_a_rulebook_sized_argument_reaches_the_harness_whole(self):
        said = self.root / "said"
        rules = "it's a rule\n" * 4000          # 48 KB, as a project seat's rulebook is
        harness = [sys.executable, "-c", "import pathlib, sys; "
                   "pathlib.Path(sys.argv[1]).write_text(str(len(sys.argv[2])))",
                   str(said), rules]
        orch.start("acme", self.root, harness, "grok")
        deadline = time.monotonic() + 15
        while not said.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(said.read_text(), str(len(rules)))
        self.assertEqual(list(self.root.joinpath("state").glob("launch-*")), [])

    def test_a_launch_cut_short_leaves_nothing_a_stop_misses(self):
        def interrupted(*args, **_kw):
            if "new-session" in args:
                raise KeyboardInterrupt       # the owner's Ctrl+C while tmux starts the seat
            return 0, ""
        with patch.object(orch, "tmux_out", side_effect=interrupted), \
                self.assertRaises(KeyboardInterrupt):
            orch.start("acme", self.root, ["grok", "--rules", "the rulebook"], "grok")
        left = [path for path in config.STATE.iterdir() if "acme" in path.name]
        self.assertTrue(left)
        self.assertEqual(set(left) - set(orch.session_owned_files("acme")), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
