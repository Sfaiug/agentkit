"""`ak standby ALIAS` leaves out each folder in wt of the lander's name, `land-`, its scratch
checkouts: none crosses, and what the copy held of one goes.  So with one made while the pass
runs, one git cannot read, one ak is still making, what a removal cut short left of one, and
files in one the home's account cannot read, their names together past what one command may be
given.  Another's checkout of that name crosses as any does: a seat's, with what is not committed
in it, and a copy of a scratch checkout, whose git directory git keeps for the one copied.
Black-box, through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

REPO = "code/acme-api"      # on the home, where git keeps its checkouts' data
WT = ".agentkit/wt"
SCRATCH, SEAT = f"{WT}/land-ab12cd34", f"{WT}/land-seat"
BUILT = "tests/built.bin"   # what a check's tests wrote
MARK = "ak-lander-scratch"  # the lander's, in its checkout's own git directory
REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it


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
        home.write(self.checkout(SCRATCH, "--detach") / MARK, {})
        self.checkout(SEAT, "-b", "seat/fix-api")
        home.write(f"{SEAT}/notes.md", "not committed")

    def git(self, *args):
        done = self.home.run("git", *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip()

    def checkout(self, tree, *args):
        """A checkout on the home at `tree`, with what a check's tests wrote in it, which a pass
        before copied here.  Its own git directory, where the lander leaves its mark."""
        there = self.home.env["HOME"]
        self.git("-C", REPO, "worktree", "add", "-q", *args, f"{there}/{tree}")
        self.built(tree)
        return Path(self.git("-C", tree, "rev-parse", "--absolute-git-dir")).relative_to(there)

    def built(self, tree):
        self.home.write(f"{tree}/{BUILT}", "a check's own")
        self.here.write(f"{tree}/{BUILT}", "copied before")

    def standby(self, *left_out):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        for tree in (SCRATCH, *left_out):
            self.assertTrue((self.home.path / tree).is_dir(), tree)
            self.assertFalse(os.path.lexists(self.here.path / tree), tree)

    def test_no_scratch_checkout_crosses_and_one_here_goes_but_anothers_of_its_name_crosses(self):
        copied = f"{WT}/land-recovery"
        done = self.home.run("cp", "-a", SCRATCH, copied)
        self.assertEqual(done.code, 0, done.err)
        self.home.write(f"{copied}/notes.md", "recovered")
        self.standby()
        copy = self.here.tree()
        self.assertEqual(copy.get(f"{SEAT}/main.py"), b"print('acme')\n")
        self.assertEqual(copy.get(f"{SEAT}/notes.md"), b"not committed")
        self.assertEqual(copy.get(f"{copied}/notes.md"), b"recovered")

    def test_one_made_while_the_pass_runs_does_not_cross(self):
        late = f"{WT}/land-ef56ab78"
        # a check starts as the home's rsync does: after the pass asked the home what to copy
        self.home.fake("rsync", f"""#!/bin/sh
late=$HOME/{late}
[ -e "$late" ] || {{
    git -C "$HOME/{REPO}" worktree add -q --detach "$late" &&
    echo '{{}}' > "$(git -C "$late" rev-parse --absolute-git-dir)/{MARK}" &&
    mkdir "$late/tests" && echo "a check's own" > "$late/{BUILT}"
}} || exit
exec {REAL} "$@"
""")
        self.standby(late)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_one_git_cannot_read_goes_from_the_copy_too(self):
        shut = f"{WT}/land-cd34ef56"
        self.home.write(self.checkout(shut, "--detach") / MARK, {})
        # the one the home's account cannot enter, the other's `.git` it cannot read
        for path in (self.home.path / SCRATCH, self.home.path / shut / ".git"):
            path.chmod(0)
            self.addCleanup(path.chmod, 0o700)
        self.standby(shut)

    def test_one_ak_is_still_making_and_what_a_removal_left_of_one_do_not_cross(self):
        making, cut = f"{WT}/land-12ab34cd", f"{WT}/land-56ef78ab"
        # as `git worktree add` leaves one till ak has put the lander's mark in it
        self.checkout(making, "--detach", "--lock", "--reason", "ak is making this checkout")
        self.built(cut)     # no checkout any more: its `.git` went first
        self.standby(making, cut)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_files_in_one_the_home_cannot_read_fail_no_pass_however_many(self):
        # as long as a file's name may be, as few as pass the limit
        for n in range(os.sysconf("SC_ARG_MAX") // 255 + 1):
            (self.home.path / SCRATCH / f"{n:06d}-".ljust(255, "x")).touch(mode=0)
        self.standby()


if __name__ == "__main__":
    unittest.main()
