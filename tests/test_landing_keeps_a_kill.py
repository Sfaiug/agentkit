"""A part of the landing suite a signal ended ends tests/landing.py as a shell ends: 128 + its
number, so a piece whose runner the kernel killed for memory is run again, never a red
(gate._SuiteMeasure.starved).

Offline: tests/landing.py runs in a temporary checkout of stand-ins, one of which ends as told.
"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from suite_shares import STATIC_CHECKS

REPO = Path(__file__).resolve().parents[1]
PARTS = (STATIC_CHECKS[0], "every_file", "gate_contract")


class LandingKeepsAKill(unittest.TestCase):
    def landing(self, part, body):
        """landing.py's run where the stand-in `part` is `body` and every other one passes."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-landing-kill-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        tests = Path(tmp.name, "tests")
        tests.mkdir()
        for name in (*STATIC_CHECKS, "every_file", "gate_contract"):
            (tests / f"{name}.py").write_text(body if name == part else "")
        (tests / "smoke.sh").write_text("true\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        return subprocess.run([sys.executable, str(REPO / "tests/landing.py")], cwd=tmp.name,
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=60)

    def test_a_part_killed_ends_it_as_killed(self):
        for part in PARTS:
            with self.subTest(part):
                proc = self.landing(part, "import os, signal\n"
                                          "os.kill(os.getpid(), signal.SIGKILL)\n")
                self.assertEqual(proc.returncode, 128 + signal.SIGKILL,
                                 proc.stdout + proc.stderr)

    def test_a_part_exiting_red_ends_it_with_that_exit(self):
        for part in PARTS:
            with self.subTest(part):
                proc = self.landing(part, "raise SystemExit(1)\n")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
