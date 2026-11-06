"""A test file that names its failing parts is named `<file>::<part>` by tests/every_file.py, its
re-run runs just those parts, a part it timed keeps its own seconds whatever the others did, and
AK_ONLY listing one runs the file for that part alone; the Go keys check given a claim's name
runs that claim alone and names it when it fails.

Offline: the real every_file.py runs on a temporary checkout of a stand-in noting each run's
parts, with injected host readings; the real Go key files judge stand-in keys with AK_BIN set.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import suite_times

# Notes the parts each run runs, all three without arguments; fix_api fails on the first
# ACME_FAILING_RUNS runs and is named in the file FAILED_PARTS names, the others timed.
STAND_IN = '''import json, os, pathlib, sys
log = pathlib.Path(os.environ["ACME_LOG"])
runs = len(log.read_text().splitlines()) if log.exists() else 0
parts = sys.argv[1:] or ["acme", "fix_api", "widget"]
with log.open("a") as fh:
    fh.write(" ".join(parts) + "\\n")
failing = [part for part in parts
           if part == "fix_api" and runs < int(os.environ["ACME_FAILING_RUNS"])]
with open(os.environ["FAILED_PARTS"], "a") as fh:
    fh.writelines(f"{part}\\n" for part in failing)
open(os.environ["PART_TIMES"], "w").write(json.dumps({p: 1.5 for p in parts if p not in failing}))
print(f"TESTS_RUN={len(parts)}")
sys.exit(bool(failing))
'''
ACME, PART, WIDGET = (f"tests/test_acme.py::{part}" for part in ("acme", "fix_api", "widget"))
# A key that notes its run and fails where ACME_FAILS names it.
KEY = '''import os, pathlib, unittest
class Acme(unittest.TestCase):
    def test_it(self):
        name = pathlib.Path(__file__).stem
        with open(os.environ["ACME_LOG"], "a") as fh:
            fh.write(name + "\\n")
        self.assertNotEqual(name, os.environ["ACME_FAILS"])
unittest.main()
'''


class EveryFileRerunsAFilesNamedParts(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-named-parts-", dir=REPO)))
        (self.root / "tests").mkdir()
        self.base = {k: v for k, v in os.environ.items()
                     if not k.startswith(("AGENTKIT_", "AK_"))}

    def read(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def every_file(self, failing_runs, only=None):
        """every_file.py's run and output; the stand-in's runs are in ran.log."""
        (self.root / "tests/smoke.sh").write_text("")
        (self.root / "tests/test_acme.py").write_text(STAND_IN)
        env = dict(self.base, HOME=str(self.root), ACME_LOG=str(self.root / "ran.log"),
                   ACME_FAILING_RUNS=str(failing_runs), AK_FAILED=str(self.root / "failed"),
                   AK_FLAKY=str(self.root / "flaky"), AK_RAN=str(self.root / "ran"),
                   AK_CGROUP_FILE=str(self.root / "no-cgroup"),
                   AK_TIMES='{"tests/test_acme.py::acme": 1}',    # listed parts share a run
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        if only is not None:
            (self.root / "only").write_text("".join(f"{test}\n" for test in only))
            env["AK_ONLY"] = str(self.root / "only")
        return subprocess.run([sys.executable, str(REPO / "tests/every_file.py"), str(self.root)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=120)

    def test_a_failing_part_is_named_alone_and_its_re_run_runs_just_it(self):
        proc = self.every_file(failing_runs=2)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.read("failed"), [PART])
        self.assertEqual(self.read("ran.log"), ["acme fix_api widget", "fix_api"])

    def test_a_part_passing_its_re_run_is_flaky_and_each_part_keeps_its_own_time(self):
        proc = self.every_file(failing_runs=1, only=[ACME, PART, WIDGET])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.read("failed"), self.read("flaky")), ([], [PART]))
        self.assertEqual(self.read("ran.log"), ["acme fix_api widget", "fix_api"])
        self.assertEqual([found[1] for line in proc.stdout.splitlines()
                          if (found := suite_times.PASSED.match(line))], [ACME, WIDGET, PART])

    def test_a_listed_part_runs_alone_and_is_named_as_run(self):
        proc = self.every_file(failing_runs=2, only=[PART])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.read("ran.log"), ["fix_api", "fix_api"])
        self.assertEqual((self.read("ran"), self.read("failed")), ([PART], [PART]))

    def test_the_go_keys_check_given_a_claims_name_runs_that_claim_alone(self):
        for name in ("test_go_keys.py", "test_go.py", "suite_shares.py"):
            shutil.copy(REPO / "tests" / name, self.root / "tests")
        (self.root / "go").mkdir()
        keys = ("test_key_acme", "test_key_fix_api", "test_key_widget")
        (self.root / "go/keys.txt").write_text("".join(f"{key} Acme\n" for key in keys))
        for key in keys:
            (self.root / "tests" / f"{key}.py").write_text(KEY)
        done = subprocess.run(
            [sys.executable, self.root / "tests/test_go_keys.py", "test_key_widget"],
            env=dict(self.base, AK_BIN="/bin/true", ACME_LOG=str(self.root / "ran.log"),
                     ACME_FAILS="test_key_widget", FAILED_PARTS=str(self.root / "parts")),
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(self.read("ran.log"), ["test_key_widget"])
        self.assertEqual(self.read("parts"), ["test_key_widget"])


if __name__ == "__main__":
    unittest.main()
