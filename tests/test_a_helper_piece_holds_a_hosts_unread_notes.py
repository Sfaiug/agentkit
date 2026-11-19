"""A suite piece on a helper holds as many unread notes on a unix datagram socket as a host
does (`net.unix.max_dgram_qlen`): what the namespace it starts in holds, and 512 at least.  A
helper's container is a new network namespace holding the kernel's 10, and piece.sh's sandbox is
another.  A sandbox that does not hold them, as under a /proc/sys mounted read-only, runs no
command: the piece ends as one the helper could not run (253), which ak runs on its own host.
Real namespaces: piece.sh's `offline`, with the lines that size and try it, run from a namespace
of this test's own made to hold what a container or a larger host holds.
"""

import re
import subprocess
import unittest
from pathlib import Path

HELD = "/proc/sys/net/unix/max_dgram_qlen"
PIECE = (Path(__file__).resolve().parents[1] / "tools/helper/piece.sh").read_text()
# `fail`, then from the sandbox's size to the line that tries it.
SANDBOX = "".join(re.search(lines, PIECE, re.M | re.S).group(0)
                  for lines in (r"^fail\(\).*?\n", r"^notes=.*?^offline .*?\n"))


def held(outside, then=""):
    """What a piece reads in piece.sh's sandbox, started in a namespace holding `outside`, after
    `then` there."""
    proc = subprocess.run(
        ["unshare", "--user", "--map-current-user", "--net", "--mount", "--keep-caps", "bash",
         "-c", f"echo {outside} >{HELD} && {then}{SANDBOX}offline cat {HELD}"],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.split(), proc.stderr


class AHelperPieceHoldsAHostsUnreadNotes(unittest.TestCase):
    def test_a_container_s_ten_become_512_and_a_larger_host_s_own_are_kept(self):
        self.assertEqual(held(10)[:2], (0, ["512"]), held(10)[2])
        self.assertEqual(held(600)[:2], (0, ["600"]), held(600)[2])

    def test_a_read_only_proc_sys_runs_no_command_and_is_the_helper_s_failure(self):
        code, printed, said = held(
            10, "mount --bind /proc/sys /proc/sys && mount -o remount,bind,ro /proc/sys && ")
        self.assertEqual((code, printed), (253, []), said)


if __name__ == "__main__":
    unittest.main()
