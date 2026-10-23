"""A worker that brings newer target commits into its branch hands in only its own lines.

A run's base is the target's tip at launch.  A worker that rebases onto a newer tip, or merges it
in, moves where its change starts: once the round's worker turns are over the base follows to
the newest target commit the branch holds (`roundloop.follow_target`), so the first review's size,
the reviewer's diff and the prose it adds count the branch's work alone, never the target's moves
since launch.  Offline: a real checkout whose `origin/main` moves past the base.
"""

import os
import subprocess
import sys
import unittest

from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gate, history, record, roundloop, run, task as taskfile, turns


class BaseFollowsWorkerRebase(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        self.write({"api.py": "a\n"}, "Base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("checkout", "-qb", "fix-api")
        self.write({"api.py": "a\nb\n"}, "Change")
        # another change lands on the target after the launch, larger than a first review takes
        # and with prose a branch may not add
        self.git("checkout", "-q", "main")
        self.write({"other.py": "".join(f"o{k} = {k}\n" for k in range(taskfile.MAX_PR_LINES)),
                    "notes.md": "target text\n"}, "Elsewhere")
        self.tip = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.tip)
        self.git("checkout", "-q", "fix-api")

    def git(self, *args):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()

    def write(self, files, message):
        for name, content in files.items():
            (self.repo / name).write_text(content)
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def rounds(self, run_id, integrate):
        state = {"run_id": run_id, "title": "Fix the API", "state": "running", "repo": str(self.repo),
                 "worktree": str(self.repo), "base": "main", "base_sha": self.base,
                 "branch": "fix-api", "executor": "opus", "reviewer": "astra", "rounds": 3,
                 "round_summaries": []}
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        record.save_state(directory, state)
        history.start_run(run_id, repo=str(self.repo))
        lp = run.Loop(config.load(), directory, state, {}, lambda _s: None, self.repo,
                      "# Fix the API", ["true"], "Do the task.")

        def build(*_args):
            lp.round_dir.mkdir(parents=True, exist_ok=True)
            self.git(*integrate)
            (self.repo / "new.py").write_text("n = 1\n")
            return "built"
        with patch.object(roundloop, "execute", side_effect=build), \
                patch.object(run, "pickup_new_code", return_value=None), \
                patch.object(gate, "run_done_when", return_value=(True, "$ true\n[exit 0]")), \
                patch.object(roundloop, "review", return_value="PASS") as review:
            try:
                run.rounds(lp)
            except turns.Blocked as blocked:
                self.fail(f"the target's own lines were counted as the branch's: {blocked}")
        self.assertTrue(review.call_args.args[2], review.call_args.args[3])
        return review.call_count, lp.state, history.get(run_id)["first_review_lines"]

    def test_a_branch_rebased_onto_a_newer_tip_counts_only_its_own_lines(self):
        reviewed, state, lines = self.rounds("20261022-1300-rebased", ["rebase", "-q", "origin/main"])
        self.assertEqual((reviewed, lines), (1, 2))
        self.assertEqual((state["base_sha"], state["target_sha"]), (self.tip, self.tip))

    def test_a_branch_that_merged_a_newer_tip_counts_only_its_own_lines(self):
        reviewed, state, lines = self.rounds("20261022-1310-merged",
                                             ["merge", "-q", "--no-edit", "origin/main"])
        self.assertEqual((reviewed, lines), (1, 2))
        self.assertEqual(state["base_sha"], self.tip)

    def test_a_branch_that_took_in_nothing_keeps_its_base(self):
        reviewed, state, lines = self.rounds("20261022-1320-kept", ["status", "--short"])
        self.assertEqual((reviewed, lines), (1, 2))
        self.assertEqual(state["base_sha"], self.base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
