"""The `tests:` line's sandbox holds as many unread notes on a unix datagram socket as the
namespace it starts in (`net.unix.max_dgram_qlen`).  A new network namespace holds the kernel's
10 whatever its host holds, and a sender past them waits for a reader: a key whose stand-in suite
sent more than its test had read yet hung at landing alone, 300 s a run until its own timeout,
and a line's check narrowed it for hours (17 Nov 2026).

Real namespaces: the line runs from a namespace of this test's own, made to hold 37, on a
stand-in tests/landing.py that prints what it finds.  Where the sandbox cannot take the 37, a
/proc/sys mounted read-only, the line runs no suite.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall

HELD = "/proc/sys/net/unix/max_dgram_qlen"


class OfflineSandboxNotes(unittest.TestCase):
    def gives(self, code, printed, then=""):
        """The line's exit code and what its suite printed, run from a namespace holding 37."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-offline-notes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "tests").mkdir()
        (Path(tmp.name) / "tests/landing.py").write_text(f"print(open({HELD!r}).read())\n")
        proc = subprocess.run(
            ["unshare", "--user", "--map-current-user", "--net", "--mount", "--keep-caps", "bash",
             "-c", f"echo 37 >{HELD} && {then}{gitcall.declared(REPO, 'tests')}"],
            cwd=tmp.name, capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stdout.split()), (code, printed), proc.stderr)

    def test_the_sandbox_holds_what_the_namespace_it_starts_in_holds(self):
        self.gives(0, ["37"])

    def test_a_sandbox_that_cannot_hold_it_runs_no_suite(self):
        read_only = "mount --bind /proc/sys /proc/sys && mount -o remount,bind,ro /proc/sys && "
        self.gives(1, [], read_only)


if __name__ == "__main__":
    unittest.main(verbosity=2)
