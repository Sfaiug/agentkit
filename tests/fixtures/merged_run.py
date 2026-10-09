"""The stage of a seat's merged run: a throwaway HOME with its state and run records, a merged
run as the merge left its record (`merged`), a checkout whose delivered commit declares what
its AGENTS.md says (`delivered`), and a run of the seat's parked undecided
(`parked_exhausted`).  Offline.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[2]
SEAT = "facts-seat"
SPENT = "three rounds spent: split or re-scope the task"


class MergedRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-merged-run-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)

    def merged(self, name, *, health=True, live=False, age=600, tree=None):
        """A merged run of the seat's, as the merge left its record: the `health:` the
        delivered commit declared, or none; `tree` puts an AGENTS.md in the checkout's working
        tree, which decides nothing."""
        repo = self.home / f"code-{name}"
        repo.mkdir()
        if tree is not None:
            (repo / "AGENTS.md").write_text(tree)
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps({
            "run_id": name, "launched_session": SEAT, "state": "pass", "verdict": "PASS",
            "merged": True, "repo": str(repo), "pr": "https://github.com/acme/widget/pull/7",
            "started_at": time.time() - age - 3600, "finished_at": time.time() - age,
            **({"health": {"command": "curl -fsS https://acme.test/ok"}} if health else {}),
            **({"live_at": time.time() - 10} if live else {})}) + "\n")

    def delivered(self, name, declared):
        """A checkout whose delivered commit's AGENTS.md is `declared`: (its path, that commit)."""
        repo = self.home / f"wt-{name}"
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        git = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                                           capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        (repo / "AGENTS.md").write_text(declared)
        git("add", "AGENTS.md")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "delivered")
        return repo, git("rev-parse", "HEAD")

    def parked_exhausted(self, name="parked-exhausted"):
        """A run of the seat's parked with its rounds spent, undecided."""
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": SEAT, "state": "exhausted", "error": SPENT,
             "started_at": time.time() - 9000, "finished_at": time.time() - 60}) + "\n")
