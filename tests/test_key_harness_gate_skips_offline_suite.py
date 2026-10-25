"""A harness upgrade is gated by tests/live.sh and the fresh install, never by tests/smoke.sh.

smoke.sh is the landing suite's offline half: fake adapters stand in for every harness, and it
passed at landing on the same commit, so a harness release cannot make it fail; only host load
can, and twice that put a good release back.  So `ak update` keeps a new release once live and
e2e-fresh pass, whatever smoke would say; a red live still puts the old one back; and a checkout
with no tests/live.sh has no gate, so nothing is upgraded and ak says why.  Black-box: the
program `AK_BIN` names runs through tests/fixtures/akbin.py with a fake `claude`, the gates
stood in for by tests/fixtures/akgates.py.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, Home
from fixtures.akgates import Gates
from test_key_update_harness_upgrade import NEW, OLD, claude

GATES = ["live"] + (["e2e-fresh"] if sys.platform.startswith("linux") else [])


class HarnessGate(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.installed = claude(self.home)
        self.gates = Gates(self.home)

    def release(self):
        return self.installed.read_text().split()[0]

    def test_green_live_and_fresh_keep_the_release_and_smoke_never_runs(self):
        self.gates.exit("smoke", 1)
        done = self.home.ak("update", timeout=120)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.release(), NEW)
        self.assertEqual(self.gates.ran(), GATES)

    def test_a_red_live_puts_the_old_release_back(self):
        self.gates.exit("live", 1)
        done = self.home.ak("update", timeout=120)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(self.release(), OLD)
        self.assertEqual(self.gates.ran(), ["live"])

    def test_a_checkout_with_no_live_gate_upgrades_nothing_and_says_why(self):
        # the program's own checkout, as it is but for tests/live.sh
        checkout = self.home.root / "checkout"
        shutil.copytree(Path(AK).resolve().parents[1], checkout,
                        ignore=shutil.ignore_patterns(".git", "go", "tests", "__pycache__"))
        (checkout / "tests").mkdir()
        for name in ("smoke.sh", "e2e-fresh.sh"):
            (checkout / "tests" / name).write_text("exit 0\n")
        ak = checkout / Path(AK).resolve().relative_to(Path(AK).resolve().parents[1])
        for argv in (["update", "--dry-run"], ["update"]):
            with self.subTest(argv):
                done = self.home.run(str(ak), *argv, timeout=120)
                self.assertNotEqual(done.code, 0, done.out + done.err)
                self.assertIn("tests/live.sh", done.out + done.err)
                self.assertEqual(self.release(), OLD)
                self.assertEqual(self.gates.ran(), [])


if __name__ == "__main__":
    unittest.main()
