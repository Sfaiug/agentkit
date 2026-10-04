#!/usr/bin/env python3
"""What the gate is: every test file runs, and any failure fails.

tests/landing.py runs this beside its two parts.  It runs the real tests/every_file.py on a
stand-in checkout in every share of a split suite, so how every_file.py pools and orders its
files stays free to change while what it runs and what it lets pass does not.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "tests" / "every_file.py"
SHARES = 3

NOTE = ('import os, pathlib\n'
        'with open(os.environ["GATE_LOG"], "a") as fh:\n'
        '    fh.write(pathlib.Path(__file__).stem + "\\n")\n')
PASSES = NOTE + 'print("TESTS_RUN=1")\n'
FAILS = NOTE + 'print("TESTS_RUN=1")\nraise SystemExit(1)\n'
EMPTY = NOTE    # exits 0 but reports no executed case
# A name in a comment runs nothing, so it must not take the file out of every_file.py's share.
SMOKE = '#!/usr/bin/env bash\n# test_named.py\npython3 "$REPO/tests/test_smoked.py"\n'


class Gate(unittest.TestCase):
    def suite(self, files):
        """Each share's exit code and the files that ran, across every share."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-gate-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        (root / "tests" / "smoke.sh").write_text(SMOKE)
        for name, body in files.items():
            (root / "tests" / f"{name}.py").write_text(body)
        log = root / "ran.log"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        # Stand-in host readings keep the runner from waiting on the real host's load.
        env.update(HOME=str(root), GATE_LOG=str(log), AK_CGROUP_FILE=str(root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        codes = [subprocess.run([sys.executable, str(RUNNER), str(root)],
                                env=dict(env, AK_SHARD=f"{share}/{SHARES}"),
                                stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=300).returncode
                 for share in range(1, SHARES + 1)]
        return codes, sorted(log.read_text().split()) if log.exists() else []

    def test_every_file_smoke_does_not_run_runs_once_in_some_share(self):
        names = [f"test_part_{n}" for n in range(5)] + ["test_named", "test_smoked"]
        codes, ran = self.suite(dict.fromkeys(names, PASSES))
        self.assertEqual(codes, [0] * SHARES)
        self.assertEqual(ran, sorted(set(names) - {"test_smoked"}))

    def test_a_failing_file_fails_the_gate(self):
        codes, ran = self.suite({"test_part_0": PASSES, "test_part_1": FAILS,
                                 "test_part_2": PASSES})
        self.assertIn("test_part_1", ran)
        self.assertTrue(any(codes), codes)

    def test_a_file_that_runs_no_case_fails_the_gate(self):
        codes, ran = self.suite({"test_part_0": PASSES, "test_part_1": EMPTY})
        self.assertIn("test_part_1", ran)
        self.assertTrue(any(codes), codes)


if __name__ == "__main__":
    unittest.main()
