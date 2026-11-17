"""`ak standby ALIAS` leaves out of its copy each folder in ak's wt and work on the home that the
home's account cannot list or enter, with all in it, and each regular file there it cannot read,
and the pass ends well without them, what the home deleted going from the copy as ever.  What the
copy held of one stays till its checkout goes on the home, and goes with it; once the home reads
one again, the next pass copies it.  Elsewhere in ak's folder such a folder fails the pass, which
stamps nothing.  Black-box, through tests/fixtures/twohomes.py.
"""

import contextlib
import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

WT, WORK = ".agentkit/wt/20261116-0900-fix-api/", ".agentkit/work/20261116-0930-add-docs/"
GONE = ".agentkit/wt/20261116-0800-old-fix/"    # a checkout the home removes
FILES = ("main.py", "docs/notes.md")
# what tests stopped before they cleaned up left in checkouts, each by its mode: in one under wt
# a folder of mode 000 and one of 0300, each holding a file, a file of mode 000, and one named
# with rsync's wildcards and a backslash; in one under work a folder of mode 0111
LEFT = {f"{WT}build/locked/": 0o000, f"{WT}out/": 0o300, f"{WT}secret.key": 0o000,
        f"{WT}logs [*]\\old?.txt": 0o000, f"{WORK}cache/": 0o111}
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well


@unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassLeavesOutWhatTheHomeCannotRead(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for checkout in (WT, WORK, GONE):
            for name in FILES:
                home.write(f"{checkout}{name}", f"the home's {checkout}{name}")

    def make(self, path, mode):
        """Make `path` on the home, a folder holding a file where it ends in /, of `mode`; the
        test's end gives it a mode it can remove, as a test stopped before then would not."""
        name = f"{path}entry" if path.endswith("/") else path
        self.home.write(name, f"the home's {name}")
        (self.home.path / path).chmod(mode)
        self.addCleanup(self.readable, path)

    def readable(self, path):
        with contextlib.suppress(FileNotFoundError):
            (self.home.path / path).chmod(0o700)

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def copied(self, path):
        """Each file of `path` here, by its path, with its bytes."""
        return {name: data for name, data in self.here.tree().items()
                if name.startswith(path) and data is not None}

    def written(self, *paths):
        """The bytes the home wrote at each of `paths`."""
        return {path: f"the home's {path}".encode() for path in paths}

    def test_a_pass_leaves_out_what_the_home_cannot_read_and_ends_well(self):
        home, here = self.home, self.here
        self.standby()
        shutil.rmtree(home.path / GONE)
        home.write(f"{WT}main.py", "print('changed')\n")
        for path, mode in LEFT.items():
            self.make(path, mode)
        (here.path / STAMP).unlink()
        self.standby()
        self.assertTrue((here.path / STAMP).is_file())
        self.assertEqual(self.copied(WT), {f"{WT}main.py": b"print('changed')\n",
                                           **self.written(f"{WT}docs/notes.md")})
        self.assertEqual(self.copied(WORK), self.written(*(f"{WORK}{name}" for name in FILES)))
        for path in LEFT:
            self.assertFalse(os.path.lexists(here.path / path), path)
        self.assertFalse(os.path.lexists(here.path / GONE))

    def test_a_folder_the_home_reads_again_crosses_at_the_next_pass(self):
        locked = f"{WT}build/locked/"
        self.make(locked, 0o000)
        self.standby()
        self.assertFalse(os.path.lexists(self.here.path / locked))
        self.readable(locked)
        self.standby()
        self.assertEqual(self.copied(locked), self.written(f"{locked}entry"))

    def test_a_checkout_the_home_removes_goes_with_what_the_copy_held_of_one_it_cannot_read(self):
        home, here = self.home, self.here
        locked = f"{WT}build/locked/"
        self.make(locked, 0o700)
        self.standby()
        held = self.copied(locked)
        self.assertEqual(held, self.written(f"{locked}entry"))
        (home.path / locked).chmod(0o000)
        self.standby()
        self.assertEqual(self.copied(locked), held)
        self.readable(locked)
        shutil.rmtree(home.path / WT)
        self.standby()
        self.assertFalse(os.path.lexists(here.path / WT))
        self.assertEqual(self.copied(WORK), self.written(*(f"{WORK}{name}" for name in FILES)))

    def test_one_elsewhere_in_aks_folder_fails_the_pass_which_stamps_nothing(self):
        locked = ".agentkit/acme-notes/"
        self.make(locked, 0o000)
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertFalse(os.path.lexists(self.here.path / STAMP))
        self.readable(locked)
        self.standby()
        self.assertTrue((self.here.path / STAMP).is_file())


if __name__ == "__main__":
    unittest.main()
