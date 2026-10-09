"""The tick writes down which live runs of a repository change the same lines.

A run's lease is its own diff, uncommitted edits included; no model declares anything.  Two
live runs whose trees cannot be merged over the base they share are a collision, written on
the younger as waiting on the older with the paths and since when; runs changing different
lines of the same file are none.  A record outlives neither the collision nor the holder's
run.  Offline: a real repository with one checkout per run, run records in a throwaway HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, leases, watch
from agentkit import record


class LeaseScan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-lease-scan-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "TMP", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git(self.repo, "init", "-qb", "main")
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "api.py").write_text("".join(f"line {n}\n" for n in range(1, 21)))
        (self.repo / "other.py").write_text("other\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Base")
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.logs = []

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def run_on(self, name, started, state="running", base=None):
        """A live run of the repository with a checkout of its own, cut from `base`."""
        worktree = config.WT / name
        self.git(self.repo, "worktree", "add", "-q", "-b", f"ak/{name}", str(worktree), base or self.base)
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        record.save_state(directory, {"run_id": name, "state": state, "repo": str(self.repo),
                                      "worktree": str(worktree), "base_sha": base or self.base,
                                      "started_at": started})
        return worktree

    def edit(self, worktree, path, line, text, commit=False):
        lines = (worktree / path).read_text().splitlines()
        lines[line - 1] = text
        (worktree / path).write_text("".join(f"{each}\n" for each in lines))
        if commit:
            self.git(worktree, "commit", "-qam", f"edit {path}:{line}")

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
                      "lines of api.py; the younger would wait", self.logs[-1])
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
