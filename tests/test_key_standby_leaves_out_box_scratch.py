"""`ak standby ALIAS` leaves out of its copy of ak's folder each box's scratch, a folder named
`.box-…`, wherever it lies: in a checkout under wt or work too, where a test suite makes runs and
boxes of its own.  The pass ends well and stamps, the rest of each checkout crosses, and a checkout
the home removed goes from the copy, with what the copy held of a box in it.  A folder in a box's
scratch that the home's account can no longer enter during or after the initial scan, as a box
running meanwhile holds its overlay's work folder, fails nothing.  Under ~/code a `.box-…` folder
is still scanned and copied, leaving out what the home cannot read there, and an unreadable regular
file named `.box-…` in a checkout is left out too.  Black-box, through tests/fixtures/twohomes.py.
"""

import contextlib
import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
PYTHON = shutil.which("python3", path=os.pathsep.join(SYSTEM))
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

    def enterable(self, folder, mode=0o700):
        """`folder` of a mode the test's end can remove, as a box's end leaves none."""
        with contextlib.suppress(FileNotFoundError):
            folder.chmod(mode)

    def assertCopied(self, *checkouts, boxes=()):
        """The copy holds each file the home wrote in each of `checkouts` but its box, and nothing
        of a box anywhere except `boxes`."""
        tree = self.here.copy()
        for checkout in checkouts:
            self.assertEqual({path: data for path, data in tree.items()
                              if path.startswith(checkout) and data is not None},
                             {f"{checkout}{name}": f"the home's {checkout}{name}".encode()
                              for name in FILES})
        self.assertTrue(set(boxes) <= set(tree))
        self.assertEqual([path for path in sorted(set(tree) - set(boxes))
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

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder whatever its mode")
    def test_a_folder_in_a_box_unreadable_during_the_ask_fails_nothing(self):
        home = self.home
        watched = tuple(f"{top}{WORKING}".rstrip("/") for top in (WT, WORK))
        for path in watched:
            self.addCleanup(self.enterable, home.path / path)
        hook = (
            "import os, sys; "
            f"watched = {{os.fsencode(os.path.join(os.environ['HOME'], p)) for p in {watched!r}}}; "
            "sys.addaudithook(lambda e, a: os.chmod(a[0], 0) "
            "if e == 'os.scandir' and a[0] in watched else None); "
            "sys.argv = ['-', *sys.argv[1:]]; exec(sys.stdin.read(), {})"
        )
        home.fake("python3", f'#!/bin/sh\nif [ "$1" = "-I" ] && [ "$2" = "-" ]; then\n'
                             f'  shift 2\n  exec {PYTHON} -I -c {shlex.quote(hook)} "$@"\nfi\n'
                             f'exec {PYTHON} "$@"\n')
        self.standby()
        for path in watched:
            self.assertNotEqual((home.path / path).stat().st_mode & 0o777, 0)
        self.assertCopied(WT, WORK, GONE)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_a_box_under_code_still_copies_and_unreadable_entries_there_stay_out(self):
        home, here = self.home, self.here
        code_box = "code/acme-api/.box-q7m2"
        note = f"{code_box}/note"
        locked = f"{code_box}/go-build-work/work/"
        secret = f"{code_box}/secret.key"
        wt_file = f"{WT}.box-secret"
        home.write(note, "the home's note")
        home.write(f"{locked}entry", "the home's locked")
        home.write(secret, "the home's secret")
        home.write(wt_file, "the home's wt secret")
        for path, mode in ((locked, 0o700), (secret, 0o600), (wt_file, 0o600)):
            (home.path / path).chmod(0o000)
            self.addCleanup(self.enterable, home.path / path, mode)
        self.standby()
        self.assertEqual(here.copy()[note], b"the home's note")
        for path in (locked, secret, wt_file):
            self.assertFalse(os.path.lexists(here.path / path), path)
        self.assertCopied(WT, WORK, GONE, boxes=(code_box, f"{code_box}/go-build-work", note))


if __name__ == "__main__":
    unittest.main()
