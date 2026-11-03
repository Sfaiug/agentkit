"""`ak run gc --dry-run` names each run, checkout, log and job the collector would take, one line
each, and keeps the ones still owed to somebody, changing nothing.

A merged run's checkout goes, whatever it holds; a smoke sandbox a day after it was last touched;
a gone job's loop is stopped once nothing was written for a month; then, run by run in name
order, a throwaway repo's run a week after it ended, an ended run's checkout a week after it
failed, a merged run's log is compressed, a run ended a month ago goes whole; and a finished job
a week after it ended.  A run still going, one younger than its age, one whose seat lives, and an
unmerged branch's checkout stay.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.  The dry run gets a /tmp of
its own (`boxed`): the host's is no part of what a Home holds.
"""

import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home, owner

DAY = 86400
NONE = "gc: no eligible artifacts\n"


def git(home, *args):
    done = home.run("git", *args)
    assert done.code == 0, done.err
    return done.out


def repository(home):
    """~/code/acme, a repository with one commit, made the first time it is asked for."""
    repo = home.path / "code" / "acme"
    if not repo.exists():
        repo.mkdir(parents=True)
        git(home, "-C", str(repo), "init", "-q")
        git(home, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "start")
    return repo


def checkout(home, run_id):
    """The run's own checkout, ~/.agentkit/wt/<id>, on its branch `ak/<id>`."""
    wt = home.path / ".agentkit" / "wt" / run_id
    git(home, "-C", str(repository(home)), "worktree", "add", "-q", "-b", f"ak/{run_id}", str(wt))
    return wt


def run(home, run_id, days, **fields):
    """A run of ~/code/acme ended `days` back, its record as old; a None field is left out."""
    ended = time.time() - days * DAY
    record = {"run_id": run_id, "repo": str(repository(home)), "started_at": ended - 600,
              "finished_at": ended, **fields}
    home.write(f".agentkit/runs/{run_id}/run.json",
               {key: value for key, value in record.items() if value is not None}, ago=days * DAY)
    return home.path / ".agentkit" / "runs" / run_id


def planted(home):
    """One of each kind the dry run names for runs and jobs, and its line, in the order printed:
    the sweep's merged checkouts and sandboxes, then the collector's gone jobs, its runs by
    name, and its finished jobs."""
    agentkit = home.path / ".agentkit"
    merged = checkout(home, "acme-merged")
    run(home, "acme-merged", 1, state="pass", merged=True, worktree=str(merged))
    sandbox = agentkit / "tmp" / "smoke-acme"
    sandbox.mkdir(parents=True)
    os.utime(sandbox, (time.time() - 2 * DAY,) * 2)
    gone = home.write(".agentkit/jobs/acme-gone/job.json",
                      {"tasks": [{"run_id": "acme-gone-1", "state": "running"}]},
                      ago=31 * DAY).parent
    ended = checkout(home, "acme-ended")
    run(home, "acme-ended", 8, state="fail", worktree=str(ended))
    # merged, its checkout already gone: its log is what is left to take
    logged = run(home, "acme-merged-log", 1, state="pass", merged=True,
                 worktree=str(agentkit / "wt" / "acme-merged-log"))
    log = home.write(".agentkit/runs/acme-merged-log/log.txt", "round 1: PASS\n", ago=DAY)
    old = run(home, "acme-old", 31, state="pass")
    throwaway = run(home, "acme-throwaway", 8, state="pass",
                    repo=str(agentkit / "tmp" / "acme-suite"))
    done = home.write(".agentkit/jobs/acme-done/job.json",
                      {"tasks": [{"run_id": "acme-done-1", "state": "merged"}],
                       "finished_at": time.time() - 8 * DAY}, ago=8 * DAY).parent
    assert logged == log.parent
    return {
        "merged worktree": f"gc: would remove merged-worktree {merged}",
        "smoke sandbox": f"gc: would remove smoke-sandbox {sandbox}",
        "gone job": f"gc: would stop gone-job {gone}: the job's launcher gone and nothing "
                    "written for 30 days",
        "ended worktree": f"gc: would remove ended-worktree {ended}",
        "merged log": f"gc: would compress merged-log {log}",
        "old run": f"gc: would remove old-run {old}",
        "throwaway run": f"gc: would remove throwaway-run {throwaway}",
        "finished job": f"gc: would remove finished-job {done}",
    }


def dry_run(home):
    # a full disk shortens retention to a day: the ages here are those of a disk with room
    done = home.ak("run", "gc", "--dry-run", boxed=True, env={"AGENTKIT_GC_DISK_PERCENT": "100"})
    assert done.code == 0, done.err
    return done.out


@unittest.skipUnless(boxable(), "no bwrap able to give the dry run a /tmp of its own")
class Taken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.lines = planted(cls.home)
        cls.out = dry_run(cls.home).splitlines()

    def test_each_kind_is_named_on_a_line_of_its_own(self):
        for kind, line in self.lines.items():
            with self.subTest(kind):
                self.assertIn(line, self.out)

    def test_the_lines_come_in_the_collectors_order_and_nothing_else_is_named(self):
        self.assertEqual(self.out, list(self.lines.values()))


@unittest.skipUnless(boxable(), "no bwrap able to give the dry run a /tmp of its own")
class Kept(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_a_run_still_going_stays_however_long_ago_it_started(self):
        run(self.home, "acme-going", 40, state="running", finished_at=None,
            **owner(os.getpid()))
        self.assertEqual(dry_run(self.home), NONE)

    def test_a_run_younger_than_its_age_stays(self):
        run(self.home, "acme-old", 29, state="pass")
        run(self.home, "acme-throwaway", 6, state="pass",
            repo=str(self.home.path / ".agentkit" / "tmp" / "acme-suite"))
        run(self.home, "acme-ended", 6, state="fail",
            worktree=str(checkout(self.home, "acme-ended")))
        self.assertEqual(dry_run(self.home), NONE)

    def test_a_run_whose_seat_lives_stays_however_old(self):
        run(self.home, "acme-seat", 31, state="pass", launched_session="acme")
        self.home.write(".agentkit/state/session-acme.json", {"orchestrator": "opus"})
        self.assertEqual(dry_run(self.home), NONE)

    def test_an_unmerged_branchs_checkout_stays(self):
        run(self.home, "acme-open", 1, state="pass",
            worktree=str(checkout(self.home, "acme-open")))
        self.assertEqual(dry_run(self.home), NONE)


@unittest.skipUnless(boxable(), "no bwrap able to give the dry run a /tmp of its own")
class Still(unittest.TestCase):
    def test_a_dry_run_leaves_every_file_and_branch_it_saw(self):
        with Home() as home:
            planted(home)
            repo = home.path / "code" / "acme"
            branches = ("-C", str(repo), "for-each-ref", "--format=%(refname)", "refs/heads")
            before, refs = home.tree(), git(home, *branches)
            self.assertNotEqual(dry_run(home), NONE)
            self.assertEqual(home.tree(), before)
            self.assertEqual(git(home, *branches), refs)


class Usage(unittest.TestCase):
    def test_an_unknown_flag_is_refused_with_the_usage_line(self):
        with Home() as home:
            done = home.ak("run", "gc", "--bogus")
            self.assertEqual((done.code, done.out, done.err),
                             (2, "", "ak run: usage: ak run gc [--dry-run]\n"))


if __name__ == "__main__":
    unittest.main()
