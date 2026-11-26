"""A suite piece on a helper holds as many unread notes on a unix datagram socket as a host
does (`net.unix.max_dgram_qlen`): what the namespace it starts in holds, and 512 at least.  A
helper's container is a new network namespace holding the kernel's 10, and piece.sh's sandbox is
another.  A sandbox that does not hold them, as under a /proc/sys mounted read-only, runs no
command and ends 253, the helper's code for a piece it could not run, which ak runs on its own
host: at piece.sh's preflight, or at the command's launch where /proc/sys turned read-only after
it; a command that starts ends its sandbox as it ends itself.  Real namespaces: piece.sh's own
lines, the sandbox's size, the sandbox and its preflight, then the command's launch, run from a
namespace of this test's own made to hold what a container or a larger host holds.
"""

import re
import subprocess
import unittest
from pathlib import Path

HELD = "/proc/sys/net/unix/max_dgram_qlen"
PIECE = (Path(__file__).resolve().parents[1] / "tools/helper/piece.sh").read_text()
# piece.sh's own lines: from the sandbox's size to its preflight, and the command's launch.
SANDBOX, LAUNCH = (re.search(lines, PIECE, re.M).group(0) for lines in (
    r'^notes=(?s:.*?)^"\$@" sh -c :.*\n', r'^unrun=(?s:.*?)^\$command"\n'))
# Of /proc/sys/net: remounting a bind of /proc/sys leaves a mount at /proc/sys/net writable.
# Recursive: the kernel refuses a user namespace a plain bind with an inherited mount under it.
READ_ONLY = "mount --rbind /proc/sys/net /proc/sys/net && mount -o remount,bind,ro /proc/sys/net"


def piece(outside, start="", launch=""):
    """How piece.sh's lines end in a namespace holding `outside`, after `start` there and `launch`
    once past the preflight, which prints `launching`, on a command that prints what it holds and
    exits 42: its exit, what was printed and what was said."""
    proc = subprocess.run(
        ["unshare", "--user", "--map-current-user", "--net", "--mount", "--keep-caps", "bash",
         "-c", f"echo {outside} >{HELD}\n{start}\ncommand='cat {HELD}; exit 42'\n{SANDBOX}"
               f"echo launching\n{launch}\n{LAUNCH}"],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.split(), proc.stderr


class AHelperPieceHoldsAHostsUnreadNotes(unittest.TestCase):
    def test_a_container_s_ten_become_512_and_a_larger_host_s_own_are_kept(self):
        for outside, inside in (10, "512"), (600, "600"):
            code, printed, said = piece(outside)
            self.assertEqual((code, printed), (42, ["launching", inside]), said)

    def test_a_proc_sys_read_only_from_the_start_ends_the_piece_at_its_preflight(self):
        code, printed, said = piece(10, start=READ_ONLY)
        self.assertEqual((code, printed), (253, []), said)

    def test_a_proc_sys_read_only_after_the_preflight_ends_the_launch_unstarted(self):
        code, printed, said = piece(10, launch=READ_ONLY)
        self.assertEqual((code, printed), (253, ["launching"]), said)


if __name__ == "__main__":
    unittest.main()
