"""`ak standby ALIAS` leaves out each scratch checkout of the home's lander: a folder in wt whose
name begins `land-` and whose own git directory holds the lander's mark, `ak-lander-scratch`.
None crosses, and what the copy held of one goes; so with one the home's account cannot list, and
with files in one it cannot read, their names together past what one command may be given.  A
seat's checkout of such a name, which holds no mark, crosses as any does, with what is not
committed in it.  Black-box, through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

REPO = "code/acme-api"      # on the home, where git keeps its checkouts' data
SCRATCH, SEAT = ".agentkit/wt/land-ab12cd34/", ".agentkit/wt/land-seat/"
BUILT = f"{SCRATCH}tests/built.bin"     # what a check's tests wrote


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassLeavesOutTheLandersScratch(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        home.write(f"{REPO}/main.py", "print('acme')\n")
        self.git("init", "-q", REPO)
        self.git("-C", REPO, "add", ".")
        self.git("-C", REPO, "commit", "-qm", "start")
        there = home.env["HOME"]
        self.git("-C", REPO, "worktree", "add", "-q", "--detach", f"{there}/{SCRATCH}")
        self.git("-C", REPO, "worktree", "add", "-q", "-b", "seat/fix-api", f"{there}/{SEAT}")
        # the lander's mark, where it leaves one: a pass reads nothing in it
        own = Path(self.git("-C", SCRATCH, "rev-parse", "--absolute-git-dir"))
        home.write(own.relative_to(there) / "ak-lander-scratch", {})
        home.write(BUILT, "a check's own")
        home.write(f"{SEAT}notes.md", "not committed")
        here.write(BUILT, "copied before")

    def git(self, *args):
        done = self.home.run("git", *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip()

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(os.path.lexists(self.here.path / SCRATCH))

    def test_no_scratch_checkout_crosses_and_one_here_goes_but_a_seats_of_its_name_crosses(self):
        self.standby()
        self.assertEqual((self.home.path / BUILT).read_text(), "a check's own")
        copy = self.here.tree()
        self.assertEqual(copy.get(f"{SEAT}main.py"), b"print('acme')\n")
        self.assertEqual(copy.get(f"{SEAT}notes.md"), b"not committed")

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_one_the_home_cannot_list_goes_from_the_copy_too(self):
        scratch = self.home.path / SCRATCH
        scratch.chmod(0o111)    # git reads its `.git` still
        self.addCleanup(scratch.chmod, 0o700)
        self.standby()

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_files_in_one_the_home_cannot_read_fail_no_pass_however_many(self):
        # as long as a file's name may be, as few as pass the limit
        for n in range(os.sysconf("SC_ARG_MAX") // 255 + 1):
            (self.home.path / SCRATCH / f"{n:06d}-".ljust(255, "x")).touch(mode=0)
        self.standby()


if __name__ == "__main__":
    unittest.main()
