"""`ak contract [HARNESS] [--snapshot FILE] [--counts FILE]` is the program's own check of its
harnesses: one whose program is not installed here is NOT CHECKED, and with none installed the
check fails saying it needs one, then gives its counts and exits 1.  Asked for `--counts FILE`, as
tests/smoke.sh's check 3 asks, it writes `passed failed skipped calls` there instead of the
counts line.

Black-box: the program `AK_BIN` names, in a Home of tests/fixtures/akbin.py whose adapters are
one manifest of the test's own, naming a program nothing installs: no turn runs.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, REPO

NONE = ["NOT CHECKED  3 acme: acme-cli is not installed",
        "FAIL  3: no harness here is installed with its login; the check needs one"]


class ContractVerb(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        adapters = self.home.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text(
            (REPO / "tests/fixtures/adapters/echo.toml").read_text().replace(
                'version = ["echo", "1.0.0"]', 'version = ["acme-cli", "1.0.0"]'))
        self.env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}

    def test_none_installed_fails_saying_so(self):
        done = self.home.ak("contract", env=self.env)
        self.assertEqual(done.code, 1, done.err)
        self.assertEqual(done.out.splitlines(), [*NONE, "0 passed, 1 failed, 0 skipped"])

    def test_counts_go_to_the_file_named(self):
        counts = self.home.root / "counts"
        done = self.home.ak("contract", "acme", "--snapshot", str(self.home.root / "usage.json"),
                            "--counts", str(counts), env=self.env)
        self.assertEqual(done.code, 1, done.err)
        self.assertEqual(done.out.splitlines(), NONE)
        self.assertEqual(counts.read_text(), "0 1 0 0\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
