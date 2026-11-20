"""A helper hands back (253) a piece whose command did not start.  `unshare` ends 1 where the
kernel makes it no namespace, as when its count of user namespaces is spent after piece.sh's
preflight, and so does a suite whose test failed: ak read the one as the other, a suite failure
naming no test.  The sandbox leaves a mark as it starts the command, and piece.sh reads from that
alone whether it did, asking for no further sandbox: without it the piece ends 253, with it as
its command did.  piece.sh's own lines, with a stand-in `unshare` first on PATH that counts its
calls and works only for the first WORKS of them.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_helper_piece_holds_a_hosts_unread_notes import END, FAIL, LAUNCH, SANDBOX

# The stand-in runs the next `unshare` on PATH. REST names that PATH from its environment: written
# into its text, a folder with a space in its name would end the assignment.
UNSHARE = ('PATH="$REST"; echo >>"$COUNT"; [ "$(wc -l <"$COUNT")" -le "$WORKS" ] || exit 1; '
           'exec unshare "$@"')


def piece(command, works):
    """How piece.sh's lines end on that command, in a new folder for their /home/ak, and how often
    they called `unshare`."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "unshare").write_text(f"#!/bin/sh\n{UNSHARE}\n")
        Path(tmp, "unshare").chmod(0o755)
        lines = f"{FAIL}command='{command}'\n{SANDBOX}{LAUNCH}{END}"
        proc = subprocess.run(["bash", "-c", lines], cwd=tmp, timeout=60, env=dict(
            os.environ, PATH=f"{tmp}:{os.environ['PATH']}", REST=os.environ["PATH"],
            COUNT=f"{tmp}/count", WORKS=str(works)))
        return proc.returncode, len(Path(tmp, "count").read_text().splitlines())


class AHelperHandsBackAPieceWhoseSandboxDidNotStart(unittest.TestCase):
    def test_only_a_launch_that_did_not_start_its_command_is_handed_back(self):
        # `unshare` works for the preflight alone; for the launch too, and for no call after it.
        for command, works, ends in (("exit 0", 1, (253, 2)), ("exit 1", 2, (1, 2))):
            self.assertEqual(piece(command, works), ends, (command, works))


if __name__ == "__main__":
    unittest.main()
