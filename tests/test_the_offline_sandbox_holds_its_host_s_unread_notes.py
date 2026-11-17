"""The `tests:` line's sandbox holds as many unread notes on a unix datagram socket as the
namespace it starts in (`net.unix.max_dgram_qlen`).  A new network namespace holds the kernel's
10 whatever its host holds, and a sender past them waits for a reader: a key whose stand-in suite
sent more than its test had read yet hung at landing alone, 300 s a run until its own timeout,
and a line's check narrowed it for hours (17 Nov 2026).

Real namespaces: the line runs from a namespace of this test's own, made to hold 37, on a
stand-in tests/landing.py that prints what it finds.
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


def line(then=""):
    """The line run from a namespace holding 37, after `then` there: its exit code, what its
    suite printed and what it said."""
    with tempfile.TemporaryDirectory(prefix=".ak-test-offline-notes-", dir=REPO) as tmp:
        (Path(tmp) / "tests").mkdir()
        (Path(tmp) / "tests/landing.py").write_text(f"print(open({HELD!r}).read())\n")
        proc = subprocess.run(
            ["unshare", "--user", "--map-current-user", "--net", "--mount", "--keep-caps", "bash",
             "-c", f"echo 37 >{HELD} && {then}{gitcall.declared(REPO, 'tests')}"],
            cwd=tmp, capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.split(), proc.stderr


class OfflineSandboxNotes(unittest.TestCase):
    def test_the_sandbox_holds_what_the_namespace_it_starts_in_holds(self):
        code, printed, said = line()
        self.assertEqual((code, printed), (0, ["37"]), said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
