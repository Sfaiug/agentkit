"""A helper hands back (253) a piece whose command's launch ended nonzero where no sandbox can be
made any more: `unshare` itself may have failed with nothing run, which ak read as a suite failure
naming no test.  A command failing in a sandbox that can still be made ends as itself, and one that
ends 0 asks for no further sandbox.  piece.sh's own lines, with a stand-in `unshare` first on PATH
that counts its calls and works only for the first WORKS of them.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_helper_piece_holds_a_hosts_unread_notes import FAIL, LAUNCH, PIECE, SANDBOX

HAND_BACK = re.search(r"^.*\|\| offline true .*\n", PIECE, re.M).group(0)
UNSHARE = 'echo >>"$COUNT"; [ "$(wc -l <"$COUNT")" -le "$WORKS" ] || exit 1; exec unshare "$@"'


def piece(command, works):
    """How piece.sh's lines end on that command, and how often they called `unshare`."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "unshare").write_text(f"#!/bin/sh\nPATH={os.environ['PATH']}\n{UNSHARE}\n")
        Path(tmp, "unshare").chmod(0o755)
        lines = f"{FAIL}command='{command}'\n{SANDBOX}{LAUNCH}code=$?\n{HAND_BACK}exit $code"
        proc = subprocess.run(["bash", "-c", lines], timeout=60, env=dict(
            os.environ, PATH=f"{tmp}:{os.environ['PATH']}", COUNT=f"{tmp}/count", WORKS=str(works)))
        return proc.returncode, len(Path(tmp, "count").read_text().splitlines())


class AHelperHandsBackAPieceWhoseSandboxDidNotStart(unittest.TestCase):
    def test_only_a_failed_launch_with_no_sandbox_left_is_handed_back(self):
        # `unshare` works for the preflight alone; for every call; for the preflight and launch.
        for command, works, ends in (("exit 0", 1, (253, 3)), ("exit 1", 3, (1, 3)),
                                     ("exit 0", 2, (0, 2))):
            self.assertEqual(piece(command, works), ends, (command, works))


if __name__ == "__main__":
    unittest.main()
