"""A pass ends no session of a tmux server other than the one that listed it (`standby._close`):
a server started at ak's socket since the listing numbers its sessions from $0 again, so a
session made there may carry a listed id and a seat's mark of its own, and is the next pass's.
Real tmux: the listing is of one server, then the socket names another, as a restart leaves it.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import orch, standby


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AServerStartedSinceTheListing(unittest.TestCase):
    def test_its_marked_session_of_a_listed_id_stays(self):
        with tempfile.TemporaryDirectory(prefix="akt-", dir="/tmp") as root:
            first, since = Path(root, "first"), Path(root, "since")

            def tmux(at, *args):
                env = {**os.environ, "TMUX_TMPDIR": str(at)}
                return subprocess.run([REAL_TMUX, "-L", "acme", *args], capture_output=True,
                                      text=True, timeout=10, env=env).stdout.split()

            def seat(at):
                at.mkdir()
                [sid] = tmux(at, "-f", "/dev/null", "new-session", "-d", "-s", "fix-api", "-P",
                             "-F", "#{session_id}", "sleep 600")
                tmux(at, "set-option", "-t", sid, orch.MARK, "1")
                return sid

            listing = orch.tmux_out

            def restarted(*args, **kw):
                said = listing(*args, **kw)
                os.environ["TMUX_TMPDIR"] = str(since)
                return said

            try:
                self.assertEqual(seat(first), seat(since))
                listed = {"TMUX_TMPDIR": str(first), orch.SOCKET_ENV: "acme"}
                with patch.dict(os.environ, listed), patch.object(orch, "tmux_out", restarted):
                    standby._close()
                self.assertEqual(tmux(since, "list-sessions", "-F", "#{session_name}"), ["fix-api"])
            finally:
                for at in (first, since):
                    tmux(at, "kill-server")


if __name__ == "__main__":
    unittest.main()
