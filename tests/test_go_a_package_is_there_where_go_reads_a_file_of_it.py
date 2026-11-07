"""tests/test_go.py asks Go whether a tree has a part's package, as `go test ./...` decides it: one
Go reads no file of -- none there, or each it leaves out (`_x.go`, `.x.go`, a build tag's) -- is
not there, named so and as no failing part; one holding a file Go cannot read (a malformed
`//go:build`) or that does not compile is named failing.

The real test_go.py and go judge a temporary module of made-up packages.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
# Each package's one file and whether test_go.py names the package failing; gone has none.
PACKAGES = {
    "underscore": ("_acme.go", "package underscore\n", False),
    "dot": (".acme.go", "package dot\n", False),
    "tagged": ("acme.go", "//go:build acme_tools\n\npackage tagged\n", False),
    "badtag": ("acme_test.go", "//go:build (\n\npackage badtag\n", True),
    "broken": ("acme.go", 'package broken\n\nfunc f() int { return "x" }\n', True),
}


class GoAPackageIsThereWhereGoReadsAFileOfIt(unittest.TestCase):
    def test_only_a_package_go_reads_a_file_of_is_named_failing(self):
        # Never a skip: the landing suite counts a skipped case as passed.
        self.assertTrue(shutil.which("go"), "go is not installed: Go 1.23 or newer builds go/")
        tree = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="ak-test-go-reads-")))
        (tree / "tests").mkdir()
        for name in ("test_go.py", "suite_shares.py"):
            shutil.copy(REPO / "tests" / name, tree / "tests")
        # The caller's GOFLAGS could select a tagged file: these judge Go's plain selection.
        env = {**os.environ, "GOFLAGS": "", "FAILED_PARTS": str(tree / "failed"),
               "NOT_THERE": str(tree / "absent")}
        release = subprocess.run(["go", "env", "GOVERSION"], env=env, capture_output=True,
                                 text=True, check=True).stdout.strip()
        (tree / "go").mkdir()
        (tree / "go/go.mod").write_text(f"module agentkit\n\ngo 1.23.0\n\ntoolchain {release}\n")
        for package, (name, source, _) in PACKAGES.items():
            (tree / "go/internal" / package).mkdir(parents=True)
            (tree / "go/internal" / package / name).write_text(source)
        parts = [f"agentkit/internal/{package}" for package in ("gone", *PACKAGES)]
        done = subprocess.run([sys.executable, tree / "tests/test_go.py", *parts], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=600)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        failed = [f"agentkit/internal/{package}"
                  for package, (*_, failing) in PACKAGES.items() if failing]
        # each part fails or is not there
        self.assertEqual([(tree / name).read_text().splitlines() for name in ("failed", "absent")],
                         [failed, [part for part in parts if part not in failed]], done.stderr)


if __name__ == "__main__":
    unittest.main()
