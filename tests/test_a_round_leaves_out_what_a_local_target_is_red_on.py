"""A round whose target origin has no branch of leaves out the tests that target's landing line
holds its local branch red on as the run started, though the work has moved that branch since.
A branch is the one of that full name: a tag named as origin's branch or the local one would be
is neither.  A run whose record is from before runs kept the local branch leaves out those the
line holds its base red on, where the base is the target.

Task runs with `--no-worktree` through `bin/ak` in a Home of tests/fixtures/akbin.py, on the
origin of gitrig.py with scripted harnesses from fakeadapter.py.  The test writes an earlier
landing's reds and the line's record as ak writes them, and the suite notes the tests it was
handed to notes.py.
"""

import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_round_runs_its_changes_tests import SUITE
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, deliver, history, land

# An earlier landing was red on both, handed in this order; the second fails where `value` is bad.
OTHER, VALUE = "./tests/other.sh", "./tests/value.sh"


class ARound(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.said = Notes()
        self.addCleanup(self.said.close)
        self.rig = Rig(self.home, "acme", files={
            "AGENTS.md": "---\nusers: none\nhealth: none\ntests: python3 suite.py\n---\n",
            "suite.py": SUITE.format(said=self.said.address), "value": "good\n",
            OTHER: "true\n", VALUE: "grep -qx good value\n"})
        self.rig.git("config", "ak.repository", "0123456789ab")
        self.home.write(".agentkit/state/test-times-0123456789ab.json", {OTHER: 1, VALUE: 1})
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")

    def line_holds(self, red):
        """Write that landing's reds and the record of `draft`'s line: {a ref: the tests the
        line holds its tree red on}."""
        with patch.object(config, "HOME", self.home.path / ".agentkit"), \
                patch.dict(os.environ, self.home.env, clear=True):
            history.start_run("fix-api", repo=self.rig.name)
            history.test_reds(("fix-api", None, "landing", "tree"), {"failed": [OTHER, VALUE]}, [])
            turn = deliver.merge_lock_path(self.rig.git("remote", "get-url", "origin"),
                                           "origin/draft")
            turn.parent.mkdir(parents=True, exist_ok=True)
            land.note(turn, [], "fix-api", red={
                self.rig.git("rev-parse", f"{ref}^{{tree}}"): {"tests": tests}
                for ref, tests in red.items()})

    def passes_handing(self, tests, *run):
        """That `ak run` passes, its suite started once and handed those tests."""
        done = self.home.ak("run", *run, cwd=self.rig.path, timeout=240)
        self.assertEqual((done.code, self.said.since()), (0, ["suite " + " ".join(tests)]),
                         done.out[-900:])

    def test_it_leaves_out_what_the_line_holds_the_local_branch_red_on_as_the_run_started(self):
        # The base `main`, where tags named as origin's branch would be stand too, and the
        # target `draft`: the checkout is on it, so the run's commit moves that name.
        for tag in ("origin/draft", "refs/remotes/origin/draft"):
            self.rig.git("tag", tag)
        self.rig.branch("draft", {"value": "bad\n"}, push=False)
        self.rig.git("checkout", "-q", "draft")
        self.line_holds({"main": [OTHER], "draft": [VALUE]})
        task = taskfile.write(self.home, self.rig.path, front={"base": "main", "target": "draft"})
        self.passes_handing([OTHER], str(task), "--rounds", "1", "--no-worktree", "--no-merge")

    def test_a_tag_named_as_the_local_branch_would_be_holds_nothing_back(self):
        self.rig.git("tag", "refs/heads/draft")
        self.rig.git("checkout", "-qb", "work")
        self.line_holds({"main": [OTHER]})
        task = taskfile.write(self.home, self.rig.path, front={"base": "main", "target": "draft"})
        self.passes_handing([OTHER, VALUE], str(task), "--rounds", "1", "--no-worktree",
                            "--no-merge")

    def test_a_record_from_before_leaves_out_what_the_line_holds_its_base_red_on(self):
        self.rig.branch("draft", {"value": "bad\n"}, push=False)
        self.rig.git("checkout", "-q", "draft")
        self.line_holds({"draft": [VALUE]})
        task = taskfile.write(self.home, self.rig.path, front={"base": "draft"})
        run, now = "20261117-0100-add-retry-file", time.time()
        self.home.write(f".agentkit/runs/{run}/task.md", task.read_text())
        self.home.write(f".agentkit/runs/{run}/log.txt", "")
        self.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "title": "Add retry file", "state": "error", "verdict": "ERROR",
            "repo": str(self.rig.path), "worktree": str(self.rig.path), "branch": "draft",
            "base": "draft", "target": "draft", "base_sha": self.rig.git("rev-parse", "draft"),
            "rounds": 1, "round_summaries": [], "executor": "opus", "reviewer": "astra",
            "no_merge": True, "silence_minutes": 20, "ceiling_hours": 6,
            "started_at": now - 120, "finished_at": now - 60})
        self.passes_handing([OTHER], "resume", run)


if __name__ == "__main__":
    unittest.main()
