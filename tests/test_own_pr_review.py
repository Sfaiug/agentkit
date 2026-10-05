"""A seat's own PR is reviewed whatever its size, and its size is recorded; inbox PRs run freely.

Offline: local git fixtures, a temporary HOME, and fake GitHub and reviewer calls.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gate, config, gc, history, plan, run, status, watch
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"


class OwnPrReview(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-own-pr-review-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "",
            "AGENTKIT_SESSION": "fix-api",
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
               want_review=None, launch_only=False, worktree=None):
        directory = config.RUNS / f"review-{len(list(config.RUNS.iterdir()))}"
        directory.mkdir()
        head = run.git(worktree or self.repo, "rev-parse", "HEAD")      # the PR's head
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
                                ("collect_usage", {}),
                                ("ready_order", ["astra"]), ("post_review", True),
                                ("checks", (True, "")), ("gh_json", (info, ""))):
                mocks.enter_context(patch.object(run, name, return_value=value))
            self.made = []
            mocks.enter_context(patch.object(run, "make_worktree", side_effect=lambda *args: (
                self.made.append(args), (worktree or self.repo, "ak/pr-7"))[1]))
            mocks.enter_context(patch.object(gc, "disk_pressure", return_value=False))
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

    def test_an_own_pr_of_any_size_is_reviewed(self):
        self.change(5000)
        (self.repo / "output.generated").write_text("generated\n" * 1000)
        self.commit()
        for background in (False, True):
            with self.subTest(background=background):
                state, reviewer, usage, _ = self.review(background=background)
                self.assertEqual(state["state"], "pass")
                self.assertTrue(state["own_pr"])
                self.assertTrue(state["merged"])
                reviewer.assert_called_once()
                self.assertEqual(usage.call_count, 2 if background else 1)
                run.history_finish(state)
                self.assertEqual(history.get(state["run_id"])["changed_lines"], 5000)

    def test_an_own_pr_review_carries_the_seats_open_plan_lines_on_its_repository(self):
        here = plan.named(self.repo)
        config.plan_path("fix-api").write_text(
            f"- [x] the gate opens · your eye · {here} · written 2026-10-01 10:00"
            " · done your yes 2026-10-01 11:00\n"
            f"- [ ] the fence holds · check: `test -f fence.txt` · {here} · written 2026-10-02 12:00\n"
            "- [ ] the other site loads · check: `true` · ~/code/site#0123456789ab"
            " · written 2026-10-02 12:00\n")
        self.change(5)
        own = Path(self.review()[0]["task"]).read_text()
        self.assertIn("## The plan this PR serves", own)
        self.assertIn("- [ ] the fence holds · check: `test -f fence.txt`", own)
        self.assertNotIn("the gate opens", own)
        self.assertNotIn("the other site loads", own)       # another project's outcome
        self.assertIn("a finding whose proof is that line's check, run with `--run`", own)
        theirs = Path(self.review(author="acme-friend")[0]["task"]).read_text()
        self.assertNotIn("## The plan this PR serves", theirs)

    def test_the_plan_lines_follow_the_pr_s_history_not_the_branch_checked_out(self):
        here = plan.named(self.repo)
        config.plan_path("fix-api").write_text(
            f"- [ ] the fence holds · check: `test -f fence.txt` · {here} · written 2026-10-02 12:00\n")
        self.change(5)
        reviewed = self.root / "pr-7"
        self.git("worktree", "add", "-q", "--detach", str(reviewed), "HEAD")
        self.git("checkout", "-q", "--orphan", "gh-pages")     # the main checkout's own root
        self.git("commit", "-q", "--allow-empty", "-m", "pages")
        own = Path(self.review(worktree=reviewed)[0]["task"]).read_text()
        self.assertIn("the fence holds", own)

    def test_a_line_from_before_roots_counts_where_its_name_resolves(self):
        config.update_session("fix-api", repo=str(self.repo))
        config.plan_path("fix-api").write_text(
            f"- [ ] the fence holds · check: `test -f fence.txt` · {self.repo.name} · written 2026-10-02 12:00\n"
            "- [ ] the site loads · check: `true` · site · written 2026-10-02 12:00\n"
            "- [ ] a hand-kept note\n")
        self.change(5)
        own = Path(self.review()[0]["task"]).read_text()
        self.assertIn("the fence holds", own)
        self.assertNotIn("the site loads", own)
        self.assertNotIn("a hand-kept note", own)

    def test_an_unreadable_plan_or_root_refuses_the_review_before_any_checkout(self):
        self.change(5)
        here = plan.named(self.repo)
        for why, written in (("plan", b"- [ ] \xff\xfe not text\n"),
                             ("root", f"- [ ] the fence holds · check: `true` · {here}"
                                      " · written 2026-10-02 12:00\n".encode())):
            with self.subTest(why=why):
                config.plan_path("fix-api").write_bytes(written)
                with patch.object(plan, "root", return_value=None), \
                        self.assertRaises(config.Error):
                    self.review()
                self.assertEqual(self.made, [], "a checkout was made for a refused review")

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
        record.save_state(directory, state)
        with patch.object(run, "start_followups"):
            run.record_decision(directory, state, "merged by the maintainer", merged=True)
        self.assertTrue(record.read_state(directory)["merged"])
        self.assertEqual(history.get("unmerged")["changed_lines"], 6)

    def test_history_status_names_no_size_ceiling(self):
        with redirect_stdout(io.StringIO()) as out, patch.object(gate, "host_status_line"):
            status.cmd_status(["--history"])
        self.assertNotIn("ceiling", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
