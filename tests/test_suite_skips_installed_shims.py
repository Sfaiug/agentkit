"""The suite runs every file without the caller's installed shims on its PATH.

A seat's PATH starts with its installed shims (`guard.shim_dir`), and the landing suite inherits
the PATH of whoever started it.  A test that puts this checkout's own shim first takes the first
`git` after it for the real one: an installed shim there answered for the live install instead,
and refused what the test expected git to do.  Offline: a temporary HOME and checkout, a fake
shim directory, and host readings injected.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import every_file
from agentkit import guard, host

CALM = {"cpus": 8, "load": 50, "cpu_pressure": 12, "free_mb": 4600}
# A test file that fails when the installed shims are on its PATH.
SEES = '''import os, sys
if os.environ["ACME_SHIMS"] in os.environ["PATH"].split(os.pathsep):
    sys.exit("the installed shims are on PATH")
print("TESTS_RUN=1")
'''


class SuiteSkipsInstalledShims(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-suite-shims-", dir=REPO)))
        self.shims = self.root / "home" / ".agentkit" / "bin"
        self.shims.mkdir(parents=True)
        (self.shims / "git").symlink_to(REPO / "tools" / "git-shim")
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(self.root / "home"), "ACME_SHIMS": str(self.shims),
            "PATH": os.pathsep.join([str(self.shims), os.environ.get("PATH", "")])}))
        self.enterContext(patch.object(guard, "shim_dir", return_value=self.shims))

    def test_a_file_runs_without_the_installed_shims_on_its_path(self):
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "smoke.sh").write_text("#!/bin/bash\n")
        (tests / "test_acme.py").write_text(SEES)
        out = io.StringIO()
        with patch.object(host, "host_readings", return_value=CALM), redirect_stdout(out):
            code = every_file.main(self.root)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("PASS  tests/test_acme.py", out.getvalue())


if __name__ == "__main__":
    unittest.main()
