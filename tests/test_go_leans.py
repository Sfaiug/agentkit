"""go/leans/ only shrinks, to nothing at the switch: each key file it names still leans on Python's
files, and tests/test_go_keys.py judges every other claim in the switched tree, each new one among
them.  Each name is a key file go/keys.txt claims, each file is empty, and none is one go/leans/ did
not hold where this change left origin/main (test_boundaries.py), where that commit holds this
file: the list starts with the change adding it.  A file of its own each, so milestones clearing
leans side by side never meet.  Offline: git over this checkout.
"""

from pathlib import Path
import subprocess
import unittest

from suite_shares import claims
from test_boundaries import REPO, left_main
from test_go_keys import leaning


class LeansOnlyShrink(unittest.TestCase):
    def test_each_lean_is_an_empty_file_named_as_a_claimed_key_file(self):
        claimed = {name for name, *_ in claims(REPO)}
        for name in leaning(REPO):
            with self.subTest(name):
                self.assertIn(name, claimed, "go/keys.txt claims no key file so named")
                self.assertEqual((REPO / "go/leans" / name).read_bytes(), b"", "a lean is empty")

    def test_no_lean_is_new(self):
        held = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", left_main(),
                               "--", "tests/test_go_leans.py", "go/leans"],
                              capture_output=True, text=True)
        if held.returncode:
            self.skipTest("origin/main is not readable")
        before = held.stdout.splitlines()
        new = leaning(REPO) - {Path(name).name for name in before}
        self.assertFalse("tests/test_go_leans.py" in before and new,
                         f"new in go/leans/ since this change left origin/main: {sorted(new)}; "
                         "a claim must pass in the switched tree (tests/test_go_keys.py)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
