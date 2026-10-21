"""The landing suite runs its static checks first in every share and stops when one fails.

Offline: tests/landing.py runs in a temporary checkout of stand-ins that note they started.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
STATIC = ("test_dead_code", "test_boundaries", "test_modules_say_what_they_are", "test_docs")
REST = ("smoke.sh", "every_file.py", "gate_contract.py")
NOTE = ('import os, pathlib\n'
        'with open(os.environ["ACME_LOG"], "a") as fh:\n'
        '    fh.write(pathlib.Path(__file__).name + "\\n")\n')


class LandingStaticFirst(unittest.TestCase):
    def landing(self, boundaries):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-static-first-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        for name in STATIC:
            (root / "tests" / f"{name}.py").write_text(NOTE)
        (root / "tests/test_boundaries.py").write_text(NOTE + boundaries)
        for name in REST[1:]:
            (root / "tests" / name).write_text(NOTE)
        (root / "tests/smoke.sh").write_text('echo smoke.sh >>"$ACME_LOG"\n')
        log = root / "ran.log"
        proc = subprocess.run([sys.executable, str(REPO / "tests/landing.py")], cwd=root,
                              env=dict(os.environ, ACME_LOG=str(log)), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
        return proc, log.read_text().splitlines() if log.exists() else []

    def test_a_failing_static_check_ends_the_share_before_the_rest_starts(self):
        proc, ran = self.landing('print("provider failure words: 61 lines, max 59")\n'
                                 'raise SystemExit(1)\n')
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("provider failure words: 61 lines, max 59", proc.stdout)
        self.assertIn("test_boundaries.py", ran)
        for part in REST:
            self.assertNotIn(part, ran)

    def test_passing_static_checks_start_the_rest(self):
        proc, ran = self.landing("")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertCountEqual(ran[:len(STATIC)], [f"{name}.py" for name in STATIC])
        self.assertCountEqual(ran[len(STATIC):], REST)

    def test_smoke_runs_none_of_them(self):
        smoke = (REPO / "tests/smoke.sh").read_text()
        for name in STATIC:
            self.assertNotIn(name, smoke)


if __name__ == "__main__":
    unittest.main()
