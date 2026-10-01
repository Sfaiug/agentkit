"""The `tests:` suite runs every test file smoke.sh does not: each once, clean, a failure named.

Offline: `tests/every_file.py` on a throwaway checkout of fake test files and a fake smoke.sh.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "tests" / "every_file.py"

# Each fake file notes that it ran; the host readings keep the runner off the real host.
PASSES = ('import os, pathlib\n'
          'with open(os.environ["ACME_LOG"], "a") as fh:\n'
          '    fh.write(pathlib.Path(__file__).stem + "\\n")\n')
FAILS = 'for n in range(1, 41):\n    print(f"acme line {n}")\nraise SystemExit(1)\n'
CLEAN = ('import os, sys\n'
         'leaked = sorted(k for k in os.environ if k.startswith(("AGENTKIT_", "AK_")))\n'
         'sys.exit(f"leaked: {leaked}" if leaked or os.environ.get("ACME_KEPT") != "1" else 0)\n')
SMOKE = '''#!/usr/bin/env bash
# test_comment.py is named in a comment only
if [ "${1:-}" = --acme ]; then
  python3 "$REPO/tests/test_argument.py"
  exit $?
fi
python3 "$REPO/tests/test_smoke.py"
lifecycle() {
  python3 - <<'PY'
import test_lifecycle
PY
}
if [ "${AGENTKIT_SMOKE_OFFLINE:-0}" = 1 ]; then
  python3 "$REPO/tests/test_offline.py"
  exit 0
fi
python3 "$REPO/tests/test_plain.py"
'''


class SuiteRunsEveryFile(unittest.TestCase):
    def checkout(self, files, smoke="#!/usr/bin/env bash\n"):
        tmp = tempfile.TemporaryDirectory(prefix="every-file-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        (root / "tests" / "smoke.sh").write_text(smoke)
        for name, body in files.items():
            (root / "tests" / f"{name}.py").write_text(body)
        self.log = root / "ran.log"
        return root

    def suite(self, root, offline="0"):
        env = dict(os.environ, ACME_LOG=str(self.log), ACME_KEPT="1", AGENTKIT_RUN="acme-run",
                   AK_RUN_DEPTH="2", AK_PARENT_RUN="acme-parent", AK_RUN_LOG="/nonexistent",
                   AK_HOST_READINGS='{"cpus": 2, "load": 0, "free_mb": 4096}',
                   AGENTKIT_SMOKE_OFFLINE=offline)
        return subprocess.run([sys.executable, str(RUNNER), str(root)], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=120)

    def ran(self):
        return sorted(self.log.read_text().split()) if self.log.exists() else []

    def test_a_failing_file_fails_the_suite_named_with_its_last_lines(self):
        root = self.checkout({"test_acme": PASSES, "test_boom": FAILS})
        proc = self.suite(root)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("FAIL  tests/test_boom.py", proc.stdout)
        self.assertIn("acme line 40", proc.stdout)
        self.assertNotIn("acme line 1\n", proc.stdout)
        self.assertIn("PASS  tests/test_acme.py", proc.stdout)

    def test_all_passing_files_pass(self):
        root = self.checkout({"test_acme": PASSES, "test_fix_api": PASSES})
        proc = self.suite(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.ran(), ["test_acme", "test_fix_api"])

    def test_no_run_variable_reaches_a_file(self):
        root = self.checkout({"test_clean": CLEAN})
        proc = self.suite(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS  tests/test_clean.py", proc.stdout)

    def test_every_file_smoke_does_not_run_runs_once(self):
        # smoke.sh's offline mode runs its offline block and exits there; the plain mode skips it
        names = ("test_smoke", "test_lifecycle", "test_comment", "test_offline", "test_acme",
                 "test_argument", "test_plain")
        for offline, ran in (("0", ["test_acme", "test_argument", "test_comment", "test_offline"]),
                             ("1", ["test_acme", "test_argument", "test_comment", "test_plain"])):
            with self.subTest(offline=offline):
                root = self.checkout(dict.fromkeys(names, PASSES), smoke=SMOKE)
                proc = self.suite(root, offline)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.ran(), ran)


if __name__ == "__main__":
    unittest.main()
