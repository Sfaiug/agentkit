"""Opening a seat tells tmux its environment and its options in one call.

tmux 3.5a itself, on a server of its own in this test's HOME, started first by another process
with a state root of its own; the harness is a stand-in that writes down what it was started with.
"""

import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, statusbar

SAYS = ("import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text("
        "os.environ[sys.argv[2]]); time.sleep(600)")
ROOT = "XDG_STATE_HOME"


class OneCall(Sandbox):
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
        self.calls, self.after = [], {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(statusbar, "dress"))
        # a log whose name ends as a tmux command does
        self.log = str(self.root / "sink;")
        self.stack.enter_context(patch.dict(os.environ, {notify.SINK_LOG_ENV: self.log}))
        os.environ.pop(ROOT, None)
        subprocess.run([*self.argv, "new-session", "-d", "-s", "other", "sleep 600"],
                       env={**self.env, ROOT: str(self.root / "stale")}, cwd=self.sockets,
                       check=True)

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        for word, then in self.after.items():
            if word in args:
                then()
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def asked(self, *args):
        """tmux's answer, outside the count of what opening the seat asked."""
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def heard(self, said):
        """What the stand-in harness wrote down, once it has."""
        deadline = time.monotonic() + 15
        while not said.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return said.read_text()

    def test_a_seat_s_environment_and_options_are_one_call_after_its_session(self):
        said = self.root / "said"
        orch.start("acme", self.root, [sys.executable, "-c", SAYS, str(said), notify.SINK_LOG_ENV],
                   "opus")
        made = next(n for n, args in enumerate(self.calls) if "new-session" in args)
        self.assertEqual(len(self.calls[made + 1:]), 1, self.calls[made + 1:])
        # the session is ours, knows its pane and outlives its harness
        self.assertEqual(self.asked("show-options", "-v", "-t", "=acme:", orch.MARK), (0, "1"))
        self.assertEqual(self.asked("show-options", "-v", "-t", "=acme:", orch.PANE_OPTION),
                         self.asked("display-message", "-p", "-t", "=acme:", "#{pane_id}"))
        self.assertEqual(self.asked("show-options", "-wv", "-t", "=acme:", "remain-on-exit"),
                         (0, "on"))
        # its later panes get the opener's log, whole, and not the server's old state root
        self.assertEqual(self.asked("show-environment", "-t", "=acme:", notify.SINK_LOG_ENV),
                         (0, f"{notify.SINK_LOG_ENV}={self.log}"))
        self.assertEqual(self.asked("show-environment", "-t", "=acme:", ROOT), (0, f"-{ROOT}"))
        # and so did the harness
        self.assertEqual(self.heard(said), self.log)

    def test_a_reopened_seat_s_environment_is_one_call_after_its_respawn(self):
        orch.start("acme", self.root, ["sleep", "600"], "opus")
        self.calls.clear()
        said = self.root / "said"
        orch._start_harness("acme", "opus", self.root,
                            [sys.executable, "-c", SAYS, str(said), notify.SINK_LOG_ENV],
                            {"name": "acme", "legacy": False})
        made = next(n for n, args in enumerate(self.calls) if "respawn-pane" in args)
        self.assertEqual(len(self.calls[made + 1:]), 1, self.calls[made + 1:])
        self.assertEqual(self.heard(said), self.log)
        self.assertEqual(self.asked("show-environment", "-t", "=acme:", notify.SINK_LOG_ENV),
                         (0, f"{notify.SINK_LOG_ENV}={self.log}"))
        self.assertEqual(self.asked("show-options", "-v", "-t", "=acme:", orch.PANE_OPTION),
                         self.asked("display-message", "-p", "-t", "=acme:", "#{pane_id}"))

    def test_a_seat_gone_as_it_starts_is_an_error(self):
        self.after["new-session"] = lambda: self.asked("kill-session", "-t", "=acme")
        with self.assertRaises(config.Error) as refused:
            orch.start("acme", self.root, ["sleep", "600"], "opus")
        self.assertIn("acme", str(refused.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
