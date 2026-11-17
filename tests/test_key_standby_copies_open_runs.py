"""`ak standby ALIAS` copies, with ak's folder, each run in ak's runs open on the home or here as
the pass reads their records: one whose folder holds no record that can be read, or one whose state
is not an ended one.  An open run's folder crosses within one pass of each change but its scratch,
a folder named `tmp…` or `.box-…` at any depth, and a `.git` folder; a `.git` file crosses.  A run
that ended on the home since the last pass crosses once more, its ended record with it, and a later
change to it on the home stays uncopied by the passes after; one a pass copied while its rsync
exited 24, for a file the home deleted under it, crosses with each pass after, till one whose
rsync exits 0.  A run ended on both machines before
the first pass never crosses, and one open here that the home no longer has goes.  A link here
where an open run's folder was goes, and what it points at stays as it was.  A pass from a home
whose runs' folder is a link fails, saying so, before it copies anything.  Black-box, through
tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

RUNS = ".agentkit/runs/"
REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
# open on the home: running, with no record yet, and with one that cannot be read, an ended one
# after a BOM, which ak's reader of records refuses as JSON's of bytes would not
OPEN = (f"{RUNS}20261116-0900-fix-api/", f"{RUNS}20261116-0910-add-docs/",
        f"{RUNS}20261116-0920-fix-cli/")
RECORDS = ({"run_id": "fix-api", "state": "running"}, None, '﻿{"state": "pass"}')
# in the first of them, which crosses but its scratch and the clone's git data
FILES = ("round-1/executor/events.jsonl", "round-1/review-checkout/main.py",
         "round-1/review-checkout/.git/HEAD", ".git")
SCRATCH = ("tmpk2j4w8x1/prompt.md", ".box-q7m2/note", "round-1/executor/.box-r3n8/token",
           "round-1/review-checkout/tmpa9/prompt.md")
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well
OWN = "personal/acme-run/"      # this machine's own, outside ak's folder


def run(machine, folder):
    """Each file and folder of the run in `folder` on `machine`, by its path in it, with each
    file's bytes."""
    return {path[len(folder):]: data for path, data in machine.tree().items()
            if path.startswith(folder)}


