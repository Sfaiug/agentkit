"""A seat's own PR, reviewed by ak, is merged by ak.

Offline: every gh call, every model pick and every review is a fake. The PR is
an invented acme/widget pull, the seat is fix-api, and nothing here touches the
network, a real harness or a real checkout.
"""

from contextlib import ExitStack, contextmanager, nullcontext, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gc, orch, run, watch

URL = "https://github.com/acme/widget/pull/7"
HEAD = "b" * 40
LOGIN = "owner"


def info(author=LOGIN, head=HEAD, state="OPEN"):
    return {"state": state, "title": "Mend the fence", "author": author,
            "baseRefName": "main", "headRefOid": head, "body": "small fix"}


class OwnPr(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-review-own-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(self.root / "sockets"), "TMUX": "", "NO_COLOR": "1"}))
        (self.root / "sockets").mkdir(mode=0o700)
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.wt = self.root / "checkout"
        self.wt.mkdir()

    def launch_dir(self, name, session="fix-api"):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        with patch.dict(os.environ, {"AGENTKIT_SESSION": session}):
            run.capture_launch(run_dir, {"--review-pr": URL})
        return run_dir

    def review_pass(self, lp, summary, ok, dw_log, **_kw):
        head = lp.state["head_sha"]
        tree = "c" * 40
        lp.state["verdict"] = "PASS"
        lp.state["review"] = {"executor": None, "executor_provider": None,
                              "reviewer": lp.reviewer, "reviewer_provider": "openai",
                              "returncode": 0, "verdict": "PASS", "done_when": True,
                              "head_sha": head, "tree_sha": tree}
        lp.state["round_summaries"].append({"round": lp.rnd, "verdict": "PASS", "done_when": True,
                                           "summary": summary, "head_sha": head, "tree_sha": tree})
        lp.findings = "VERDICT: PASS\n"
        lp.state["findings"] = "VERDICT: PASS\n"
        lp.save()
        return "PASS"

    def review_fail(self, lp, summary, ok, dw_log, **_kw):
        head = lp.state["head_sha"]
        tree = "c" * 40
        text = ("VERDICT: FAIL\n\n## Findings\n"
                "- a.py:1 - off-by-one in the gate - wrong outcome for edge input\n")
        lp.findings = text
        lp.state["findings"] = text
        lp.state["verdict"] = "FAIL"
        lp.state["review"] = {"executor": None, "executor_provider": None,
                              "reviewer": lp.reviewer, "reviewer_provider": "openai",
                              "returncode": 0, "verdict": "FAIL", "done_when": True,
                              "head_sha": head, "tree_sha": tree}
        lp.state["round_summaries"].append({"round": lp.rnd, "verdict": "FAIL", "done_when": True,
                                           "summary": summary, "head_sha": head, "tree_sha": tree})
        lp.save()
        return "FAIL"

    def base_patches(self, author=LOGIN, reviewer="PASS"):
        """Every review_pr dependency but the verdict, the posting, the checks and the merge."""
        faces = {
            "PASS": self.review_pass,
            "FAIL": self.review_fail,
        }
        return [
            patch.object(run, "pr_view", side_effect=[info(author), info(author, state="CLOSED")]),
            patch.object(run, "viewer_login", return_value=LOGIN),
            patch.object(run, "checkout_for", return_value=self.repo),
            patch.object(run, "git", return_value=""),
            patch.object(run, "make_worktree", return_value=(self.wt, "ak/pr-7")),
            patch.object(run, "declared", return_value=None),
            patch.object(run, "exclude_junk", return_value=None),
            patch.object(gc, "disk_pressure", return_value=False),
            patch.object(run.usage, "collect", return_value={}),
            patch.object(run, "review", side_effect=faces[reviewer]),
            patch.object(run, "restore_review_checkout", return_value=None),
            patch.object(run, "launcher_world", side_effect=lambda *a, **k: nullcontext(False)),
        ]

    def posting_gh(self, events, merges=None):
        """Fake gh that posts reviews successfully and records merge calls."""
        def fake_gh(cwd, *args, **kwargs):
            if len(args) >= 2 and args[0] == "api" and "/reviews" in args[1]:
                for i, arg in enumerate(args):
                    if arg == "-f" and args[i + 1].startswith("event="):
                        events.append(args[i + 1].split("=", 1)[1])
                return 0, ""
            if args[:2] == ("pr", "merge"):
                if merges is not None:
                    merges.append(list(args))
                return 0, ""
            if args[:2] == ("pr", "view"):
                return 0, "OPEN"
            return 0, ""
        return fake_gh

    def test_own_pr_reviewer_is_from_another_provider(self):
        run_dir = self.launch_dir("20260927-0001-own-pick")
        opts = {"--review": None, "--review-pr": URL}
        events = []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(run, "gh", side_effect=self.posting_gh(events)))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["reviewer"], "astra")
        self.assertEqual(config.model(self.cfg, "astra")["provider"], "openai")
        self.assertEqual(config.model(self.cfg, "opus")["provider"], "anthropic")
        self.assertTrue(state["own_pr"])
        self.assertEqual(state["own_orchestrator"], "opus")
        self.assertEqual(events, ["COMMENT"])

    def test_own_pr_pass_merges_through_merge_turn_without_inbox(self):
        run_dir = self.launch_dir("20260927-0002-own-merge")
        opts = {"--review": None, "--review-pr": URL}
        merges, turns, inbox, events = [], [], [], []
        real_merge = run.MERGE_METHODS["squash"]

        @contextmanager
        def turn(lp, upstream, reserve=False):
            turns.append(upstream)
            yield

        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(run, "merge_turn", side_effect=turn))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertEqual(inbox, [])
        self.assertEqual(events, ["COMMENT"])
        self.assertEqual(len(merges), 1, merges)
        self.assertEqual(merges[0][:2], ["pr", "merge"])
        self.assertIn(real_merge, merges[0])
        self.assertIn("--match-head-commit", merges[0])
        self.assertIn(HEAD, merges[0])
        self.assertEqual(turns, ["origin/main"])
        self.assertNotIn("pending_inbox", state)

    def test_own_pr_pass_with_moved_head_never_merges(self):
        run_dir = self.launch_dir("20260927-0003-own-moved")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", side_effect=[
                    ({"headRefOid": HEAD, "state": "OPEN"}, ""),
                    ({"headRefOid": "d" * 40, "state": "OPEN"}, "")]))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(inbox, [])
        self.assertIn("not merged", state["merge_note"])
        self.assertIn("head changed", state["merge_note"])
        self.assertTrue(state["merge_failed"])

    def test_own_pr_pass_with_failed_checks_is_an_unfinished_merge(self):
        run_dir = self.launch_dir("20260927-0008-own-checks-fail")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "checks", return_value=(False, "required checks failed: gate")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(inbox, [])
        self.assertTrue(state["merge_failed"])
        self.assertIn("required checks failed", state["merge_note"])

    def test_closed_own_pr_ends_fail_with_findings_and_no_merge(self):
        run_dir = self.launch_dir("20260927-0004-own-fail")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "fail")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(inbox, [])
        self.assertEqual(events, ["COMMENT"])
        result = (run_dir / "result.md").read_text()
        self.assertIn("## Reviewer findings", result)
        self.assertIn("off-by-one in the gate", result)

    def test_closed_own_pr_fail_is_handed_back_like_a_failed_task_run(self):
        run_dir = self.launch_dir("20260927-0005-own-handback")
        opts = {"--review": None, "--review-pr": URL}
        events = []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(run, "gh", side_effect=self.posting_gh(events)))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "fail")
        self.assertEqual(events, ["COMMENT"])
        typed = []
        with patch.object(orch, "find", return_value={"name": "fix-api"}), \
                patch.object(watch, "type_at_prompt",
                             side_effect=lambda seat, line, *a, **k: typed.append(line) or True):
            with patch.object(run, "launcher_world") as world:
                world.return_value.__enter__.return_value = True
                world.return_value.__exit__.return_value = False
                run.announce(run.read_state(run_dir), run_dir, lambda line: None)
        self.assertEqual(len(typed), 1, typed)
        self.assertIn(f"run {run_dir.name} finished FAIL", typed[0])
        self.assertIn("off-by-one in the gate", typed[0])
        self.assertIn("Decide the next step.", typed[0])

    def test_other_pr_fail_posts_request_changes_and_ends_fail(self):
        run_dir = self.launch_dir("20260927-0009-other-fail")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author="other", reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "fail")
        self.assertFalse(state["merged"])
        self.assertEqual(events, ["REQUEST_CHANGES"])
        self.assertEqual(inbox, [])
        self.assertFalse(state["own_pr"])

    def test_other_pr_pass_asks_inbox_as_before(self):
        run_dir = self.launch_dir("20260927-0006-other-asks")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author="other", reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(len(inbox), 1)
        self.assertIn("Merge? yes/no", inbox[0][1])
        self.assertFalse(state["own_pr"])
        self.assertIn("offered to the", state["merge_note"])
        self.assertNotIn("merge_failed", state)

    def test_no_seat_pass_asks_inbox_as_before(self):
        run_dir = self.launch_dir("20260927-0007-noseat-asks", session="")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(len(inbox), 1)
        self.assertFalse(state["own_pr"])

    def test_missing_writer_stays_own_and_refuses_review(self):
        run_dir = self.launch_dir("20260927-0010-ghost-pick", session="ghost-seat")
        opts = {"--review": None, "--review-pr": URL}
        inbox, events = [], []
        with ExitStack() as mocks:
            entered = [mocks.enter_context(m)
                       for m in self.base_patches(author=LOGIN, reviewer="PASS")]
            review_mock = entered[9]
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            gh_mock = mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "ghost-seat"}):
                with self.assertRaisesRegex(config.Error, "writer"):
                    run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(review_mock.call_count, 0)
        self.assertEqual(gh_mock.call_count, 0)
        self.assertEqual(inbox, [])
        self.assertEqual(events, [])

    def test_writer_is_preserved_when_the_record_changes(self):
        run_dir = self.launch_dir("20260927-0011-own-resume")
        opts = {"--review": None, "--review-pr": URL}
        saved = run.read_state(run_dir)
        saved.update(own_pr=True, own_orchestrator="opus")
        run.save_state(run_dir, saved)
        config.save_session(self.cfg, "fix-api", "astra", ["opus", "astra"])
        events = []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(run, "gh", side_effect=self.posting_gh(events)))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertTrue(state["own_pr"])
        self.assertEqual(state["own_orchestrator"], "opus")
        self.assertEqual(state["reviewer"], "astra")
        self.assertEqual(events, ["COMMENT"])

    def test_own_pr_adopts_the_saved_background_reviewer(self):
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra", "spark"])
        run_dir = self.launch_dir("20260927-0012-own-preset")
        opts = {"--review": None, "--review-pr": URL}
        saved = run.read_state(run_dir)
        saved.update(launch_reviewer="spark")
        run.save_state(run_dir, saved)
        events = []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="FAIL"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(run, "gh", side_effect=self.posting_gh(events)))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["reviewer"], "spark")
        self.assertTrue(state["own_pr"])

    def test_preflight_captures_ownership_and_delivery(self):
        for author, session, want_own, want_line in (
                (LOGIN, "fix-api", True, "merge on PASS"),
                ("other", "fix-api", False, "review only"),
                (LOGIN, "", False, "review only")):
            with self.subTest(author=author, session=session):
                run_dir = config.RUNS / f"20260927-preflight-{author}-{session or 'noseat'}"
                run_dir.mkdir(parents=True)
                (run_dir / "log.txt").touch()
                with patch.dict(os.environ, {"AGENTKIT_SESSION": session}):
                    run.capture_launch(run_dir, {"--review-pr": URL})
                lines = []
                with patch.object(run, "pr_view", return_value=info(author)), \
                        patch.object(run, "viewer_login", return_value=LOGIN):
                    run.preflight(run_dir, {"--review-pr": URL}, lines.append)
                saved = run.read_state(run_dir)
                self.assertEqual(bool(saved.get("own_pr")), want_own)
                if want_own:
                    self.assertEqual(saved.get("own_orchestrator"), "opus")
                self.assertIn(want_line, "\n".join(lines))

    def test_preflight_refuses_own_pr_without_a_writer(self):
        run_dir = config.RUNS / "20260927-preflight-ghost"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "ghost-seat"}):
            run.capture_launch(run_dir, {"--review-pr": URL})
        with patch.object(run, "pr_view", return_value=info(LOGIN)), \
                patch.object(run, "viewer_login", return_value=LOGIN):
            with self.assertRaisesRegex(config.Error, "writer"):
                run.preflight(run_dir, {"--review-pr": URL}, lambda line: None)
        saved = run.read_state(run_dir)
        self.assertTrue(saved.get("own_pr"))
        self.assertIsNone(saved.get("own_orchestrator"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
