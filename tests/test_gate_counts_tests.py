"""The gate needs executed cases and permits only stdlib and repository imports."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "tests/every_file.py"
REPORTED = 'assert 1 + 1 == 2\nprint("TESTS_RUN=1")\n'
UNITTEST = '''import unittest
class Acme(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1 + 1, 2)
    def test_two(self):
        self.assertTrue(True)
unittest.main()
'''


class GateCountsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-gate-counts-", dir=REPO)))
        self.write("tests/smoke.sh", "#!/bin/bash\n")

    def write(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def gate(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(self.root),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        return subprocess.run([sys.executable, str(RUNNER), str(self.root)], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30)

    def assert_rejected(self, proc, name, reason):
        output = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, output)
        self.assertIn(name, output)
        self.assertIn(reason, output)

    def test_uninvoked_cases_fail_and_name_the_file(self):
        self.write("tests/test_acme.py", "def test_case():\n    assert False\n")
        self.assert_rejected(self.gate(), "tests/test_acme.py", "no tests ran")

    def test_empty_unittest_suite_fails(self):
        self.write("tests/test_acme.py", "import unittest\nunittest.main()\n")
        self.assert_rejected(self.gate(), "tests/test_acme.py", "Ran 0 tests")

    def test_unittest_cases_pass_with_the_tally_on_stderr(self):
        self.write("tests/test_acme.py", UNITTEST)
        proc = self.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS  tests/test_acme.py", proc.stdout)

    def test_a_single_unittest_case_passes(self):
        self.write("tests/test_acme.py", UNITTEST.replace("test_two", "check_two"))
        proc = self.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_an_explicit_case_count_passes(self):
        self.write("tests/test_acme.py", REPORTED)
        proc = self.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_a_missing_zero_or_malformed_count_fails(self):
        for report in ("OK", "TESTS_RUN=0", "TESTS_RUN=-1", "TESTS_RUN=one", "TESTS_RUN=1 extra"):
            with self.subTest(report=report):
                self.write("tests/test_acme.py", f"print({report!r})\n")
                self.assert_rejected(self.gate(), "tests/test_acme.py", "no tests ran")

    def test_a_case_count_does_not_override_a_failed_exit(self):
        self.write("tests/test_acme.py", REPORTED + "raise SystemExit(7)\n")
        self.assert_rejected(self.gate(), "tests/test_acme.py", "exit 7")

    def test_an_external_import_fails_in_every_source_directory(self):
        self.write("tests/test_acme.py", REPORTED)
        for name in ("agentkit/nested/helper.py", "tools/nested/helper.py",
                     "bin/ak", "tests/nested/helper.py"):
            with self.subTest(name=name):
                self.write(name, "#!/usr/bin/env python3\nif False:\n    import pytest\n")
                self.assert_rejected(self.gate(), name, "pytest")
                (self.root / name).unlink()

    def test_from_and_aliased_imports_are_checked_even_when_guarded(self):
        self.write("tests/test_acme.py", REPORTED)
        for statement in ("from pytest import fixture", "import json, pytest as cases",
                          "from pytest.mark import parametrize"):
            with self.subTest(statement=statement):
                self.write("tools/helper.py", f"if False:\n    {statement}\n")
                self.assert_rejected(self.gate(), "tools/helper.py", "pytest")

    def test_smoke_selection_does_not_exempt_a_dependency(self):
        self.write("tests/test_acme.py", REPORTED)
        self.write("tests/test_smoked.py", "import pytest\n")
        self.write("tests/smoke.sh", 'python3 "$REPO/tests/test_smoked.py"\n')
        self.assert_rejected(self.gate(), "tests/test_smoked.py", "pytest")

    def test_stdlib_and_repository_modules_are_allowed(self):
        self.write("tests/fixtures/helper.py", "thing = 1\n")
        self.write("browser/local.py", "thing = 2\n")
        self.write("agentkit/local.py", "from . import sibling\n")
        self.write("agentkit/sibling.py", "thing = 3\n")
        self.write("tools/helper.py", "from local import thing\n")
        self.write("tests/test_acme.py", "import json, sys\nfrom pathlib import Path\n"
                   "from fixtures.helper import thing\nassert thing == 1\n"
                   'print("TESTS_RUN=1")\n')
        proc = self.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_comments_and_strings_are_not_imports(self):
        self.write("tests/test_acme.py", '# import pytest\nsource = "import pytest"\n' + REPORTED)
        proc = self.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_a_syntax_error_in_a_non_test_source_fails(self):
        self.write("tests/test_acme.py", REPORTED)
        self.write("tools/helper.py", "def broken(\n")
        self.assert_rejected(self.gate(), "tools/helper.py", "invalid Python")


if __name__ == "__main__":
    unittest.main()
