"""tests/test_go_keys.py judges a claim by what ran: on a made-up checkout with its own
go/keys.txt, a claim that fails, skips, runs no test or reaches Python ak fails and is named, and
a key it does not list fails, named as not there."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from suite_shares import claims

TESTS = Path(__file__).resolve().parent
KEY = """import os, subprocess, sys, unittest
from pathlib import Path
class Acme(unittest.TestCase):
    def test_it(self):
        {}
class Other(unittest.TestCase):
    def test_it(self):
        self.fail("a part this claim does not name")
unittest.main()
"""
KEYS = {
    "test_key_passes": KEY.format("pass"),
    "test_key_fails": KEY.format('self.fail("acme")'),
    "test_key_skips": KEY.format('self.skipTest("acme")'),
    "test_key_child_passes": KEY.format(
        'subprocess.run([sys.executable, "-c", "import unittest; unittest.TextTestRunner().run('
        'unittest.TestSuite([unittest.FunctionTestCase(lambda: None)]))"], check=True)\n'
        '        self.skipTest("acme")'),
    "test_key_no_test": "import unittest\nunittest.main()\n",
    "test_key_python_ak": KEY.format('subprocess.run([sys.executable, "-c", "import agentkit"], '
                                     'cwd=Path(__file__).parents[1], check=True)'),
    "test_key_the_build": KEY.format(
        'self.assertEqual(Path(os.environ["AK_BIN"]).read_text(), "built\\n")\n'
        '        self.assertTrue(Path(os.environ["AK_BIN"]).resolve().is_relative_to('
        'Path(__file__).resolve().parents[1]))'),
}
# Takes test_go.py's environment, and writes where `go build -o` is told to.
GO = '#!/bin/sh\n[ "$GOPROXY" = off ] || exit 1\nmkdir -p "$(dirname "$3")"\necho built >"$3"\n'


class Judges(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(
            tempfile.TemporaryDirectory(prefix="ak-keys-judges-"))).resolve()
        (self.root / "tests").mkdir()
        (self.root / "go").mkdir()
        (self.root / "agentkit").mkdir()
        (self.root / "agentkit/__init__.py").touch()
        shutil.copy(TESTS / "test_go_keys.py", self.root / "tests")
        shutil.copy(TESTS / "test_go.py", self.root / "tests")
        shutil.copy(TESTS / "suite_shares.py", self.root / "tests")
        for name, body in KEYS.items():
            (self.root / "tests" / f"{name}.py").write_text(body)

    def judged(self, *asked, keys, **env):
        (self.root / "go/keys.txt").write_text("".join(f"{key}\n" for key in keys))
        base = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        # A PYTHONPATH of the caller's leading to agentkit must not reach a claim, and the claims
        # failing or not there here are no parts of this file (every_file.py's FAILED_PARTS).
        return subprocess.run([sys.executable, self.root / "tests/test_go_keys.py", *asked],
                              env={**base, "AK_BIN": "/bin/true", "PYTHONPATH": str(self.root),
                                   "FAILED_PARTS": "", "NOT_THERE": "", **env},
                              text=True, capture_output=True, timeout=120)

    def test_what_the_claim_names_is_what_runs(self):
        for claim in ("test_key_passes Acme", "test_key_passes Acme.test_it"):
            with self.subTest(claim):
                done = self.judged(keys=[claim])
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_claim_failing_skipping_empty_or_reaching_python_ak_is_named(self):
        for claim in ("test_key_fails Acme", "test_key_skips Acme", "test_key_child_passes Acme",
                      "test_key_no_test", "test_key_python_ak Acme", "test_key_passes Other",
                      "test_key_passes Absent"):
            with self.subTest(claim):
                # Listed before a passing claim, of the same file in the last two: one claim with
                # it then, failing all the same.
                done = self.judged(keys=[claim, "test_key_passes Acme"])
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                self.assertIn(f"['{' '.join(claims(self.root)[0])}'] is not false", done.stderr)

    def test_names_keep_it_to_those_files_and_each_must_be_listed(self):
        keys = ["test_key_passes Acme", "test_key_fails"]
        self.assertEqual(self.judged("test_key_passes", keys=keys).returncode, 0)
        self.assertEqual(self.judged("test_key_fails", keys=keys).returncode, 1)
        absent = self.root / "absent"
        done = self.judged("test_key_passes", "test_key_skips", keys=keys, NOT_THERE=str(absent))
        self.assertEqual(done.returncode, 1)
        self.assertIn("{'test_key_skips'} is not false", done.stderr)
        self.assertEqual(absent.read_text().split(), ["test_key_skips"])

    def test_with_no_ak_bin_it_builds_in_the_copy(self):
        bin_dir = self.root / "path"
        bin_dir.mkdir()
        (bin_dir / "go").write_text(GO)
        (bin_dir / "go").chmod(0o755)
        path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        done = self.judged(keys=["test_key_the_build Acme"], AK_BIN="", PATH=path)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse((self.root / "go/bin").exists())

    def test_a_build_that_fails_names_each_claim_asked(self):
        bin_dir = self.root / "path"
        bin_dir.mkdir()
        (bin_dir / "go").write_text("#!/bin/sh\necho 'acme.go:1:1: undefined: acme' >&2\nexit 1\n")
        (bin_dir / "go").chmod(0o755)
        parts = self.root / "parts"
        keys = ["test_key_passes Acme", "test_key_fails"]
        for asked, named in (((), ["test_key_passes", "test_key_fails"]),
                             (("test_key_fails",), ["test_key_fails"])):
            with self.subTest(asked=asked):
                parts.write_text("")
                done = self.judged(*asked, keys=keys, AK_BIN="", FAILED_PARTS=str(parts),
                                   PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                self.assertIn("undefined: acme", done.stderr)
                self.assertEqual(parts.read_text().split(), named)

    def test_a_host_without_go_fails(self):
        done = self.judged(keys=["test_key_passes Acme"], AK_BIN="", PATH=str(self.root / "path"))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("'go'", done.stderr)

    def test_a_relative_ak_bin_is_read_from_the_checkout(self):
        (self.root / "bin").mkdir()
        (self.root / "bin/acme").write_text("built\n")
        (self.root / "tests/test_key_outside.py").write_text(KEY.format(
            f'self.assertEqual(os.environ["AK_BIN"], {str(self.root / "bin/acme")!r})'))
        done = self.judged(keys=["test_key_outside Acme"], AK_BIN="bin/acme")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
