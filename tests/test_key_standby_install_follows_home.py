"""After its copy, `ak standby ALIAS` moves ak here to the commit ~/agentkit is at on the home,
as every move of ak goes: from ak's remote, swapped in, its install.sh run once, and never to the
remote's main past it.  Only once the home's move there is final: while its keep link is there
(`~/.agentkit/tmp/keep/ak`) ak here stays where it is.  Forward only: a standby ahead of its home
stays there.  An install.sh that failed here runs again on the next pass, the copy leaving this
machine's mark of it.  A pass that cannot move ak ends as its copy ended, 0 here, and
`ak standby` says why ak here does not follow its home yet, after the copy's age.  Black-box,
through tests/fixtures/twohomes.py: the two machines' installs are clones of one origin, and a
key moves one with git itself.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

STATE = ".agentkit/state/watch.json"     # the home's, which a pass copies
KEEP = ".agentkit/tmp/keep/ak"           # the home's link while its last move is not final


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbysInstallFollowsItsHome(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        home.write(STATE, "the home's")
        self.first = here.install.head()

    def moved(self, machine):
        """`machine`'s clone moved with git to one more commit on origin's main; its sha."""
        commit = machine.install.advance()
        machine.install.git("fetch", "-q", "origin")
        machine.install.git("merge", "-q", "--ff-only", commit)
        return commit

    def passed(self):
        """One pass, which copies, so exits 0."""
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.here.tree()[STATE], b"the home's")

    def said(self):
        said = self.here.ak("standby")
        self.assertEqual(said.code, 0, said.out + said.err)
        return said.out

    def test_ak_here_goes_to_its_homes_commit_once_though_main_is_past_it(self):
        commit = self.moved(self.home)
        self.home.install.advance()
        for _ in range(2):
            self.passed()
        self.assertEqual(self.here.install.head(), commit)
        self.assertEqual(self.here.install.installs(), 1)
        self.assertNotRegex(self.said(), "not final")

    def test_a_homes_move_not_final_moves_nothing_here_till_it_is(self):
        home, here = self.home, self.here
        commit = self.moved(home)
        keep = home.path / KEEP
        keep.parent.mkdir(parents=True)
        keep.symlink_to(Path(home.env["HOME"], ".agentkit/versions/acme/bin/ak"))
        self.passed()
        self.assertEqual((here.install.head(), here.install.installs()), (self.first, 0))
        self.assertRegex(self.said(), "not final")
        keep.unlink()
        self.passed()
        self.assertEqual((here.install.head(), here.install.installs()), (commit, 1))

    def test_a_standby_ahead_of_its_home_stays_there(self):
        commit = self.moved(self.here)
        self.passed()
        self.assertEqual((self.here.install.head(), self.here.install.installs()), (commit, 0))
        self.assertRegex(self.said(), "ahead")

    def test_an_install_sh_that_failed_here_runs_again_on_the_next_pass(self):
        (self.home.install.seed / "install.sh").write_text(
            '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\n[ -e "$HOME/install-ok" ] || exit 3\n'
            'echo installed >>"$HOME/installed"\n')
        commit = self.moved(self.home)
        self.passed()
        self.assertEqual((self.here.install.head(), self.here.install.installs()), (commit, 0))
        self.here.write("install-ok", "")
        self.passed()
        self.assertEqual(self.here.install.installs(), 1)

    def test_a_pass_whose_home_has_no_install_copies_and_leaves_ak_here(self):
        shutil.rmtree(self.home.install.path)
        self.home.install.advance()
        self.passed()
        self.assertEqual((self.here.install.head(), self.here.install.installs()),
                         (self.first, 0))


if __name__ == "__main__":
    unittest.main()
