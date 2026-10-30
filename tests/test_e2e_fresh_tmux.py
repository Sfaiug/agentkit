"""The fresh gate's private tmux socket fits even with a long HOME and TMPDIR."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
FRESH = (REPO / "tests/e2e-fresh.sh").read_text()
SETUP = FRESH[FRESH.index("INVOKER=$(id -un)"):FRESH.index(". \"$REPO/tests/acceptance.sh\"")]
CLEANUP = FRESH[FRESH.index("cleanup_logs()"):FRESH.index("\ntrap cleanup EXIT")]


class FreshTmux(unittest.TestCase):
    def test_long_home_keeps_a_short_private_socket_and_cleans_it_up(self):
        with tempfile.TemporaryDirectory(prefix="ak-e2e-home-") as directory:
            caller = Path(directory) / ("acme-" + "x" * 48)
            caller.mkdir()
            env = {"HOME": str(caller), "TMPDIR": str(caller), "REPO": str(REPO),
                   "PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
            setup = subprocess.run(
                ["/bin/bash", "-c", SETUP + '\nprintf "%s\\n%s\\n" "$WORK" "$E2E_TMUX_DIR"'],
                env=env, capture_output=True, text=True, check=True, timeout=30)
            work, sockets = map(Path, setup.stdout.strip().splitlines())
            self.addCleanup(shutil.rmtree, work, ignore_errors=True)
            self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
            self.assertEqual(work.parent, caller / ".agentkit/tmp")
            # Bind the endpoint tmux uses, without starting a server or touching any seat.
            private = sockets / ("tmux-" + str(os.getuid()))
            private.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(private / "agentkit-test"))
            self.assertEqual(sockets.stat().st_mode & 0o777, 0o700)
            cleanup = subprocess.run(
                ["/bin/bash", "-c", """
tmux() { :; }
KEEP=0
""" + CLEANUP + "\ncleanup"],
                env={**env, "WORK": str(work), "E2E_TMUX_DIR": str(sockets)},
                capture_output=True, text=True, timeout=30)
            self.assertEqual(cleanup.returncode, 0, cleanup.stdout + cleanup.stderr)
            self.assertFalse(work.exists())
            self.assertFalse(sockets.exists())


if __name__ == "__main__":
    unittest.main()
