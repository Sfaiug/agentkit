"""A Claude seat refuses Claude Code's own messages from other sessions; seats use `ak tell`.

Offline: the real adapters/claude.sh against a temporary HOME; it only prints the command.
"""

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/claude.sh"
CONVERSATION = "9f3a7c1e-2b4d-4e6f-8a0c-1d2e3f4a5b6c"


class SeatRefusesNativePeer(unittest.TestCase):
    def test_every_seat_launch_refuses_cross_session_messages(self):
        with tempfile.TemporaryDirectory(prefix="ak-seat-refuses-peer-") as tmp:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
            for account in ("", "quay"):
                for extra in ([CONVERSATION, "new"], [CONVERSATION]):
                    with self.subTest(account=account or "usual", resume=len(extra) == 1):
                        proc = subprocess.run(
                            [str(ADAPTER), "interactive", "opus", "medium", *extra],
                            capture_output=True, text=True,
                            env={**env, "HOME": tmp, "AGENTKIT_SESSION": "lagoon",
                                 "AGENTKIT_ACCOUNT": account})
                        self.assertEqual(proc.returncode, 0, proc.stderr)
                        words = shlex.split(proc.stdout)
                        tail = words[len(words) - words[::-1].index("--"):]
                        self.assertEqual(tail[0], "claude")
                        settings = json.loads(tail[tail.index("--settings") + 1])
                        self.assertEqual(settings["crossSessionInbound"], "refuse")


if __name__ == "__main__":
    unittest.main(verbosity=2)
