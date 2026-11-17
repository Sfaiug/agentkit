"""`ak standby ALIAS` copies ak's two folders of checkouts on the home, wt and work, whole and at
the same path, within one pass of each change: every file in them, what git ignores too, and each
checkout's `.git` file, which names its repository; of a clone, its files but not its `.git`
folder.  A checkout gone from the home goes from the copy, a `.git` folder here in it too.  A link
here at a checkout's folder goes, replaced by the home's checkout or removed with none, and what
it points at stays as it was.  Black-box, through tests/fixtures/twohomes.py.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

REPO = "code/acme-api"      # on the home, where git keeps its checkouts' data
CHECKOUTS = (".agentkit/wt/", ".agentkit/work/")
WT, WORK = ".agentkit/wt/20261116-0900-fix-api/", ".agentkit/work/20261116-0930-add-docs/"
CLONE = ".agentkit/wt/acme-seat/"       # a seat's clone, its git data in itself
OLD = ".agentkit/wt/20261020-0900-old-fix/"     # this machine's own, a clone the home lacks
OWN = "code/acme-own/"      # this machine's own repository, outside ak's folder


def checkouts(machine):
    """Each file and folder in `machine`'s wt and work, with each file's bytes, but a `.git`
    folder and what it holds."""
    return {path: data for path, data in machine.tree().items()
            if path.startswith(CHECKOUTS) and "/.git/" not in path
            and not (path.endswith("/.git") and data is None)}


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesCheckouts(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        home.write(f"{REPO}/main.py", "print('acme')\n")
        home.write(f"{REPO}/.gitignore", "*.log\n")
        self.git(home, "init", "-q", REPO)
        self.git(home, "-C", REPO, "add", ".")
        self.git(home, "-C", REPO, "commit", "-qm", "start")
        there = home.env["HOME"]
        self.git(home, "-C", REPO, "worktree", "add", "-q", "-b", "ak/fix-api", f"{there}/{WT}")
        self.git(home, "-C", REPO, "worktree", "add", "-q", "--detach", f"{there}/{WORK}")
        self.git(home, "clone", "-q", REPO, f"{there}/{CLONE}")
        for checkout in (WT, WORK, CLONE):
            home.write(f"{checkout}build.log", f"the home's {checkout}build.log")
            self.git(home, "-C", checkout, "check-ignore", "-q", "build.log")
        self.git(here, "init", "-q", OLD)
        here.write(f"{OLD}main.py", "this machine's")

    def git(self, machine, *args):
        done = machine.run("git", *args)
        self.assertEqual(done.code, 0, done.err)

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.here.tree()

    def test_each_checkout_crosses_whole_within_one_pass_of_each_change_but_a_git_folder(self):
        home, here = self.home, self.here
        copy = self.standby()
        self.assertEqual(checkouts(here), checkouts(home))
        for path in (f"{WT}.git", f"{WORK}.git", f"{WT}build.log", f"{CLONE}build.log",
                     f"{CLONE}main.py"):
            self.assertTrue(copy[path], path)
        self.assertTrue((home.path / CLONE / ".git/HEAD").is_file())
        self.assertNotIn(f"{CLONE}.git", copy)
        for checkout in (WT, WORK, CLONE):
            home.write(f"{checkout}main.py", "print('changed')\n")
            home.write(f"{checkout}docs/notes.md", "made")
            home.write(f"{checkout}late.log", "made")
            (home.path / checkout / "build.log").unlink()
        self.standby()
        self.assertEqual(checkouts(here), checkouts(home))

    def test_a_checkout_gone_from_the_home_goes_from_the_copy(self):
        home, here = self.home, self.here
        self.standby()
        self.git(home, "-C", REPO, "worktree", "remove", "--force", f"{home.env['HOME']}/{WORK}")
        shutil.rmtree(home.path / CLONE)
        self.standby()
        self.assertEqual(checkouts(here), checkouts(home))
        gone = tuple(checkout.rstrip("/") for checkout in (WORK, CLONE, OLD))
        self.assertEqual([path for path in here.tree() if path.startswith(gone)], [])

    def test_a_link_here_at_a_checkouts_folder_goes_and_what_it_points_at_stays(self):
        home, here = self.home, self.here
        self.git(here, "init", "-q", OWN)
        here.write(f"{OWN}main.py", "this machine's own")
        own = f"{here.env['HOME']}/{OWN}"     # as the machine names it
        # at a checkout the home has, and at one it lacks
        for checkout in (WT, ".agentkit/work/20261020-0900-old-docs/"):
            link = here.path / checkout.rstrip("/")
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(own)
        before = {path: data for path, data in here.tree().items() if path.startswith(OWN)}
        self.standby()
        self.assertEqual({path: data for path, data in here.tree().items()
                          if path.startswith(OWN)}, before)
        self.assertEqual(checkouts(here), checkouts(home))


if __name__ == "__main__":
    unittest.main()
