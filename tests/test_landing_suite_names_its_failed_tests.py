"""agentkit's landing suite names its failed tests (AK_FAILED) and runs only those asked for
(AK_ONLY), naming each it runs (AK_RAN), each a checkout-relative path.

Offline: tests/landing.py and the real tests/every_file.py run on a temporary checkout of
stand-ins that note each start and fail as told; the host readings are injected.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from suite_shares import STATIC_CHECKS

# Each stand-in notes its start; ACME_FAILS names those that always fail, ACME_FLAKY those
# that fail only their first run.
STAND_IN = '''import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
log = pathlib.Path(os.environ["ACME_LOG"])
with log.open("a") as fh:
    fh.write(name + "\\n")
print("TESTS_RUN=1")
sys.exit(name in os.environ["ACME_FAILS"].split()
         or name in os.environ["ACME_FLAKY"].split() and log.read_text().split().count(name) == 1)
'''
# Like smoke.sh, a piece runs only its share, and smoke.sh runs a test file of its own.
SMOKE = '''if [ "${AK_SHARD:-1/1}" = 1/1 ]; then
  echo smoke.sh >>"$ACME_LOG"
else
  echo "smoke.sh $AK_SHARD" >>"$ACME_LOG"
fi
python3 tests/test_smoked.py || exit 1
case " $ACME_FAILS " in *" smoke.sh "*) exit 1 ;; esac
'''
FILES = ("test_acme", "test_boom", "test_flaky", "test_fix_api", "test_smoked")


class LandingSuiteNamesItsFailedTests(unittest.TestCase):
    def landing(self, fails="", flaky="", only=None, shard="1/1", **modules):
        """landing.py's exit, the stand-ins that started and the tests it named as failed; those
        it named as run in `self.named`."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-failed-tests-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        tests = root / "tests"
        tests.mkdir()
        for name in ("landing.py", "affected.py", "suite_shares.py"):
            (tests / name).write_text((REPO / "tests" / name).read_text())
        # The real runner, on this checkout: left to its default it would sweep the repository.
        (tests / "every_file.py").write_text(
            'import os, sys\nos.execv(sys.executable, [sys.executable, '
            f'{str(REPO / "tests/every_file.py")!r}, os.getcwd(), *sys.argv[2:]])\n')
        for name in (*STATIC_CHECKS, *FILES, "gate_contract"):
            (tests / f"{name}.py").write_text(STAND_IN)
        (tests / "smoke.sh").write_text(SMOKE)
        for name, body in modules.items():
            (tests / f"{name}.py").write_text(body)
        log, failed, listed = root / "ran.log", root / "failed-tests", root / "only-tests"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(root), ACME_LOG=str(log), ACME_FAILS=fails, ACME_FLAKY=flaky,
                   AK_FAILED=str(failed), AK_RAN=str(root / "ran-tests"), AK_SHARD=shard, AK_CGROUP_FILE=str(root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        if only is not None:
            listed.write_text("".join(f"{test}\n" for test in only))
            env["AK_ONLY"] = str(listed)
        proc = subprocess.run([sys.executable, "tests/landing.py"], cwd=root, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=120)
        read = lambda path: sorted(path.read_text().splitlines()) if path.exists() else []
        self.named = read(root / "ran-tests")
        return proc, read(log), read(failed)

    def test_each_failure_is_named_once_and_a_flaky_file_is_not(self):
        proc, ran, failed = self.landing(fails="test_boom.py smoke.sh gate_contract.py",
                                         flaky="test_flaky.py")
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(failed, ["tests/gate_contract.py", "tests/smoke.sh",
                                  "tests/test_boom.py"])
        # Naming changes nothing that runs: every part, a failed file re-run.
        self.assertEqual(ran, sorted([f"{name}.py" for name in (*STATIC_CHECKS, *FILES)]
                                     + ["gate_contract.py", "smoke.sh", "test_boom.py",
                                        "test_flaky.py"]))

    def test_a_failing_static_check_is_named(self):
        proc, ran, failed = self.landing(fails="test_docs.py test_boundaries.py")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(failed, ["tests/test_boundaries.py", "tests/test_docs.py"])
        self.assertEqual(ran, sorted(f"{name}.py" for name in STATIC_CHECKS))

    def test_only_the_listed_tests_run_whatever_the_share(self):
        for shard in ("1/2", "2/2"):
            with self.subTest(shard=shard):
                proc, ran, failed = self.landing(
                    flaky="test_flaky.py", shard=shard,
                    only=["tests/test_flaky.py", "tests/test_docs.py", "tests/smoke.sh"])
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(ran, ["smoke.sh", "test_docs.py", "test_flaky.py",
                                       "test_flaky.py", "test_smoked.py"])
                self.assertEqual(failed, [])
                self.assertEqual(self.named, ["tests/smoke.sh", "tests/test_docs.py",
                                              "tests/test_flaky.py"])

    def test_a_listed_test_failing_again_fails_and_is_named(self):
        # smoke.sh runs test_smoked.py and is not listed: every_file.py runs it instead.
        proc, ran, failed = self.landing(
            fails="test_boom.py test_smoked.py gate_contract.py",
            only=["tests/test_boom.py", "tests/test_smoked.py", "tests/gate_contract.py"])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(ran, ["gate_contract.py", "test_boom.py", "test_boom.py",
                               "test_smoked.py", "test_smoked.py"])
        self.assertEqual(failed, ["tests/gate_contract.py", "tests/test_boom.py",
                                  "tests/test_smoked.py"])
        self.assertEqual(self.named, failed)

    def test_an_unknown_test_runs_nothing_fails_nothing_and_is_not_named_as_run(self):
        # Every stand-in would fail, and the import check too: no listed test holds it.
        tests = [f"{name}.py" for name in (*STATIC_CHECKS, *FILES, "gate_contract")]
        proc, ran, failed = self.landing(fails=" ".join(tests + ["smoke.sh"]),
                                         only=["tests/test_gone.py", "acme"],
                                         acme_client="import acme_vendored\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((ran, failed, self.named), ([], [], []))


if __name__ == "__main__":
    unittest.main()
