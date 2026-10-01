"""Own PRs fit a ceiling learned from this host's merged work; inbox PRs run freely.

Offline: local git fixtures, a temporary HOME, and fake GitHub and reviewer calls.
"""

from contextlib import ExitStack, closing, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, run, watch

URL = "https://github.com/acme/widget/pull/7"


class PrCeiling(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-pr-ceiling-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "fix-api",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1"}))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "old.txt").write_text("old\n")
        (self.repo / ".gitattributes").write_text("*.generated linguist-generated=true\n")
        self.base = self.commit()
        self.git("update-ref", "refs/remotes/origin/main", self.base)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def change(self, lines):
        (self.repo / "work.txt").write_text("work\n" * lines)
        return self.commit()

    def review(self, author="owner", seat="fix-api", background=False,
               want_review=None, launch_only=False):
        directory = config.RUNS / f"review-{len(list(config.RUNS.iterdir()))}"
        directory.mkdir()
        head = self.git("rev-parse", "HEAD")
        info = dict(state="OPEN", title="Mend the fence", author=author,
                    baseRefName="main", headRefOid=head, body="small fix")

        def passed(lp, *_args, **_kw):
            lp.state.update(verdict="PASS", round_summaries=[{"verdict": "PASS"}])
            return "PASS"

        def merged(lp, *_args, **_kw):
            lp.state["merged"] = True
            return True

        opts = {"--review": want_review, "--review-pr": URL}

        def reviewed(directory, *_args, **_kw):
            return run.review_pr(self.cfg, directory, URL, opts, lambda _: None)

        with ExitStack() as mocks:
            mocks.enter_context(patch.dict(os.environ, {"AGENTKIT_SESSION": seat}))
            run.capture_launch(directory, {"--review-pr": URL})
            for name, value in (("pr_view", info), ("viewer_login", "owner"),
                                ("checkout_for", self.repo), ("fetch", (0, "")),
                                ("make_worktree", (self.repo, "ak/pr-7")),
                                ("disk_pressure", False), ("collect_usage", {}),
                                ("ready_order", ["astra"]), ("post_review", True),
                                ("checks", (True, "")), ("gh_json", (info, ""))):
                mocks.enter_context(patch.object(run, name, return_value=value))
            for name in ("exclude_junk", "join_session_project", "restore_review_checkout",
                         "write_result", "refused"):
                mocks.enter_context(patch.object(run, name))
            reviewer = mocks.enter_context(patch.object(run, "review", side_effect=passed))
            usage = run.collect_usage
            self.reviewer, self.usage = reviewer, usage
            mocks.enter_context(patch.object(run, "merge_own_pr", side_effect=merged))
            inbox = mocks.enter_context(patch.object(watch, "ask_inbox", return_value=0))
            if background:
                mocks.enter_context(patch.object(run, "spawn_bg", return_value=0,
                                                 side_effect=None if launch_only else reviewed))
                state = run.review_pr_main(self.cfg, opts, {"--bg": True},
                                           ["--review-pr", URL, "--bg"], None)
            else:
                state = reviewed(directory)
        return state, reviewer, usage, inbox

    def fabricated(self, small=100, large=200, count=50):
        for n in range(count):
            history.start_run(str(n), repo="other-project", started_at=1)
            history.finish_run(str(n), final_state="pass", verdict="PASS", finished_at=2,
                               changed_lines=small if n < 30 else large,
                               rounds_used=1 if n < 30 else 2)

    def test_over_ceiling_refuses_before_any_model_runs(self):
        self.change(301)
        for background in (False, True):
            with self.subTest(background=background):
                with self.assertRaisesRegex(config.Error, r"301.*300.*split"):
                    self.review(background=background)
                self.usage.assert_not_called()
                self.reviewer.assert_not_called()

    def test_under_and_at_ceiling_run_and_generated_lines_do_not_count(self):
        self.change(299)
        (self.repo / "output.generated").write_text("generated\n" * 1000)
        self.commit()
        for background in (False, True):
            with self.subTest(background=background):
                state, reviewer, usage, _ = self.review(background=background)
                self.assertEqual(state["state"], "pass")
                reviewer.assert_called_once()
                self.assertEqual(usage.call_count, 2 if background else 1)
        self.change(300)
        self.assertEqual(self.review()[0]["state"], "pass")

    def test_another_authors_pr_and_a_review_without_a_seat_run(self):
        self.change(1000)
        for author, seat in (("other", "fix-api"), ("owner", "")):
            with self.subTest(author=author, seat=seat):
                state, reviewer, _, inbox = self.review(author, seat)
                self.assertFalse(state["own_pr"])
                reviewer.assert_called_once()
                inbox.assert_called_once()

    def test_background_own_pr_keeps_the_parent_launch_line_and_self_review_mark(self):
        self.change(40)
        for reviewer, mark in ((None, "(astra review)"), ("opus", "(opus review, self-reviewed)")):
            with self.subTest(reviewer=reviewer), redirect_stdout(io.StringIO()) as out, \
                    patch.object(run, "refuse_unready"):
                self.assertEqual(self.review(background=True, want_review=reviewer,
                                             launch_only=True)[0], 0)
                self.assertIn(f"launched: Review PR #7: Mend the fence {mark}", out.getvalue())
                self.reviewer.assert_not_called()

    def test_background_explicit_reviewer_is_refused_in_the_parent(self):
        self.change(40)
        with patch.object(run, "refuse_unready", side_effect=config.Error("astra cannot run here")), \
                self.assertRaisesRegex(config.Error, "astra cannot run here"):
            self.review(background=True, want_review="astra", launch_only=True)
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"], {"reviewers": ["astra"]})
        with self.assertRaisesRegex(config.Error, "not a reviewer"):
            self.review(background=True, want_review="opus", launch_only=True)

    def test_git_without_check_attr_source_reviews_and_records_sizes_without_changing_index(self):
        self.change(40)
        (self.repo / "output.generated").write_text("generated\n" * 1000)
        head = self.commit()
        (self.repo / ".gitattributes").write_text("*.generated -linguist-generated\n")
        self.git("add", ".gitattributes")
        index = self.repo / ".git" / "index"
        before = index.read_bytes()
        real_tool = run.tool_run

        def older_git(cmd, *args, **kwargs):
            if "check-attr" in cmd and any(arg.startswith("--source=") for arg in cmd):
                return 129, "", "error: unknown option 'source'"
            return real_tool(cmd, *args, **kwargs)

        with patch.object(run, "tool_run", side_effect=older_git):
            state, reviewer, _, _ = self.review()
            self.assertEqual(state["state"], "pass")
            reviewer.assert_called_once()
            state.update(delivery_sha=head, worktree=str(self.root / "gone"))
            run.history_finish(state)
            self.assertEqual(history.get(state["run_id"])["changed_lines"], 40)
        self.assertEqual(index.read_bytes(), before)

    def test_ceiling_moves_with_host_history_and_requires_fifty_sized_merges(self):
        self.fabricated(count=49)
        self.assertEqual(history.pr_ceiling(), (300, "starting value"))
        history.start_run("49", repo="acme")
        history.finish_run("49", final_state="pass", verdict="PASS", finished_at=2,
                           changed_lines=200, rounds_used=2)
        self.assertEqual(history.pr_ceiling(), (100, "history"))
        self.change(150)
        with self.assertRaisesRegex(config.Error, r"150.*100.*split"):
            self.review()
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE runs SET changed_lines=changed_lines+400")
        self.assertEqual(history.pr_ceiling(), (500, "history"))
        self.assertEqual(self.review()[0]["state"], "pass")

    def test_half_passing_is_not_a_drop_and_the_smallest_ceiling_can_be_zero(self):
        self.fabricated()
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE runs SET rounds_used=1 WHERE CAST(run_id AS INTEGER) BETWEEN 30 AND 39")
        self.assertEqual(history.pr_ceiling(), (None, "history"))
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE runs SET rounds_used=2")
        self.assertEqual(history.pr_ceiling(), (0, "history"))

    def test_merged_size_counts_additions_and_deletions_and_survives_collection(self):
        self.change(5)
        (self.repo / "old.txt").unlink()
        (self.repo / "output.generated").write_text("generated\n" * 1000)
        head = self.commit()
        state = dict(run_id="merged", repo=str(self.repo), worktree=str(self.root / "gone"),
                     base_sha=self.base, delivery_sha=head, merged=True, state="pass",
                     verdict="PASS", finished_at=2, round_summaries=[{"verdict": "PASS"}])
        history.start_run("merged", repo=str(self.repo), started_at=1)
        run.history_finish(state)
        self.assertEqual(history.get("merged")["changed_lines"], 6)
        history.start_run("unmerged", repo=str(self.repo), started_at=1)
        state = {**state, "run_id": "unmerged", "merged": False}
        run.history_finish(state)
        self.assertIsNone(history.get("unmerged")["changed_lines"])
        directory = config.RUNS / "unmerged"
        directory.mkdir()
        run.save_state(directory, state)
        with patch.object(run, "start_followups"):
            run.record_decision(directory, state, "merged by the maintainer", merged=True)
        self.assertTrue(run.read_state(directory)["merged"])
        self.assertEqual(history.get("unmerged")["changed_lines"], 6)

    def test_history_status_shows_ceiling_and_source(self):
        with redirect_stdout(io.StringIO()) as out, patch.object(run, "host_status_line"):
            run.cmd_status(["--history"])
        self.assertIn("PR size ceiling: 300 changed lines (starting value)", out.getvalue())
        self.fabricated()
        with redirect_stdout(io.StringIO()) as out, patch.object(run, "host_status_line"):
            run.cmd_status(["--history"])
        self.assertIn("PR size ceiling: 100 changed lines (history)", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
