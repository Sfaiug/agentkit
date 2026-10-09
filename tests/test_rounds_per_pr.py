"""Review rounds are budgeted per change, counted across runs: three per pull request.

A review of a seat's own PR inherits the rounds earlier runs spent on that PR, and a task
launched `from:` a branch continues the change of the run that branch still belongs to and
inherits the rounds spent on it; a fourth round is refused at launch, whichever run would spend
it.  A change is a recorded id, never a branch name: a name freed by a merge or a stop and given
to the next task charges it nothing, and a run in the repository itself owns no branch.
Offline: run records in a throwaway HOME, a faked GitHub, a real git repository for the task
launch.
"""

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from types import SimpleNamespace

from agentkit import config, record, run, task as taskfile

URL = "https://github.com/acme/widget/pull/7"
OTHER = "https://github.com/acme/widget/pull/8"
INFO = {"number": 7, "title": "Widget", "body": "", "author": "acme-bot", "baseRefName": "main",
        "headRefOid": "a" * 40, "url": URL, "state": "OPEN", "isDraft": False}


class RoundsPerPr(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", config.SESSION_ENV: "fix-api",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])

    def earlier(self, name, rounds, **fields):
        """An earlier run's record with that many rounds spent."""
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {
            "run_id": name, "title": f"Task {name}", "state": "fail", "launched_session": "fix-api",
            "round_summaries": [{"round": n, "verdict": "FAIL", "summary": ""}
                                for n in range(1, rounds + 1)], **fields})
        return directory

    def own(self, repo, n):
        """A checkout ak cut for a run of that repository."""
        return {"repo": str(repo), "worktree": str(self.root / f"wt-{n}")}

    def test_rounds_spent_on_the_same_pr_or_change_count_across_runs(self):
        own = self.earlier("20260101-0900-review-pr-widget-7", 2, review_pr=URL, pr=URL)
        self.earlier("20260101-0800-task", 1, pr=URL, branch="ak/task")
        self.earlier("20260101-0700-review-pr-widget-8", 3, review_pr=OTHER, pr=OTHER)
        first = "20260101-0600-first"
        self.earlier(first, 2, branch="ak/first")
        self.earlier("20260101-0500-second", 1, branch="ak/first-2", change=first, **{"from": "ak/first"})
        self.earlier("20260101-0400-third", 1, branch="ak/first-3", change=first, **{"from": "ak/first-2"})
        self.earlier("20260101-0300-fresh", 0, review_pr=URL, pr=URL)
        self.assertEqual(run.rounds_spent_elsewhere(pr=URL), (3, 2))
        self.assertEqual(run.rounds_spent_elsewhere(pr=URL, exclude=own), (1, 1))
        self.assertEqual(run.rounds_spent_elsewhere(pr=OTHER), (3, 1))
        # every run of a change carries its id, however far down the relaunches go
        self.assertEqual(run.rounds_spent_elsewhere(change=first), (4, 3))
        self.assertEqual(run.round_budget(3, change=first, what="branch ak/first-3")[0], 0)
        self.assertEqual(run.rounds_spent_elsewhere(change="20260101-0000-nothing"), (0, 0))
        self.assertEqual(run.rounds_spent_elsewhere(), (0, 0))
        # a pull request is one name however its URL is spelled
        for spelled in (URL + "/", "https://github.com/Acme/Widget/pull/7", " " + URL):
            self.assertEqual(run.rounds_spent_elsewhere(pr=spelled), (3, 2), spelled)
        self.earlier("20260101-0200-review-pr-widget-7", 1, review_pr=URL + "/", pr=URL + "/")
        self.assertEqual(run.rounds_spent_elsewhere(pr=URL), (4, 3))

    def test_a_branch_belongs_to_the_newest_run_still_on_it_and_a_freed_name_to_nobody(self):
        repo = self.root / "acme"
        repo.mkdir()
        for n, (name, fields) in enumerate((
                ("20260101-0100-merged", {"merged": True, "pr": "https://github.com/acme/widget/pull/3"}),
                ("20260101-0200-stopped", {"state": "stopped"}),         # without --keep
                ("20260101-0300-closed", {"branch_removed": True}),       # its session stopped
                ("20260101-0350-done", {"state": "not_needed"}))):
            self.earlier(name, 3, branch="ak/fix-parser", **self.own(repo, n), **fields)
        # a run in the repository itself is on whatever branch was checked out and owns none
        self.earlier("20260101-0400-plain", 3, branch="ak/fix-parser", repo=str(repo), worktree=str(repo))
        self.assertIsNone(run.change_on("ak/fix-parser", repo))
        self.assertEqual(run.round_budget(3, change=None, what="x"), (3, None))
        self.earlier("20260101-0500-kept", 1, branch="ak/fix-parser", **self.own(repo, 5),
                     state="stopped", stop_kept=True)
        self.assertEqual(run.change_on("ak/fix-parser", repo), "20260101-0500-kept")
        # the newest run on a branch names the change it inherited, not itself ...
        self.earlier("20260101-0600-again", 1, branch="ak/fix-parser-2", **self.own(repo, 6),
                     change="20260101-0500-kept", **{"from": "ak/fix-parser"})
        self.assertEqual(run.change_on("ak/fix-parser-2", repo), "20260101-0500-kept")
        self.assertEqual(run.round_budget(3, change="20260101-0500-kept", what="x"), (1, None))
        # ... and only in its repository: the same name elsewhere is another change
        other = self.root / "widget"
        other.mkdir()
        self.assertIsNone(run.change_on("ak/fix-parser", other))

    def test_a_run_in_the_repository_itself_is_its_own_change(self):
        repo = self.root / "acme"
        repo.mkdir()
        self.earlier("20260101-0600-parser", 3, branch="main", repo=str(repo), worktree=str(repo))
        state = {"run_id": "20260101-0700-docs", "repo": str(repo), "worktree": str(repo), "branch": "main"}
        self.assertEqual(run.lineage_cap(state, config.RUNS / "20260101-0700-docs"), 3)

    def test_a_round_is_refused_as_it_is_spent_once_another_run_of_the_change_took_it(self):
        repo = self.root / "acme"
        repo.mkdir()
        self.earlier("20260101-0600-a", 2, branch="ak/a", **self.own(repo, 1))
        b = self.earlier("20260101-0700-b", 0, branch="ak/b", **self.own(repo, 2),
                         change="20260101-0600-a", **{"from": "ak/a"})
        lp = SimpleNamespace(rounds=3, state=record.read_state(b), run_dir=b, rnd=0, log=lambda _: None)
        self.assertEqual(run.allowed_rounds(lp), 1)       # one round left on the change ...
        self.assertTrue(run.round_allowed(lp))
        lp.rnd = 1                                        # ... and this run spent it
        with self.assertRaisesRegex(run.Blocked, "3 review rounds spent on this change across 2 runs: "
                                                 "3 per pull request is the budget; split or redesign it"):
            run.round_allowed(lp)
        lp.rnd = 0
        self.earlier("20260101-0600-a", 3, branch="ak/a", **self.own(repo, 1))
        self.assertEqual(run.allowed_rounds(lp), 0)       # spent meanwhile by its sibling ...
        with self.assertRaisesRegex(run.Blocked, "3 review rounds spent on this change across 1 run:"):
            run.round_allowed(lp)                         # ... so this run ends blocked, with the reason
        self.assertEqual(run.lineage_cap(lp.state, b), 0)
        # a round under way counts from its first step, on a run still going; a dead run's
        # does not
        self.earlier("20260101-0600-a", 2, branch="ak/a", **self.own(repo, 1), state="running",
                     step="executor", step_round=3)
        self.assertEqual(run.allowed_rounds(lp), 0)
        with self.assertRaisesRegex(run.Blocked, "3 review rounds spent on this change across 1 run:"):
            run.round_allowed(lp)
        self.assertEqual(run.round_budget(3, change="20260101-0600-a", what="x")[0], 0)   # a launch sees it too
        self.earlier("20260101-0600-a", 2, branch="ak/a", **self.own(repo, 1), state="running",
                     review_pending={"round": 3, "summary": ""})
        self.assertEqual(run.allowed_rounds(lp), 0)
        self.earlier("20260101-0600-a", 2, branch="ak/a", **self.own(repo, 1),
                     step="executor", step_round=3, review_pending={"round": 3, "summary": ""})
        self.assertEqual(run.allowed_rounds(lp), 1)

    def test_the_budget_is_what_earlier_runs_left_of_three(self):
        self.assertEqual(run.round_budget(3, pr=URL, what="PR #7"), (3, None))
        self.earlier("20260101-0900-review-pr-widget-7", 1, review_pr=URL, pr=URL)
        self.assertEqual(run.round_budget(3, pr=URL, what="PR #7"), (2, None))
        self.assertEqual(run.round_budget(1, pr=URL, what="PR #7"), (1, None))
        self.earlier("20260101-0800-review-pr-widget-7", 2, review_pr=URL, pr=URL)
        left, why = run.round_budget(3, pr=URL, what="PR #7")
        self.assertEqual(left, 0)
        self.assertEqual(why, "3 review rounds spent on PR #7 across 2 runs: "
                              f"{taskfile.TASK_MAX_ROUNDS} per pull request is the budget; "
                              "split or redesign it")

    def launch(self, name="20260102-0900-review-pr-widget-7"):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "launched_session": "fix-api",
                                      "state": "queued"})
        return directory

    def test_a_fourth_review_of_an_own_pr_is_refused_at_launch_and_in_the_round(self):
        self.earlier("20260101-0900-review-pr-widget-7", 2, review_pr=URL, pr=URL)
        self.earlier("20260101-0800-review-pr-widget-7", 1, review_pr=URL, pr=URL)
        launch = self.launch()
        logs = []
        with patch.object(run, "pr_view", return_value=dict(INFO)), \
                patch.object(run, "own_pr_orchestrator", return_value=(True, "opus")):
            with self.assertRaises(config.Error) as refused:
                run.preflight(launch, {"--review-pr": URL, "--no-merge": False}, logs.append)
            self.assertIn("3 review rounds spent on PR #7 across 2 runs", str(refused.exception))
            # ... and inside the round, where a resumed run reads its own earlier rounds too
            with self.assertRaises(config.Error) as refused:
                run.review_pr_round(self.cfg, launch, URL, {"--review-pr": URL}, logs.append)
            self.assertIn("3 review rounds spent on PR #7", str(refused.exception))
            # somebody else's PR has one review, whatever anybody spent on it
            with patch.object(run, "own_pr_orchestrator", return_value=(False, None)), \
                    patch.object(run, "checkout_for", side_effect=RuntimeError("past the budget")):
                with self.assertRaises(RuntimeError):
                    run.review_pr_round(self.cfg, self.launch("20260102-0901-review-pr-widget-7"),
                                        URL, {"--review-pr": URL}, logs.append)

    def test_an_own_pr_review_gets_only_the_rounds_earlier_runs_left(self):
        self.earlier("20260101-0900-review-pr-widget-7", 2, review_pr=URL, pr=URL)
        launch = self.launch()
        logs = []
        with patch.object(run, "pr_view", return_value=dict(INFO)), \
                patch.object(run, "own_pr_orchestrator", return_value=(True, "opus")), \
                patch.object(run, "checkout_for", side_effect=RuntimeError("past the budget")):
            with self.assertRaises(RuntimeError):     # the budget check passed: one round left
                run.review_pr_round(self.cfg, launch, URL, {"--review-pr": URL}, logs.append)
            # ... and that one round, once spent in this run, is the last
            state = record.read_state(launch)
            record.save_state(launch, {**state, "own_pr": True, "own_orchestrator": "opus",
                                       "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": ""}]})
            with self.assertRaises(config.Error) as refused:
                run.review_pr_round(self.cfg, launch, URL, {"--review-pr": URL}, logs.append)
            self.assertIn("3 review rounds spent on PR #7 across 2 runs", str(refused.exception))

    def test_a_resume_cannot_spend_past_the_changes_budget(self):
        repo = self.root / "acme"
        repo.mkdir()
        self.earlier("20260101-0600-a", 2, branch="ak/a", **self.own(repo, 1))
        wt = self.root / "checkout-b"
        wt.mkdir()
        b = self.earlier("20260101-0700-b", 1, branch="ak/b", worktree=str(wt), repo=str(repo),
                         base="origin/main", base_sha="a" * 40, no_merge=True,
                         change="20260101-0600-a", **{"from": "ak/a"})
        record.save_state(b, {**record.read_state(b), "rounds": 1})
        (b / "task.md").write_text("# B\n\n## Goal\nx\n\n## Done when\n```bash\ntrue\n```\n")
        (b / "log.txt").write_text("")
        state = record.read_state(b)
        self.assertTrue(run.failed_at_budget(state))
        self.assertEqual(run.lineage_cap(state, b), 1)
        self.assertEqual(run.continue_line(state, b), "")       # nothing to spend: no way on
        with patch.object(run.box, "check"), patch.object(run, "place_here", return_value=None):
            with self.assertRaises(config.Error) as refused:
                run.resume_run(["20260101-0700-b", "--rounds", "3"])
        self.assertIn("3 review rounds spent on this change across 2 runs: 3 per pull request is the budget",
                      str(refused.exception))
        # with one round left on the change, the resume may take exactly that much
        record.save_state(config.RUNS / "20260101-0600-a", {
            **record.read_state(config.RUNS / "20260101-0600-a"),
            "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": ""}]})
        self.assertEqual(run.lineage_cap(state, b), 2)
        self.assertEqual(run.continue_line(state, b), "continue: ak run resume 20260101-0700-b --rounds 2")
        with patch.object(run.box, "check"), patch.object(run, "place_here", return_value=None):
            with self.assertRaises(config.Error) as refused:
                run.resume_run(["20260101-0700-b"])
        # the bound named is the one a --rounds is held to
        self.assertIn("give --rounds N above it, at most 2, to continue", str(refused.exception))
        seen = []
        with patch.object(run.box, "check"), patch.object(run, "place_here", return_value=None), \
                patch.object(run, "drive", side_effect=lambda *a, **k: seen.append(k["prior"]["rounds"]) or 0):
            with self.assertRaises(config.Error) as refused:
                run.resume_run(["20260101-0700-b", "--rounds", "3"])
            self.assertIn("--rounds 3 is over this change's budget: 2 of 3 rounds", str(refused.exception))
            self.assertEqual(run.resume_run(["20260101-0700-b", "--rounds", "2"]), 0)
        self.assertEqual(seen, [2])

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def test_a_task_launched_from_a_branch_continues_that_change(self):
        repo = config.CODE / "acme"
        repo.mkdir(parents=True)
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "user.name", "Fixture")
        self.git(repo, "config", "user.email", "fixture@localhost")
        (repo / "AGENTS.md").write_text("---\nusers: none\n---\n# acme\n")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "Base")
        self.git(repo, "branch", "ak/fix-parser")
        self.earlier("20260101-0900-fix-parser", 2, branch="ak/fix-parser", **self.own(repo, 1))
        self.earlier("20260101-0800-fix-parser", 1, branch="ak/fix-parser-2", **self.own(repo, 2),
                     change="20260101-0900-fix-parser", **{"from": "ak/fix-parser"})
        task = self.root / "task.md"
        task.write_text(f"---\nrepo: {repo}\nfrom: ak/fix-parser\n---\n# Fix the parser\n\n"
                        "## Goal\nThe parser parses.\n\n## Done when\n```bash\ntrue\n```\n")
        launch = self.launch("20260102-0900-fix-parser")
        opts = {"--rounds": None, "--no-worktree": False, "--no-merge": False}
        logs = []
        with self.assertRaises(config.Error) as refused:
            run.loop(self.cfg, launch, task, opts, logs.append)
        self.assertIn("3 review rounds spent on branch ak/fix-parser across 2 runs",
                      str(refused.exception))
        self.assertEqual([p.name for p in config.WT.iterdir()] if config.WT.exists() else [], [])
        # a task that names no `from:` is a new change, whatever the branch a slug lands on
        self.earlier("20260101-0700-fix-parser", 3, branch="ak/fix-the-parser", **self.own(repo, 3))
        self.assertEqual(run.round_budget(3, exclude=launch, what="x"), (3, None))
        # with a round left on the change, the launch records the change it continues and
        # takes only that round
        self.earlier("20260101-0800-fix-parser", 0, branch="ak/fix-parser-2", **self.own(repo, 2),
                     change="20260101-0900-fix-parser", **{"from": "ak/fix-parser"})
        started = []

        def far_enough(state, cfg, log):
            started.append(state)
            raise RuntimeError("far enough")

        with patch.object(run, "invalidate_saved_pass", side_effect=far_enough):
            with self.assertRaises(RuntimeError):
                run.loop(self.cfg, launch, task, opts, logs.append)
        self.assertEqual([(s["change"], s["from"], s["rounds"]) for s in started],
                         [("20260101-0900-fix-parser", "ak/fix-parser", 1)])
        # the name freed, the next task of that title is a change of its own
        for name in ("20260101-0900-fix-parser", "20260101-0800-fix-parser"):
            record.save_state(config.RUNS / name, {**record.read_state(config.RUNS / name), "merged": True})
        self.assertIsNone(run.change_on("ak/fix-parser", repo, exclude=launch))


if __name__ == "__main__":
    unittest.main(verbosity=2)
