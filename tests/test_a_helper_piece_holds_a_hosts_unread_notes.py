"""A suite piece on a helper holds as many unread notes on a unix datagram socket as a host
does (`net.unix.max_dgram_qlen`): what the namespace it starts in holds, and 512 at least.  A
helper's container is a new network namespace holding the kernel's 10, and piece.sh's sandbox is
another.  Real namespaces: piece.sh's `offline`, with the lines that size it, run from a
namespace of this test's own made to hold what a container or a larger host holds.
"""

import re
import subprocess
import unittest
from pathlib import Path

HELD = "/proc/sys/net/unix/max_dgram_qlen"
PIECE = Path(__file__).resolve().parents[1] / "tools/helper/piece.sh"
SANDBOX = re.search(r"^notes=.*?^}\n", PIECE.read_text(), re.M | re.S).group(0)


def held(outside):
    """What a piece reads in piece.sh's sandbox, started in a namespace holding `outside`."""
    proc = subprocess.run(
        ["unshare", "--user", "--map-current-user", "--net", "--mount", "--keep-caps", "bash",
         "-c", f"echo {outside} >{HELD} && {SANDBOX}offline cat {HELD}"],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.split(), proc.stderr


class AHelperPieceHoldsAHostsUnreadNotes(unittest.TestCase):
    def test_a_container_s_ten_become_512_and_a_larger_host_s_own_are_kept(self):
        self.assertEqual(held(10)[:2], (0, ["512"]), held(10)[2])
        self.assertEqual(held(600)[:2], (0, ["600"]), held(600)[2])


if __name__ == "__main__":
    unittest.main()
