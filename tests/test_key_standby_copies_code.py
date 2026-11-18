"""`ak standby ALIAS` copies ~/code as rsync copies any folder, a project's `.git` folder and what
git ignores too; the next pass brings what changed and takes what the home removed, a whole
project too.  A file beside ~/code does not come, and a home without ~/code leaves the copy's as it
was.  What the home's account cannot read there stays out, and the pass ends well; readable again,
it comes with the next.  A pass from a home whose ~/code is a link fails before it copies
anything, and so does one on a machine whose ak runs from under its own ~/code.  Black-box,
through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

MAIN, GIT, IGNORES = "code/acme-api/main.py", "code/acme-api/.git/HEAD", "code/acme-api/.gitignore"
IGNORED, OTHER = "code/acme-api/build.log", "code/acme-web/index.html"
BESIDE = "notes/plan.txt"
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well


def code(machine):
    """Each file and folder in `machine`'s ~/code, with each file's bytes."""
    return {path: data for path, data in machine.tree().items() if path.startswith("code/")}


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesCode(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for path in (MAIN, GIT, IGNORED, OTHER, BESIDE):
            home.write(path, f"the home's {path}")
        home.write(IGNORES, "*.log\n")

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_pass_copies_code_whole_then_what_changed_and_what_the_home_removed(self):
        home, here = self.home, self.here
        for change in (lambda: None,
                       lambda: (home.write(MAIN, "changed"), (home.path / IGNORED).unlink(),
                                shutil.rmtree(home.path / "code/acme-web"))):
            change()
            self.standby()
            self.assertEqual(code(here), code(home))
        self.assertEqual(code(here)[MAIN], b"changed")
        self.assertEqual({IGNORED, "code/acme-web"} & set(code(here)), set())
        self.assertNotIn(BESIDE, here.tree())
        shutil.rmtree(home.path / "code")
        before = code(here)
        self.standby()
        self.assertEqual(code(here), before)
        self.assertIn(GIT, before)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder or file whatever its mode")
    def test_what_the_home_cannot_read_stays_out_and_comes_once_it_can(self):
        home, here = self.home, self.here
        locked, secret = "code/acme-api/build/locked/", "code/acme-api/secret.key"
        modes = {locked: 0o700, secret: 0o600}     # a mode the test's end can remove it in
        for path in (f"{locked}entry", secret):
            home.write(path, f"the home's {path}")
        for path, mode in modes.items():
            self.addCleanup((home.path / path).chmod, mode)
            (home.path / path).chmod(0o000)
        self.standby()
        self.assertTrue((here.path / STAMP).is_file())
        for path in (MAIN, GIT, IGNORED, OTHER):
            self.assertEqual(code(here)[path], f"the home's {path}".encode())
        for path in (locked, secret):
            self.assertFalse(os.path.lexists(here.path / path), path)
        for path, mode in modes.items():
            (home.path / path).chmod(mode)
        self.standby()
        self.assertEqual(code(here), code(home))

    def test_a_pass_from_a_home_whose_code_is_a_link_fails_and_copies_nothing(self):
        home, here = self.home, self.here
        self.standby()
        # the home's ~/code moved to a folder of its own, linked by the path it has on both
        # machines, then linked to nothing
        (home.path / "code").rename(home.path / "projects")
        home.write("projects/acme-api/main.py", "changed")
        home.write(".agentkit/acme-notes.md", "the home's, changed")
        for to in ("projects", "missing"):
            with self.subTest(to=to):
                (home.path / "code").unlink(missing_ok=True)
                (home.path / "code").symlink_to(f"{home.env['HOME']}/{to}")
                before, stamp = here.copy(), (here.path / STAMP).read_bytes()
                done = here.ak("standby", home.name)
                self.assertEqual(done.code, 1, done.out + done.err)
                self.assertEqual((here.path / STAMP).read_bytes(), stamp)
                self.assertEqual(here.copy(), before)
                self.assertFalse((here.path / "code").is_symlink())

    def test_a_machine_whose_ak_runs_from_under_its_code_refuses_and_changes_nothing(self):
        here = self.here
        own = "code/acme-tools/agentkit"
        (here.path / own).parent.mkdir(parents=True)
        (here.path / "agentkit").rename(here.path / own)
        (here.path / "agentkit").symlink_to(f"{here.env['HOME']}/{own}")
        crontab = here.root / "crontab"
        before, table = here.copy(), crontab.read_bytes() if crontab.exists() else None
        done = here.ak("standby", self.home.name)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"refused: ak runs from ~/{own}", done.err)
        self.assertEqual(here.copy(), before)
        self.assertEqual(crontab.read_bytes() if crontab.exists() else None, table)


if __name__ == "__main__":
    unittest.main()
