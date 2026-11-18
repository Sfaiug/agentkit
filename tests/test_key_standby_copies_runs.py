"""`ak standby ALIAS` copies, with ak's folder, every run in ak's runs, each folder there on the
home or here, open or ended, within one pass of each change, but its scratch, a folder named
`tmp…` or `.box-…` at any depth, and a `.git` folder; a `.git` file crosses.  What the home
removed of a run goes from the copy, and so does a run the home removed or only the copy holds;
what the home deleted as a pass met a file vanishing, rsync's exit 24, goes with the next.  A
link here where a run's folder was goes, whatever it points at, and that stays as it was.  A file
beside the runs, a lock, queue or wait of each machine's own, neither crosses nor goes.  A pass
from a home whose runs' folder is a link fails, saying so, before it copies anything.
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

RUNS = ".agentkit/runs/"
REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
# on the home: a run open there, and one that ended there before the copy's first pass
OPEN, ENDED = f"{RUNS}20261116-0900-fix-api/", f"{RUNS}20261020-0900-old-fix/"
RECORDS = {OPEN: {"run_id": "fix-api", "state": "running"},
           ENDED: {"run_id": "old-fix", "state": "pass", "merged": True}}
# in each of them, which crosses but its scratch and the clone's git data
FILES = ("notes.md", "round-1/executor/events.jsonl", "round-1/review-checkout/main.py",
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
class APassCopiesEveryRun(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for folder, record in RECORDS.items():
            home.write(f"{folder}run.json", record)
            for path in (*FILES, *SCRATCH):
                home.write(f"{folder}{path}", f"the home's {folder}{path}")

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def assertCopied(self, folder):
        self.assertEqual(run(self.here, folder), crossing(run(self.home, folder)))

    def test_an_open_run_and_one_ended_before_the_first_pass_cross_but_scratch_and_git(self):
        home, here = self.home, self.here
        self.standby()
        for folder in RECORDS:
            self.assertCopied(folder)
            copy = run(here, folder)
            self.assertTrue(copy[".git"])
            self.assertTrue(copy["round-1/review-checkout/main.py"])
            for path in (*SCRATCH, "round-1/review-checkout/.git/HEAD"):
                self.assertNotIn(path, copy)
                self.assertTrue(run(home, folder)[path])

    def test_a_later_change_in_a_run_open_or_ended_crosses_with_the_next_pass(self):
        home, here = self.home, self.here
        self.standby()
        # the open run ended since, and the other, ended on both machines, changed after its end
        home.write(f"{OPEN}run.json", {**RECORDS[OPEN], "state": "pass"})
        home.write(f"{ENDED}run.json", {**RECORDS[ENDED], "finished_at": 1789000000})
        for folder in RECORDS:
            home.write(f"{folder}round-2/verdict.md", "made after the first pass")
            (home.path / folder / FILES[1]).unlink()
        self.standby()
        for folder in RECORDS:
            self.assertCopied(folder)
            self.assertNotIn(FILES[1], run(here, folder))

    def test_a_run_the_home_removed_or_only_the_copy_holds_goes_from_the_copy(self):
        home, here = self.home, self.here
        only = {f"{RUNS}20261010-0900-own-fix/": "running",
                f"{RUNS}20261010-0930-own-docs/": "stopped"}
        for folder, state in only.items():
            here.write(f"{folder}run.json", {"run_id": folder, "state": state})
            for path in (*FILES[:-1], *SCRATCH):
                here.write(f"{folder}{path}", "this machine's")
        self.standby()
        for folder in (*only, *RECORDS):
            self.assertEqual(os.path.lexists(here.path / folder), folder in RECORDS, folder)
        for folder in RECORDS:
            shutil.rmtree(home.path / folder)
        self.standby()
        for folder in RECORDS:
            self.assertFalse(os.path.lexists(here.path / folder))

    def test_what_the_home_deleted_as_a_pass_met_a_file_vanishing_goes_with_the_next(self):
        home, here = self.home, self.here
        # rsync's own word for a file gone between its listing and its sending, which it leaves
        # here: as the file the home deletes after the pass was during it
        vanishing = here.fake("rsync", f'#!/bin/sh\n{REAL} "$@" || exit; exit 24\n')
        self.standby()
        for folder in RECORDS:
            (home.path / folder / FILES[0]).unlink()
        vanishing.unlink()
        self.standby()
        for folder in RECORDS:
            self.assertCopied(folder)
            self.assertNotIn(FILES[0], run(here, folder))

    def test_a_link_here_where_a_runs_folder_was_goes_and_what_it_points_at_stays(self):
        home, here = self.home, self.here
        here.write(f"{OWN}run.json", {"run_id": "acme", "state": "running"})
        here.write(f"{OWN}notes.md", "this machine's own")
        own = run(here, OWN)
        self.standby()
        # at a run the home lacks, to a folder, and at each it has, to a folder, a file or nothing
        gone = f"{RUNS}20261010-0900-own-fix"
        (here.path / gone).symlink_to(f"{here.env['HOME']}/{OWN}")    # as it names it
        for folder in RECORDS:
            for to in (OWN, f"{OWN}notes.md", f"{OWN}missing"):
                with self.subTest(folder=folder, to=to):
                    shutil.rmtree(here.path / folder)
                    (here.path / folder.rstrip("/")).symlink_to(f"{here.env['HOME']}/{to}")
                    home.write(f"{folder}notes.md", f"the home's, changed for {to}")
                    self.standby()
                    self.assertEqual(run(here, OWN), own)
                    self.assertCopied(folder)
                    self.assertFalse((here.path / folder.rstrip("/")).is_symlink())
        self.assertFalse(os.path.lexists(here.path / gone))

    def test_a_file_beside_the_runs_stays_each_machines_own(self):
        home, here = self.home, self.here
        # a slot's lock and queue here, the queue on the home too, and a landing's wait there alone
        here.write(f"{RUNS}.slots.lock", "")
        here.write(f"{RUNS}.slots.queue", {"queue": ["fix-cli"], "running": 1})
        home.write(f"{RUNS}.slots.queue", {"queue": [], "running": 0})
        home.write(f"{RUNS}.landing-wait-1-2-3", {"run_id": "fix-api"})

        def own():
            """Each file beside the runs here, by its name, with its bytes and its inode, which a
            lock held on it needs to stay."""
            return {path.name: (path.read_bytes(), path.stat().st_ino)
                    for path in (here.path / RUNS).iterdir() if path.is_file()}
        before = own()
        self.standby()
        self.assertEqual(own(), before)
        for folder in RECORDS:
            self.assertCopied(folder)

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
