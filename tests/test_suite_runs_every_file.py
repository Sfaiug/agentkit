"""The `tests:` suite runs every test file smoke.sh does not: each once, clean, a failure named.

Offline: isolated suites and smoke lifecycle tests.
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
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-every-file-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        (root / "tests" / "smoke.sh").write_text(smoke)
        for name, body in files.items():
            (root / "tests" / f"{name}.py").write_text(body)
        self.log = root / "ran.log"
        return root

    def suite(self, root, offline="0"):
        env = dict(os.environ, HOME=str(root), ACME_LOG=str(self.log), ACME_KEPT="1", AGENTKIT_RUN="acme-run",
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

    def test_smoke_does_not_hide_unselected_failures(self):
        smoke = (REPO / "tests" / "smoke.sh").read_text()
        slot = smoke[smoke.index("slot_queue_check() {"):smoke.index("# Run the offline regressions")]
        balance = smoke[smoke.index("balancecheck() {"):smoke.index("# 8f:")]
        harness = ('#!/usr/bin/env bash\nREPO=$1\nWORK=$REPO\nFAILED=0\n'
                   'ok() { :; }\nno() { FAILED=1; }\n' + slot +
                   '\nslot_queue_check || FAILED=1\n' + balance + '\nexit "$FAILED"\n')
        names = ("test_v5am", "test_usage_balance", "test_audit_enforce_review_contract")
        # Chosen methods pass; only the omitted method can make the suite fail.
        broken = '''import pathlib, sys, unittest
class Acme(unittest.TestCase):
    def test_ok(self):
        pass
    def test_broken(self):
        self.fail(pathlib.Path(__file__).stem)
for spec in sys.argv[1:]:
    if ".test_" in spec:
        name, method = spec.split(".", 1)
        globals()[name] = Acme
        setattr(Acme, method, Acme.test_ok)
unittest.main()
'''
        root = self.checkout(dict.fromkeys(names, broken) | {"test_worker_list": PASSES},
                             smoke=harness)
        smoked = subprocess.run(["bash", str(root / "tests" / "smoke.sh"), str(root)],
                                env=dict(os.environ, HOME=str(root), ACME_LOG=str(self.log)),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=120)
        rest = self.suite(root)
        out = smoked.stdout + smoked.stderr + rest.stdout + rest.stderr
        self.assertNotEqual(smoked.returncode or rest.returncode, 0, out)
        for name in names:
            self.assertIn(f"AssertionError: {name}", out)

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

    def test_lifecycle_runs_the_original_alias_regression(self):
        smoke = (REPO / "tests" / "smoke.sh").read_text()
        start = smoke.index("lifecycle_check() {")
        body = smoke[smoke.index("from contextlib", start):smoke.index("\nPY\n", start)]
        name = "test_pruning_an_alias_preserves_the_live_seats_notice_and_latch"
        # A red assertion in the file must reach the runner that marks it as run.
        probe = '''import sys, unittest
import test_v4l
name = sys.argv[1]
original = getattr(test_v4l.Babysitter, name)
def broken(self):
    original(self)
    self.fail("original alias regression ran")
setattr(test_v4l.Babysitter, name, broken)
unittest.defaultTestLoader.loadTestsFromModule = lambda module: (
    unittest.defaultTestLoader.loadTestsFromName("Babysitter." + name, module))
sys.argv = ["-", "v4l"]
''' + body
        root = self.checkout({})
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(root), PYTHONPATH=f"{REPO}:{REPO / 'tests'}",
                   AK_RUN_DEPTH="0", AK_MAX_RUNS="0")
        proc = subprocess.run([sys.executable, "-c", probe, name], cwd=REPO, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=60)
        out = proc.stdout + proc.stderr
        self.assertIn("AssertionError: original alias regression ran", out)
        self.assertEqual(proc.returncode, 1, out)


if __name__ == "__main__":
    unittest.main()
