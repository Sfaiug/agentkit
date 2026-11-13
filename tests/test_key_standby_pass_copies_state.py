"""`ak standby ALIAS`, run on a client of ALIAS, makes one pass of this machine's copy of ak's
folder on that home, at the same path: what the home deleted goes here too, and the home's runs
and checkouts stay out.  This machine's record of its server, ak's tmp folder, its ak install and
ak's repository stay as they were, and nothing starts from the copy.  A pass whose home does not
answer, or has no ak folder, leaves the copy as it was, says why and exits non-zero; a machine
not ALIAS's client is refused, saying so.  Black-box, through tests/fixtures/twohomes.py.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

STATE = ".agentkit/state/watch.json"     # the home's, which a pass copies
GONE = ".agentkit/tasks/fix-api.md"      # copied by an earlier pass, since deleted on the home
# the home's runs and checkouts, which no pass copies
RUNS = (".agentkit/runs/r-fix-api/run.json", ".agentkit/wt/r-fix-api/main.py",
        ".agentkit/work/acme-api/main.py")
SERVER = ".agentkit/state/server"     # this machine's, which the home has none of
# this machine's own, which the home holds its own of: ak's tmp folder, its ak install, ak's
# repository and a version of ak
OWN = (".agentkit/tmp/watch.log", "agentkit/bin/ak", ".agentkit/agentkit.git/HEAD",
       ".agentkit/versions/1e05b19/bin/ak")


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesAksFolder(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for path in (STATE, *RUNS, *OWN):
            home.write(path, f"the home's {path}")
        for path in (GONE, *OWN):
            here.write(path, f"this machine's {path}")

    def test_a_pass_copies_aks_folder_but_its_runs_and_checkouts_and_keeps_this_machines_own(self):
        home, here = self.home, self.here
        before = here.tree()
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = here.tree()
        self.assertEqual(after.get(STATE), home.tree()[STATE])
        self.assertNotIn(GONE, after)
        for path in RUNS:
            self.assertNotIn(path, after)
        self.assertEqual({path: after.get(path) for path in (SERVER, *OWN)},
                         {path: before[path] for path in (SERVER, *OWN)})
        # nothing started from the copy: no seat or run, no tick or unit
        self.assertNotEqual(here.tmux("list-sessions").code, 0)
        for tool in ("crontab", "systemctl", "systemd-run"):
            self.assertEqual(here.calls(tool), [], tool)

    def test_a_pass_whose_home_does_not_answer_or_has_no_ak_folder_leaves_the_copy(self):
        home, here = self.home, self.here
        self.addCleanup(home.answer)
        before = here.tree()
        home.silence()
        done = here.ak("standby", home.name)
        self.assertNotEqual(done.code, 0)
        self.assertIn(f"the pass from {home.name} failed", done.err)
        self.assertEqual(here.tree(), before)
        home.answer()
        shutil.rmtree(home.path / ".agentkit")
        done = here.ak("standby", home.name)
        self.assertNotEqual(done.code, 0)
        self.assertIn(f"the pass from {home.name} failed", done.err)
        self.assertIn(f"{here.env['HOME']}/.agentkit", done.err)    # the folder it lacks
        self.assertEqual(here.tree(), before)

    def test_a_machine_not_the_homes_client_is_refused(self):
        home, here = self.home, self.here
        # a client of another home, and the home itself, a client of none
        for machine, alias in ((here, "acme-laptop"), (home, here.name)):
            with self.subTest(alias=alias):
                before = home.tree(), here.tree()
                done = machine.ak("standby", alias)
                self.assertNotEqual(done.code, 0)
                self.assertIn("refused", done.err)
                self.assertIn(alias, done.err)
                self.assertEqual((home.tree(), here.tree()), before)


if __name__ == "__main__":
    unittest.main()
