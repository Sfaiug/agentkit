"""The tick writes down which live runs of a repository change the same lines.

A run's lease is its own diff, uncommitted edits included; no model declares anything.  Two
live runs whose trees cannot be merged over the base they share are a collision, written on
the younger as waiting on the older with the paths and since when; runs changing different
lines of the same file are none.  A record outlives neither the collision nor the holder's
run.  Offline: the lease stage (`fixtures.leases`), a real repository with one checkout per run.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import LiveRuns
from agentkit import config, gitcall, leases, run, watch
from agentkit import record


class LeaseScan(LiveRuns):
    def test_runs_on_the_same_lines_collide_and_the_younger_waits(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 15, "younger's line 15")       # uncommitted: it counts too
        self.assertEqual(leases.scan(self.repo, self.logs.append, now=2000), {})
        self.assertEqual(self.logs, [])
        self.edit(younger, "api.py", 5, "younger's line 5")
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found, {"20260101-1000-younger": {
            "waits_on": "20260101-0900-older", "files": ["api.py"], "since": 2000}})
        self.assertEqual(leases.read(self.repo), found)
        self.assertIn("collision: 20260101-1000-younger and 20260101-0900-older change the same "
                      "lines of api.py; the younger is only written down", self.logs[-1])
        # the record keeps its first sighting while the pair stands, and nothing in either
        # checkout was touched by the scan
        self.assertEqual(leases.scan(self.repo, now=2300)["20260101-1000-younger"]["since"], 2000)
        self.assertEqual(self.git(younger, "status", "--porcelain"), "M api.py")    # unstaged still
        self.assertEqual(self.git(older, "status", "--porcelain"), "")

    def test_a_record_outlives_neither_the_collision_nor_the_holder(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertIn("20260101-1000-younger", leases.scan(self.repo, now=2000))
        self.edit(younger, "api.py", 5, "line 5")               # the younger backs off
        self.assertEqual(leases.scan(self.repo, now=2100), {})
        self.assertEqual(leases.read(self.repo), {})
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertIn("20260101-1000-younger", leases.scan(self.repo, now=2200))
        directory = config.RUNS / "20260101-0900-older"
        record.save_state(directory, {**record.read_state(directory), "state": "pass"})   # the holder ended
        self.assertEqual(leases.scan(self.repo, now=2300), {})

    def test_the_oldest_holder_is_the_one_waited_on_and_bases_may_differ(self):
        first = self.run_on("20260101-0800-first", 800)
        self.edit(first, "api.py", 5, "first's line 5", commit=True)
        # main moved meanwhile: a later run is cut from the newer base
        self.edit(self.repo, "other.py", 1, "moved on", commit=True)
        moved = self.git(self.repo, "rev-parse", "HEAD")
        second = self.run_on("20260101-0900-second", 900, base=moved)
        third = self.run_on("20260101-1000-third", 1000, base=moved)
        self.edit(second, "api.py", 5, "second's line 5", commit=True)
        self.edit(third, "api.py", 5, "third's line 5")
        found = leases.scan(self.repo, now=2000)
        self.assertEqual({name: each["waits_on"] for name, each in found.items()},
                         {"20260101-0900-second": "20260101-0800-first",
                          "20260101-1000-third": "20260101-0800-first"})

    def clash_with_main(self):
        """A run behind main clashing with it in two files, and runs on the newer base."""
        first = self.run_on("20260101-0800-first", 800)
        self.edit(first, "other.py", 1, "first's other", commit=True)   # what main then changes too
        self.edit(first, "api.py", 1, "first's line 1", commit=True)     # ... and this
        self.edit(self.repo, "other.py", 1, "main moved on", commit=True)
        self.edit(self.repo, "api.py", 1, "main's line 1", commit=True)
        moved = self.git(self.repo, "rev-parse", "HEAD")
        second = self.run_on("20260101-0900-second", 900, base=moved)
        self.edit(second, "api.py", 15, "second's line 15")
        # the first run conflicts with main, not with the second, which changed none of it;
        # and main's own change to api.py:1 is not the second run's diff either
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        # ... yet the rest of its diff is still compared, in the clashing file too: a line
        # both change is a collision
        self.edit(first, "api.py", 15, "first's line 15", commit=True)
        self.assertEqual(leases.scan(self.repo, now=2050)["20260101-0900-second"],
                         {"waits_on": "20260101-0800-first", "files": ["api.py"], "since": 2050})
        third = self.run_on("20260101-1000-third", 1000)                 # cut from the old base
        self.edit(third, "api.py", 15, "third's line 15")
        self.assertEqual(leases.scan(self.repo, now=2100)["20260101-1000-third"]["waits_on"],
                         "20260101-0800-first")

    def test_mains_own_movement_between_two_bases_is_nobodys_diff(self):
        self.clash_with_main()

    def test_the_scan_asks_nothing_of_a_git_newer_than_ak_checks_for(self):
        """`merge-tree -X` is git 2.43's: the hunks main's side wins at are settled by `git
        merge-file`, which the 2.39 ak checks for has."""
        shim = self.root / "shim"
        shim.mkdir()
        (shim / "git").write_text("#!/bin/sh\nfor arg in \"$@\"; do\n  [ \"$arg\" = -X ] && "
                                  "{ echo \"error: unknown switch 'X'\" >&2; exit 129; }\ndone\n"
                                  f"exec {shutil.which('git')} \"$@\"\n")
        (shim / "git").chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}):
            self.clash_with_main()

    def test_only_a_pair_git_has_something_to_decide_on_is_merged(self):
        (self.repo / "pkg" / "sub").mkdir(parents=True)
        for name in ("a.py", "b.py"):
            (self.repo / "pkg" / "sub" / name).write_text(f"{name}\n" * 9)
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "A package")
        base = self.git(self.repo, "rev-parse", "HEAD")
        older = self.run_on("20260101-0900-older", 900, base=base)
        younger = self.run_on("20260101-1000-younger", 1000, base=base)
        self.edit(older, "api.py", 5, "older's line 5")
        self.edit(younger, "other.py", 1, "younger's line")
        with patch.object(leases, "merged", wraps=leases.merged) as merge:
            self.assertEqual(leases.scan(self.repo, now=2000), {})
        merge.assert_not_called()
        # no path in common, yet git's own conflicts: a directory moved, its files a level down,
        # under a file added to it,
        self.git(older, "mv", "pkg", "moved")
        (younger / "pkg" / "new.py").write_text("new\n")
        self.assertEqual(leases.scan(self.repo, now=2100)["20260101-1000-younger"]["files"],
                         ["moved/new.py"])
        # a file where the other has a directory,
        self.git(older, "mv", "moved", "pkg")
        (younger / "pkg" / "new.py").unlink()
        (older / "shared").write_text("a file\n")
        (younger / "shared").mkdir()
        (younger / "shared" / "x.py").write_text("x\n")
        self.assertIn("shared", " ".join(leases.scan(self.repo, now=2200)["20260101-1000-younger"]["files"]))
        # a run behind main moving a directory main added to, the addition taken along to where
        # the other adds it,
        (younger / "shared" / "x.py").unlink()
        (older / "shared").unlink()
        self.edit(older, "api.py", 5, "line 5")
        self.edit(younger, "other.py", 1, "other")
        self.git(older, "mv", "pkg", "moved")
        (self.repo / "pkg" / "f.py").write_text("main's\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Added")
        added = self.run_on("20260101-1050-added", 1050, base=self.git(self.repo, "rev-parse", "HEAD"))
        (added / "moved").mkdir()
        (added / "moved" / "f.py").write_text("its own\n")
        self.assertEqual(leases.scan(self.repo, now=2250)["20260101-1050-added"]["files"],
                         ["moved/f.py"])
        self.git(older, "mv", "moved", "pkg")
        shutil.rmtree(added / "moved")
        # and a run behind renames on main, more than a diff's rename limit takes, its edit
        # followed to a line the other changes
        self.git(self.repo, "config", "diff.renameLimit", "1")
        self.git(self.repo, "config", "merge.renameLimit", "100")
        self.git(self.repo, "mv", "api.py", "renamed.py")
        self.git(self.repo, "mv", "pkg/sub/b.py", "pkg/sub/c.py")
        self.edit(self.repo, "renamed.py", 30, "main's line 30")
        self.edit(self.repo, "pkg/sub/c.py", 9, "main's line 9")
        self.git(self.repo, "commit", "-qam", "Renamed")
        moved = self.git(self.repo, "rev-parse", "HEAD")
        third = self.run_on("20260101-1100-third", 1100, base=moved)
        self.edit(older, "api.py", 5, "older's line 5")
        self.edit(third, "renamed.py", 5, "third's line 5")
        self.assertEqual(leases.scan(self.repo, now=2300)["20260101-1100-third"]["waits_on"],
                         "20260101-0900-older")

    def tree_with_other_unreadable(self, checkout):
        """The checkout's `leases.tree`, other.py, unchanged, unreadable once the checkout's
        own index holds its stat data: a scan reading it says so."""
        self.git(checkout, "config", "core.trustctime", "false")   # the chmod changes its ctime alone
        os.utime(checkout / "other.py", (1, 1))
        self.git(checkout, "status")
        (checkout / "other.py").chmod(0)
        self.addCleanup((checkout / "other.py").chmod, 0o644)
        tree = leases.tree(checkout, (), self.logs.append)
        self.assertEqual(self.logs, [])
        return tree

    def test_a_scan_reads_no_file_the_checkouts_own_index_knows_is_unchanged(self):
        checkout = self.run_on("20260101-0900-older", 900)
        self.assertEqual(self.tree_with_other_unreadable(checkout),
                         self.git(checkout, "rev-parse", "HEAD^{tree}"))

    def test_nor_while_a_merge_leaves_another_file_unmerged(self):
        checkout = self.run_on("20260101-0900-older", 900)
        self.edit(checkout, "api.py", 5, "older's line 5", commit=True)
        self.edit(self.repo, "api.py", 5, "main's line 5", commit=True)
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(checkout, "merge", "-q", "main")
        tree = self.tree_with_other_unreadable(checkout)
        self.assertIn("main's line 5", self.git(checkout, "show", f"{tree}:api.py"))

    def test_an_edit_the_index_cannot_tell_by_its_stat_data_is_read_while_git_replaces_it(self):
        checkout = self.run_on("20260101-0900-older", 900)
        self.git(checkout, "config", "core.trustctime", "false")
        api = checkout / "api.py"
        os.utime(api, (1, 1))
        self.git(checkout, "status")
        index = checkout / self.git(checkout, "rev-parse", "--git-path", "index")
        os.utime(index, (1, 1))     # written the second api.py was: git hashes it to be sure
        api.write_text(api.read_text().replace("line 5", "LINE 5"))     # its size and stat kept
        os.utime(api, (1, 1))
        opened, replaced = open, []

        def replaced_once_open(path, *args, **kwargs):
            file = opened(path, *args, **kwargs)
            if path == index and not replaced:      # another git adds, renaming a new index in
                replaced.append(path)
                (checkout / "other.py").write_text("changed\n")
                self.git(checkout, "add", "other.py")
            return file
        with patch("builtins.open", replaced_once_open):
            tree = leases.tree(checkout, (), self.logs.append)
        self.assertEqual(replaced, [index])
        self.assertIn("LINE 5", self.git(checkout, "show", f"{tree}:api.py"))

    def test_a_run_launched_from_a_linked_worktree_is_of_the_repository_it_was_added_from(self):
        seat = self.root / "seat-checkout"
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(seat), "main")
        older = self.run_on("20260101-0900-older", 900, repo=seat)      # recorded from the seat's checkout
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        found = leases.scan(seat, now=2000)                              # scanned by either path ...
        self.assertEqual(found["20260101-1000-younger"]["waits_on"], "20260101-0900-older")
        self.assertEqual(leases.read(self.repo), found)                 # ... into the one record
        scanned = []
        with patch.object(leases, "scan", side_effect=lambda repo, log, now: scanned.append(repo)):
            leases.scan_all()
        self.assertEqual(len(scanned), 1)

    def test_the_scan_takes_no_checkouts_index_lock(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.git(younger, "status", "--porcelain")                     # its index fresh
        found = self.git(younger, "rev-parse", "--git-path", "index")
        index = Path(found) if Path(found).is_absolute() else younger / found
        time.sleep(1.1)                                                 # a later second, as any real save
        (younger / "other.py").write_text((younger / "other.py").read_text())   # rewritten unchanged, as a formatter does
        self.edit(younger, "api.py", 5, "younger's line 5")
        before = (index.stat().st_mtime_ns, index.read_bytes())
        self.assertIn("20260101-1000-younger", leases.scan(self.repo, now=2000))
        self.assertEqual((index.stat().st_mtime_ns, index.read_bytes()), before)

    def test_a_name_git_would_quote_is_read_raw(self):
        (self.repo / "café.py").write_text("".join(f"line {n}\n" for n in range(1, 6)))
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "A name git quotes")
        start = self.git(self.repo, "rev-parse", "HEAD")
        first = self.run_on("20260101-0800-first", 800, base=start)
        self.edit(first, "café.py", 1, "first's line 1", commit=True)
        self.edit(self.repo, "café.py", 1, "main's line 1", commit=True)     # the clash with main
        moved = self.git(self.repo, "rev-parse", "HEAD")
        second = self.run_on("20260101-0900-second", 900, base=moved)
        self.edit(second, "café.py", 5, "second's line 5")
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        self.edit(first, "café.py", 5, "first's line 5", commit=True)
        self.assertEqual(leases.scan(self.repo, now=2100)["20260101-0900-second"]["files"], ["café.py"])

    def test_what_the_checks_generated_is_no_lease(self):
        older = self.run_on("20260101-0900-older", 900, artifacts=["checks.log"])
        younger = self.run_on("20260101-1000-younger", 1000, artifacts=["checks.log"])
        for worktree in (older, younger):
            (worktree / "checks.log").write_text(f"checks ran in {worktree}\n")   # un-ignored, uncommitted
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "other.py", 1, "younger's other")
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        # ... and a loop writes them down as it writes anything
        directory = config.RUNS / "20260101-1100-loop"
        directory.mkdir()
        state = {"run_id": directory.name, "title": "Loop", "state": "running", "repo": str(self.repo),
                 "worktree": str(younger), "base": "main", "base_sha": self.base,
                 "branch": "ak/20260101-1000-younger", "rounds": 3, "executor": "opus",
                 "reviewer": "astra", "round_summaries": []}
        record.save_state(directory, state)
        lp = run.Loop(config.load(), directory, state, {}, lambda _: None, younger, "# Fixture",
                      ["true"], "context")
        lp.artifacts.add("checks.log")
        lp.write()
        self.assertEqual(record.read_state(directory)["artifacts"], ["checks.log"])

    def test_an_uncommitted_deletion_is_the_runs_lease_too(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "other.py", 1, "older's other", commit=True)
        (younger / "other.py").unlink()                 # deleted, uncommitted: a commit would take it
        self.assertEqual(leases.scan(self.repo, now=2000)["20260101-1000-younger"]["files"], ["other.py"])

    def test_a_file_that_vanishes_between_listing_and_adding_costs_only_itself(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertEqual(leases.scan(self.repo, self.logs.append, now=2000)["20260101-1000-younger"]["since"], 2000)
        listed = gitcall.committable_paths

        def with_a_temp_file_gone(worktree, artifacts=(), env=None):
            real, junk = listed(worktree, artifacts, env=env)
            return real + ["gone.tmp"], junk          # written and removed under the scan's feet

        with patch.object(gitcall, "committable_paths", side_effect=with_a_temp_file_gone), \
                patch.dict(os.environ, {"LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"}):   # git's words in any language
            found = leases.scan(self.repo, self.logs.append, now=2100)
        self.assertEqual(found["20260101-1000-younger"], {"waits_on": "20260101-0900-older",
                                                           "files": ["api.py"], "since": 2000})
        self.assertFalse(any("WARN" in line for line in self.logs), self.logs)

    def test_paths_a_commit_would_leave_are_no_lease_and_an_unchanged_pair_writes_nothing(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        for worktree in (older, younger):
            (worktree / "venv").mkdir()
            (worktree / "venv" / "pyvenv.cfg").write_text(f"home = {worktree}\n")
            (worktree / ".ak-test-x").mkdir()
            (worktree / ".ak-test-x" / "junk").write_text("junk\n")
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertIn("20260101-1000-younger", leases.scan(self.repo, now=2100))
        objects = lambda: self.git(self.repo, "count-objects", "-v").splitlines()[0]
        before = objects()
        self.assertIn("20260101-1000-younger", leases.scan(self.repo, now=2200))
        self.assertEqual(objects(), before)                 # the same trees, the same commits

    def test_runs_cut_from_bases_that_never_met_collide_with_nobody(self):
        self.git(self.repo, "checkout", "-qb", "feature")
        self.edit(self.repo, "api.py", 5, "the feature's line 5", commit=True)
        feature = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "checkout", "-q", "main")
        self.edit(self.repo, "api.py", 5, "main's line 5", commit=True)
        moved = self.git(self.repo, "rev-parse", "HEAD")
        self.run_on("20260101-0800-feature", 800, base=feature)        # changes nothing ...
        self.run_on("20260101-0900-main", 900, base=moved)             # ... and neither does this
        self.assertEqual(leases.scan(self.repo, now=2000), {})

    def test_an_unreadable_file_in_one_checkout_costs_no_pair_its_record(self):
        older = self.run_on("20260101-0900-older", 900)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        (younger / "secret.txt").write_text("unreadable\n")
        (younger / "secret.txt").chmod(0)
        self.addCleanup((younger / "secret.txt").chmod, 0o600)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found["20260101-1000-younger"]["files"], ["api.py"])
        self.assertTrue(any("left unreadable paths" in line for line in self.logs), self.logs)

    def test_only_going_runs_with_a_checkout_of_their_own_count(self):
        gone = self.run_on("20260101-0900-gone", 900, state="fail")
        self.edit(gone, "api.py", 5, "gone's line 5", commit=True)
        younger = self.run_on("20260101-1000-younger", 1000)
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        # a run in the repository itself holds no diff of its own
        directory = config.RUNS / "20260101-0950-here"
        directory.mkdir()
        record.save_state(directory, {"run_id": directory.name, "state": "running",
                                      "repo": str(self.repo), "worktree": str(self.repo),
                                      "base_sha": self.base, "started_at": 950})
        self.assertEqual([each["run"] for each in leases.live(self.repo)], ["20260101-1000-younger"])
        # the tick scans every repository a live run works in, and only those
        other = self.root / "widget"
        other.mkdir()
        self.git(other, "init", "-qb", "main")
        scanned = []
        with patch.object(leases, "scan", side_effect=lambda repo, log, now: scanned.append(Path(repo).name)):
            leases.scan_all(self.logs.append)
        self.assertEqual(scanned, ["acme"])
        self.assertIn("the lease scan did not run", [what for what, _, _ in watch.local_passes({}, True, self.logs.append)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
