"""`ak standby ALIAS` leaves out of its copy of ak's folder each box's scratch, a folder named
`.box-…`, wherever it lies: in a checkout under wt or work too, where a test suite makes runs and
boxes of its own.  The pass ends well and stamps, the rest of each checkout crosses, and a checkout
the home removed goes from the copy, with what the copy held of a box in it.  A folder in a box's
scratch that the home's account can no longer enter once the home said what it cannot read, as a
box made meanwhile holds its overlay's work folder, fails nothing.  Black-box, through
tests/fixtures/twohomes.py.
"""

import contextlib
import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
WT, WORK = ".agentkit/wt/20261116-0900-fix-api/", ".agentkit/work/20261116-0930-add-docs/"
GONE = ".agentkit/wt/20261116-0800-old-fix/"    # a checkout the home removes
# what crosses of each checkout: its own files and a file of a test's run in it
FILES = ("main.py", "docs/notes.md", ".ak-test-k2j4/run/round-1/reviewer/events.jsonl")
# that run's box, and in it the folder its overlay works in, which the kernel makes mode 000
BOX = ".ak-test-k2j4/run/round-1/reviewer/.box-q7m2/"
WORKING = f"{BOX}go-build-work/work/"
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassLeavesOutEveryBoxsScratch(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for checkout in (WT, WORK, GONE):
            for name in (*FILES, f"{WORKING}entry"):
                home.write(f"{checkout}{name}", f"the home's {checkout}{name}")

    def standby(self):
        """A pass that ends well and stamps."""
        (self.here.path / STAMP).unlink(missing_ok=True)
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue((self.here.path / STAMP).is_file())

    def enterable(self, folder):
        """`folder` of a mode the test's end can remove, as a box's end leaves none."""
        with contextlib.suppress(FileNotFoundError):
            folder.chmod(0o700)

    def assertCopied(self, *checkouts):
        """The copy holds each file the home wrote in each of `checkouts` but its box, and nothing
        of a box anywhere."""
        tree = self.here.copy()
        for checkout in checkouts:
            self.assertEqual({path: data for path, data in tree.items()
                              if path.startswith(checkout) and data is not None},
                             {f"{checkout}{name}": f"the home's {checkout}{name}".encode()
                              for name in FILES})
        self.assertEqual([path for path in tree
                          if any(part.startswith(".box-") for part in Path(path).parts)], [])

    def test_a_pass_copies_each_checkout_but_its_boxes_and_a_removed_one_goes(self):
        home, here = self.home, self.here
        self.standby()
        self.assertCopied(WT, WORK, GONE)
        here.write(f"{GONE}{WORKING}entry", "as a pass copied it before boxes were left out")
        shutil.rmtree(home.path / GONE)
        self.standby()
        self.assertCopied(WT, WORK)
        self.assertFalse(os.path.lexists(here.path / GONE))

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder whatever its mode")
    def test_a_folder_in_a_box_unreadable_only_after_the_ask_fails_nothing(self):
        home, here = self.home, self.here
        working = home.path / WT / WORKING
        self.addCleanup(self.enterable, working)
        # before each transfer, once the home has said what it cannot read
        here.fake("rsync", f'#!/bin/sh\nssh {home.name} chmod 000 {WT}{WORKING} || exit\n'
                           f'exec {REAL} "$@"\n')
        self.standby()
        self.assertEqual(working.stat().st_mode & 0o777, 0)
        self.assertCopied(WT, WORK, GONE)


if __name__ == "__main__":
    unittest.main()
