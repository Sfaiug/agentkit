"""A builder's `blocked` stops no change its checks pass that still awaits its first review.

A worker's why is a model's words, and no reading of them tells a size from a task nobody can do:
"split items" is a real blocker, "580 added lines; split the change" is none.  So ak reads the diff
and the checks.  Offline: a real checkout whose attributes mark a generated file, the checks
injected; tests/test_key_executor_blocked.py holds the whole run from outside.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, hand_in, history, record, roundloop, run, task as taskfile, turns

WHYS = ("The change takes 580 added lines; split the change into smaller PRs",
        "The task needs ten items in three equal groups; it is impossible to split items that way")


class BlockedOverAChange(Sandbox):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {"AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
                                                  "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
                                                  "AK_MAX_RUNS": "0"}))
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / ".gitattributes").write_text("dist/*.js linguist-generated\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "Base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "fix-api")

    def git(self, *args):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()

    def loop(self, **extra):
        directory = config.RUNS / f"20261030-0900-try-{len(list(config.RUNS.glob('*')))}"
        directory.mkdir(parents=True)
        state = {"run_id": directory.name, "title": "Fix the API", "state": "running",
                 "repo": str(self.repo), "worktree": str(self.repo), "base": "main",
                 "base_sha": self.base, "branch": "fix-api", "executor": "opus", "reviewer": "astra",
                 "rounds": 3, "round_summaries": [], **extra}
        record.save_state(directory, state)
        history.start_run(directory.name, repo=str(self.repo))
        return run.Loop(config.load(), directory, state, {}, lambda _s: None, self.repo,
                        "# Fix the API", ["true"], "Do the task.")

    def closed(self, lp, why, checks=True):
        """The builder's turn, closed blocked, as the loop reads it: (its result, its checks' calls)."""
        out = lp.run_dir / "round-1" / "executor"
        out.mkdir(parents=True, exist_ok=True)
        (out / "final.md").write_text("Stopped.")
        hand_in.start(out, self.repo, role="executor")
        with (out / hand_in.FILE).open("a") as closing:
            closing.write(json.dumps({"kind": "blocked", "why": why}) + "\n")
        with patch.object(roundloop, "verify_work", return_value=(checks, "")) as verify:
            try:
                return roundloop.worker_result(lp, "Stopped.", out), verify.call_count
            except turns.Blocked as blocked:
                return str(blocked), verify.call_count

    def test_a_change_its_checks_pass_goes_on_whatever_the_why_says(self):
        for why in WHYS:
            with self.subTest(why=why):
                self.git("reset", "-q", "--hard", self.base)
                # uncommitted, as builders leave it, and every line generated, as on 29 Oct 2026
                (self.repo / "dist").mkdir()
                (self.repo / "dist" / "app.js").write_text("built\n" * 900)
                self.assertEqual(self.closed(self.loop(), why), ("Stopped.", 1))
                self.assertIn("dist/app.js", self.git("show", "--name-only", "--format=", "HEAD"))

    def test_a_change_whose_checks_fail_ends_the_run_with_the_why_and_keeps_the_work(self):
        (self.repo / "api.py").write_text("half = 1\n")
        self.assertEqual(self.closed(self.loop(), WHYS[1], checks=False), (WHYS[1], 1))
        self.assertIn("api.py", self.git("show", "--name-only", "--format=", "HEAD"))

    def test_with_no_change_there_is_nothing_to_judge_and_the_why_stands(self):
        for why in WHYS:
            with self.subTest(why=why):
                self.assertEqual(self.closed(self.loop(), why), (why, 0))

    def test_only_a_first_review_is_ahead_of_a_change(self):
        (self.repo / "api.py").write_text("half = 1\n")
        for extra in ({"round_summaries": [{"round": 1, "verdict": "FAIL"}]},
                      {"review_pr": "https://github.com/acme/widget/pull/7"},
                      {"repo": "none", "scratch": True}):
            with self.subTest(extra=extra):
                self.assertEqual(self.closed(self.loop(**extra), WHYS[1]), (WHYS[1], 0))

    def test_ak_s_count_ends_a_change_too_big_for_a_first_review_in_its_own_words(self):
        def build(lp, *_args):
            (self.repo / "api.py").write_text("n = 1\n" * (taskfile.MAX_PR_LINES + 1))
            return self.closed(lp, WHYS[1])[0]

        lp = self.loop()
        with patch.object(roundloop, "execute", side_effect=build), \
                patch.object(run, "pickup_new_code", return_value=None), \
                patch.object(roundloop, "review") as review, \
                self.assertRaisesRegex(turns.Blocked, f"adds {taskfile.MAX_PR_LINES + 1} lines.*split it$"):
            run.rounds(lp)
        review.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
