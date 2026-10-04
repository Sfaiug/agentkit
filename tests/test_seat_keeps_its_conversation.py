"""Every Claude seat starts with Claude Code's background daemon off, so its conversation never
leaves the seat.

With the daemon on, `/background` moved a seat's conversation into a daemon process started by
another seat: its hooks and `ak` commands carried that seat's name, and its resume reopened the
conversation from before the move.  Offline: the real adapters/claude.sh against a temporary
HOME with a fake `claude` on PATH.
"""

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/claude.sh"
CONVERSATION = "9f3a7c1e-2b4d-4e6f-8a0c-1d2e3f4a5b6c"


class SeatKeepsItsConversation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-seat-no-daemon-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "claude").write_text("#!/usr/bin/env bash\nexit 0\n")
        (bin_dir / "claude").chmod(0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
        self.env.update(HOME=str(self.root), PATH=f"{bin_dir}{os.pathsep}{self.env.get('PATH', '')}",
                        AGENTKIT_SESSION="lagoon")

    def test_the_seat_command_turns_the_background_daemon_off_for_the_tui(self):
        for account in ("", "quay"):
            for extra in ([CONVERSATION, "new"], [CONVERSATION]):
                with self.subTest(account=account or "usual", resume=len(extra) == 1):
                    proc = subprocess.run(
                        [str(ADAPTER), "interactive", "opus", "medium", *extra],
                        capture_output=True, text=True,
                        env={**self.env, "AGENTKIT_ACCOUNT": account})
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    words = shlex.split(proc.stdout)
                    # an `env` assignment before the first program reaches every process
                    # down to the TUI, which inherits it
                    self.assertEqual(words[0], "env")
                    first = next(i for i, word in enumerate(words[1:], 1)
                                 if word not in ("-u",) and "=" not in word
                                 and words[i - 1] != "-u")
                    self.assertIn("CLAUDE_CODE_DISABLE_AGENT_VIEW=1", words[1:first])


if __name__ == "__main__":
    unittest.main()
