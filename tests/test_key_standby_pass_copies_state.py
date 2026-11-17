"""`ak standby ALIAS`, run on a client of ALIAS, makes one pass of this machine's copy of ak's
folder on that home, at the same path: what the home deleted goes here too, and a run ended on
both machines stays as it was here; a file rewritten at the same size within a second crosses
too, and a file the home deletes mid-pass fails no pass.  This machine's record of its server, ak's tmp folder, its ak install and ak's repository
stay as they were, and nothing starts from the copy: the crontab holds the standby's own job
alone.  A pass whose home does not answer, or has no ak folder, leaves the copy as it was, says
why and exits non-zero; a machine not ALIAS's client is refused, saying so, as is one where a
link is at what it keeps or above it in ak's folder, which a pass would replace or go past.  None
of those renames the copy's config key by its old name, as other commands do.  Black-box,
through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

STATE = ".agentkit/state/watch.json"     # the home's, which a pass copies
REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
WRITTEN = 1_800_000_000_100_000_000     # when, in nanoseconds: a tenth into its second
GONE = ".agentkit/tasks/fix-api.md"      # copied by an earlier pass, since deleted on the home
# a run ended on both machines, which no pass copies
RUNS = (".agentkit/runs/r-fix-api/run.json", ".agentkit/runs/r-fix-api/round-1/main.py")
ENDED = {"run_id": "r-fix-api", "state": "pass"}
SERVER = ".agentkit/state/server"     # this machine's, which the home has none of
# this machine's own, which the home holds its own of: ak's tmp folder, its ak install, ak's
# repository and a version of ak
OWN = (".agentkit/tmp/watch.log", "agentkit/notes", ".agentkit/agentkit.git/HEAD",
       ".agentkit/versions/1e05b19/bin/ak")


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesAksFolder(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        config = here.path / ".agentkit/config.toml"
        config.write_text(f"rounds = 3\n{config.read_text()}")    # review_rounds' old name
        for path in (STATE, *RUNS, *OWN):
            home.write(path, f"the home's {path}")
        home.write(RUNS[0], {**ENDED, "merged": True})
        os.utime(home.path / STATE, ns=(WRITTEN, WRITTEN))
        for path in (GONE, *OWN):
            here.write(path, f"this machine's {path}")
        here.write(RUNS[0], ENDED)

    def test_a_pass_copies_aks_folder_but_a_run_ended_on_both_and_keeps_this_machines_own(self):
        home, here = self.home, self.here
        before = here.tree()
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = here.tree()
        self.assertEqual(after.get(STATE), home.tree()[STATE])
        self.assertNotIn(GONE, after)
        self.assertEqual({path: after.get(path) for path in (SERVER, *OWN, *RUNS)},
                         {path: before.get(path) for path in (SERVER, *OWN, *RUNS)})
        # nothing started from the copy: no seat or run, no unit, and no tick beside the job
        self.assertNotEqual(here.tmux("list-sessions").code, 0)
        for tool in ("systemctl", "systemd-run"):
            self.assertEqual(here.calls(tool), [], tool)
        self.assertEqual(len((here.root / "crontab").read_text().splitlines()), 1)
        # rewritten at the same size, a hundredth of a second later
        home.write(STATE, f"the home's {STATE}".upper())
        os.utime(home.path / STATE, ns=(WRITTEN + 10**7, WRITTEN + 10**7))
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(here.tree()[STATE], home.tree()[STATE])

    def test_a_file_the_home_deletes_mid_pass_fails_no_pass(self):
        home, here = self.home, self.here
        # rsync's own word for a file gone between its listing and its sending
        here.fake("rsync", f'#!/bin/sh\n{REAL} "$@" || exit; exit 24\n')
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(here.tree().get(STATE), home.tree()[STATE])
        self.assertEqual(here.ak("standby").code, 0)    # it stamped: the copy has an age

    def test_a_pass_whose_home_does_not_answer_or_has_no_ak_folder_leaves_the_copy(self):
        home, here = self.home, self.here
        self.addCleanup(home.answer)
        before = here.copy()
        home.silence()
        done = here.ak("standby", home.name)
        self.assertNotEqual(done.code, 0)
        self.assertIn(f"the pass from {home.name} failed", done.err)
        self.assertEqual(here.copy(), before)
        home.answer()
        shutil.rmtree(home.path / ".agentkit")
        done = here.ak("standby", home.name)
        self.assertNotEqual(done.code, 0)
        self.assertIn(f"the pass from {home.name} failed", done.err)
        self.assertIn(f"{here.env['HOME']}/.agentkit", done.err)    # the folder it lacks
        self.assertEqual(here.copy(), before)

    def test_a_machine_not_the_homes_client_or_with_a_link_where_it_keeps_its_own_is_refused(self):
        home, here = self.home, self.here
        ak = here.path / ".agentkit"

        def link(name, to):
            """Move `name` in ak's folder to `to`, from there, leaving a link to it in its place."""
            (ak / name).rename(ak / to)
            (ak / name).symlink_to(to)
        # a client of another home and the home itself, a client of none; then this machine with
        # the folder of its server's record a link, and ak's tmp folder one into ak's folder
        for machine, alias, layout, said in (
                (here, "acme-laptop", None, "acme-laptop"), (home, here.name, None, here.name),
                (here, home.name, ("state", "../state-aside"), "~/.agentkit/state"),
                (here, home.name, ("tmp", "tmp-aside"), "~/.agentkit/tmp")):
            with self.subTest(alias=alias, layout=layout):
                if layout:
                    link(*layout)
                before = home.tree(), here.tree()
                done = machine.ak("standby", alias)
                self.assertNotEqual(done.code, 0)
                self.assertIn("refused", done.err)
                self.assertIn(said, done.err)
                self.assertEqual((home.tree(), here.tree()), before)


if __name__ == "__main__":
    unittest.main()
