"""tests/unclaimed.py puts each key go/keys.txt does not claim whole in its place: on a made-up
checkout whose keys run a stand-in program through this checkout's tests/fixtures/akbin.py, as
real keys run Go, the one claimed is not run, and of the rest one passes, one hands over and
one answers wrong."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
KEY = """import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
class Acme(unittest.TestCase):
    def test_it(self):
        with Home() as home:
            done = home.ak("{}")
        self.assertEqual((done.code, done.out), (0, "right\\n"), done.err)
unittest.main()
"""
KEYS = {"test_key_claimed": "right", "test_key_right": "right", "test_key_over": "over",
        "test_key_wrong": "wrong"}
# Go's hand-over: its line on the end of the record, then exit 3.
STAND_IN = """#!/bin/sh
case $1 in
  right) echo right ;;
  over) echo "run gc: internal/cli/rungc.go:28" >>"$AK_HANDOVER"; exit 3 ;;
  *) echo wrong ;;
esac
"""


class Unclaimed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(cls.enterClassContext(
            tempfile.TemporaryDirectory(prefix="ak-unclaimed-"))).resolve()
        (root / "tests/fixtures").mkdir(parents=True)
        for name in ("unclaimed.py", "test_go_keys.py", "test_go.py", "suite_shares.py",
                     "fixtures/akbin.py"):
            shutil.copy(REPO / "tests" / name, root / "tests" / name)
        shutil.copy(REPO / "config.default.toml", root)
        for name, verb in KEYS.items():
            (root / "tests" / f"{name}.py").write_text(KEY.format(verb))
        (root / "go").mkdir()
        (root / "go/keys.txt").write_text("test_key_claimed\n")
        (root / "stand-in").write_text(STAND_IN)
        (root / "stand-in").chmod(0o755)
        base = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        cls.done = subprocess.run([sys.executable, root / "tests/unclaimed.py"],
                                  env={**base, "AK_BIN": "stand-in"}, capture_output=True,
                                  text=True, timeout=600)

    def setUp(self):
        self.assertEqual(self.done.returncode, 0, self.done.stderr)

    def test_the_claimed_key_is_not_run(self):
        self.assertNotIn("test_key_claimed", self.done.stdout + self.done.stderr)

    def test_a_key_answered_right_passes(self):
        self.assertIn("Passes: 1\n  test_key_right\n", self.done.stdout)

    def test_a_key_handed_over_is_listed_under_its_record_line(self):
        self.assertIn("Hands over: 1\n  run gc: internal/cli/rungc.go:28\n    test_key_over\n",
                      self.done.stdout)

    def test_a_key_answered_wrong_names_its_failing_test(self):
        self.assertIn("Answers wrong: 1\n  test_key_wrong: FAIL: test_it (__main__.Acme.test_it)\n",
                      self.done.stdout)


if __name__ == "__main__":
    unittest.main()