def crossing(files):
    """`files` of a run but its scratch and each `.git` folder: what a pass copies of it."""
    def crosses(path, data):
        parts = Path(path).parts
        return not (any(part.startswith(("tmp", ".box-")) for part in parts)
                    or ".git" in parts[:-1] or (parts[-1] == ".git" and data is None))
    return {path: data for path, data in files.items() if crosses(path, data)}


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesOpenRuns(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for folder, record in zip(OPEN, RECORDS):
            home.write(f"{folder}notes.md", f"the home's {folder}")
            if record is not None:
                home.write(f"{folder}run.json", record)
        for path in (*FILES, *SCRATCH):
            home.write(f"{OPEN[0]}{path}", f"the home's {path}")

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def assertCopied(self, folder):
        self.assertEqual(run(self.here, folder), crossing(run(self.home, folder)))

    def test_an_open_runs_folder_crosses_within_one_pass_of_each_change_but_scratch_and_git(self):
        home, here = self.home, self.here
        self.standby()
        for folder in OPEN:
            self.assertCopied(folder)
        copy = run(here, OPEN[0])
        self.assertTrue(copy[".git"])
        self.assertTrue(copy["round-1/review-checkout/main.py"])
        for path in (*SCRATCH, "round-1/review-checkout/.git/HEAD"):
            self.assertNotIn(path, copy)
            self.assertTrue(run(home, OPEN[0])[path])
        home.write(f"{OPEN[0]}round-1/executor/events.jsonl", "a later event")
        home.write(f"{OPEN[0]}round-2/plan.md", "made")
        (home.path / OPEN[0] / "notes.md").unlink()
        home.write(f"{OPEN[1]}run.json", {"run_id": "add-docs", "state": "queued"})
        self.standby()
        for folder in OPEN:
            self.assertCopied(folder)

    def test_a_run_ended_on_the_home_crosses_once_more_with_its_record_then_never(self):
        home, here = self.home, self.here
        folder = OPEN[0]
        self.standby()
        home.write(f"{folder}run.json", {"run_id": "fix-api", "state": "pass"})
        home.write(f"{folder}round-1/verdict.md", "passed")
        self.standby()
        self.assertCopied(folder)
        ended = run(here, folder)
        home.write(f"{folder}run.json", {"run_id": "fix-api", "state": "pass", "merged": True})
        home.write(f"{folder}round-1/verdict.md", "passed, and merged")
        home.write(f"{folder}after.md", "made after its end")
        for _ in range(2):
            self.standby()
            self.assertEqual(run(here, folder), ended)

    def test_a_run_a_pass_ended_as_the_home_deleted_a_file_crosses_till_a_pass_meets_none(self):
        home, here = self.home, self.here
        folder = OPEN[0]
        self.standby()
        home.write(f"{folder}run.json", {"run_id": "fix-api", "state": "pass"})
        # rsync's own word for a file gone between its listing and its sending, which it leaves
        # here: as the two files the home deletes after each such pass were during it
        vanishing = here.fake("rsync", f'#!/bin/sh\n{REAL} "$@" || exit; exit 24\n')
        self.standby()
        (home.path / folder / "notes.md").unlink()
        self.standby()
        self.assertCopied(folder)
        (home.path / folder / FILES[0]).unlink()
        vanishing.unlink()
        self.standby()
        self.assertCopied(folder)
        ended = run(here, folder)
        home.write(f"{folder}after.md", "made after its end")
        self.standby()
        self.assertEqual(run(here, folder), ended)

    def test_a_run_ended_on_both_machines_before_the_first_pass_is_not_copied(self):
        home, here = self.home, self.here
        only, both = f"{RUNS}20261020-0900-old-fix/", f"{RUNS}20261020-0930-old-docs/"
        for folder, state in ((only, "pass"), (both, "stopped")):
            home.write(f"{folder}run.json", {"run_id": folder, "state": state, "merged": True})
            home.write(f"{folder}notes.md", "the home's")
        here.write(f"{both}run.json", {"run_id": both, "state": "stopped"})
        here.write(f"{both}notes.md", "this machine's")
        before = run(here, both)
        self.standby()
        self.assertFalse(os.path.lexists(here.path / only))
        self.assertEqual(run(here, both), before)

    def test_a_run_open_here_that_the_home_no_longer_has_goes_from_here(self):
        home, here = self.home, self.here
        gone = f"{RUNS}20261020-0900-old-fix/"
        here.write(f"{gone}run.json", {"run_id": "old-fix", "state": "running"})
        for path in FILES[:-1] + SCRATCH:
            here.write(f"{gone}{path}", "this machine's")
        self.standby()
        self.assertFalse(os.path.lexists(here.path / gone))
        self.assertCopied(OPEN[1])
        shutil.rmtree(home.path / OPEN[1])
        self.standby()
        self.assertFalse(os.path.lexists(here.path / OPEN[1]))

    def test_a_link_here_where_an_open_runs_folder_was_goes_and_what_it_points_at_stays(self):
        home, here = self.home, self.here
        here.write(f"{OWN}run.json", {"run_id": "acme", "state": "running"})
        here.write(f"{OWN}notes.md", "this machine's own")
        own = run(here, OWN)
        self.standby()
        # at a run the home has, and at one it lacks, each open by the record it reaches
        gone = f"{RUNS}20261020-0900-old-fix"
        shutil.rmtree(here.path / OPEN[0])
        for link in (OPEN[0].rstrip("/"), gone):
            (here.path / link).symlink_to(f"{here.env['HOME']}/{OWN}")    # as it names it
        home.write(f"{OPEN[0]}notes.md", "the home's, changed")
        self.standby()
        self.assertEqual(run(here, OWN), own)
        self.assertCopied(OPEN[0])
        self.assertFalse((here.path / OPEN[0].rstrip("/")).is_symlink())
        self.assertFalse(os.path.lexists(here.path / gone))

    def test_a_pass_from_a_home_whose_runs_folder_is_a_link_fails_and_copies_nothing(self):
        home, here = self.home, self.here
        self.standby()
        # the home's runs moved to a folder of its own, linked by the path it has on both machines
        (home.path / OWN).parent.mkdir()
        (home.path / RUNS).rename(home.path / OWN)
        (home.path / RUNS).symlink_to(f"{home.env['HOME']}/{OWN}")
        home.write(f"{OWN}20261116-0900-fix-api/notes.md", "the home's, changed")
        here.write(f"{OWN}20261116-0900-fix-api/run.json", {"run_id": "acme", "state": "running"})
        here.write(f"{OWN}20261116-0900-fix-api/notes.md", "this machine's own")
        before, stamp = here.copy(), (here.path / STAMP).read_bytes()
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"the pass from {home.name} failed: ~/{RUNS.rstrip('/')} is a link", done.err)
        self.assertEqual((here.path / STAMP).read_bytes(), stamp)
        self.assertEqual(here.copy(), before)
        self.assertFalse((here.path / RUNS).is_symlink())
        self.assertTrue((here.path / RUNS).is_dir())


if __name__ == "__main__":
    unittest.main()
