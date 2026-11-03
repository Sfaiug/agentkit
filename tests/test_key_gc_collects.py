"""`ak run gc` takes what its dry run names, keeps what that leaves off, and says what it did.

Each run, checkout, log, job and leftover the dry run names (tests/fixtures/garbage.py, whose
lines tests/test_key_gc_plan_*.py pin) is gone after `ak run gc`: a merged log gzipped, a gone
job stopped, a harness's entries pruned, a merged run's branch dropped with its checkout while an
unmerged one's stays.  All it never named, the records of runs whose checkouts went among them,
stays byte for byte.  It prints the plan's line for each, then the sweep's count of merged
checkouts and smoke sandboxes and the space they held; a second collection, and one on a Home
with nothing to take, finds nothing and says so.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.  Each
collection is boxed with a /tmp, a /var/tmp and processes of its own (`Leftovers.ak`), or, beside
a run of the test's own process, a /tmp.
"""

import gzip
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home, owner
from fixtures.garbage import branches, checkout, Leftovers, planted, ROOM, run

NONE = "gc: no eligible artifacts\n"


def outside(leftovers, named):
    """Where a path the box names lies: its /tmp and /var/tmp are folders of the Home."""
    path = Path(named)
    if path.is_relative_to(leftovers.home.root):
        return path
    for inside, there in (("/tmp", leftovers.tmp), ("/var/tmp", leftovers.var)):
        if path.is_relative_to(inside):
            return there / path.relative_to(inside)
    raise AssertionError(f"{named} lies outside the Home and its box")


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class Taken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.plan = list(planted(cls.home).values())
        cls.leftovers = Leftovers(cls.home)
        cls.plan += cls.leftovers.expected
        # a merged checkout goes whatever it holds: a mebibyte never committed is what it frees
        (cls.home.path / ".agentkit/wt/acme-merged/build.bin").write_bytes(os.urandom(1 << 20))
        cls.before = cls.home.tree()
        cls.done = cls.leftovers.ak("run", "gc")
        cls.again = cls.leftovers.ak("run", "gc")

    def test_each_path_it_plans_to_remove_is_gone(self):
        for line in self.plan:
            action, kind, path = line.split()[2:5]
            if action == "remove":
                with self.subTest(kind):
                    self.assertFalse(os.path.lexists(outside(self.leftovers,
                                                             path.removesuffix(":"))))

    def test_what_the_plan_leaves_off_stays_byte_for_byte(self):
        named = [outside(self.leftovers, line.split()[4].removesuffix(":")) for line in self.plan]

        def taken(relative):
            # a named path, what it holds, and its sidecars (a viewer's marker, a log's .gz);
            # the repository's own records change as its checkouts go: its branches are judged
            path = self.home.path / relative
            return relative.startswith("code/") or any(
                path.is_relative_to(name) or path.parent == name.parent
                and path.name.startswith(f"{name.name}.") for name in named)
        kept = {relative: data for relative, data in self.before.items() if not taken(relative)}
        after = self.home.tree()
        self.assertIn(".agentkit/runs/acme-merged/run.json", kept)
        self.assertEqual({relative: after.get(relative, "gone") for relative in kept}, kept)

    def test_a_merged_log_is_gzipped_whole(self):
        log = self.home.path / ".agentkit/runs/acme-merged-log/log.txt"
        self.assertFalse(log.exists())
        self.assertEqual(gzip.decompress(log.with_suffix(".txt.gz").read_bytes()),
                         b"round 1: PASS\n")

    def test_a_gone_job_is_stopped_and_finished(self):
        job = json.loads((self.home.path / ".agentkit/jobs/acme-gone/job.json").read_text())
        self.assertEqual([task["state"] for task in job["tasks"]], ["stopped"])
        self.assertIn("finished_at", job)

    def test_a_harness_keeps_no_entry_naming_a_gone_checkout(self):
        self.assertEqual(json.loads((self.home.path / ".claude.json").read_text()),
                         {"projects": {}})

    def test_a_merged_runs_branch_goes_and_the_unmerged_stay(self):
        self.assertEqual(branches(self.home), ["ak/acme-ended", "ak/passed-fix", "main"])

    def test_it_says_each_removal_as_planned_then_what_the_sweep_freed(self):
        said = [line.replace("gc: would ", "gc: ", 1) for line in self.plan]
        self.assertEqual(self.done.out.splitlines(), [
            *said, "gc: removed 1 merged worktree and 1 smoke sandbox, 1.0 MB freed"])
        self.assertEqual((self.done.code, self.done.err), (0, ""))

    def test_a_second_collection_finds_nothing(self):
        self.assertEqual(self.again, (0, NONE, ""))


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class Kept(unittest.TestCase):
    def test_what_the_plan_leaves_off_stays_as_it_was(self):
        with Home() as home:
            leftovers = Leftovers(home, kept=True)
            run(home, "acme-old", 29, state="pass")
            run(home, "acme-throwaway", 6, state="pass",
                repo=str(home.path / ".agentkit" / "tmp" / "acme-suite"))
            run(home, "acme-ended", 6, state="fail", worktree=str(checkout(home, "acme-ended")))
            run(home, "acme-seat", 31, state="pass", launched_session="acme")
            home.write(".agentkit/state/session-acme.json", {"orchestrator": "opus"})
            run(home, "acme-open", 1, state="pass", worktree=str(checkout(home, "acme-open")))
            before, refs = leftovers.seen(), branches(home)
            self.assertEqual(leftovers.ak("run", "gc"), (0, NONE, ""))
            self.assertEqual(leftovers.seen(), before)
            self.assertEqual(branches(home), refs)

    def test_a_run_still_going_stays(self):
        with Home() as home:
            run(home, "acme-going", 40, state="running", finished_at=None, **owner(os.getpid()))
            before = home.tree()
            self.assertEqual(home.ak("run", "gc", boxed=True, env=ROOM), (0, NONE, ""))
            self.assertEqual(home.tree(), before)


if __name__ == "__main__":
    unittest.main()
