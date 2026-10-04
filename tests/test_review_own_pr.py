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
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gc, orch, run, watch
from agentkit import record
from fixtures.hand_in import records

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
        # An empty fake checkout still inherits the enclosing repository's Git state.
        self.stack.enter_context(patch.object(
            run, "git_out", side_effect=AssertionError("real Git in a fake checkout")))
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
        lp.state["review_records"] = records(lp.findings)
        lp.save()
        return "PASS"

    def review_fail(self, lp, summary, ok, dw_log, **_kw):
        head = lp.state["head_sha"]
        tree = "c" * 40
        text = ("VERDICT: FAIL\n\n## Findings\n"
                "- a.py:1 - off-by-one in the gate - wrong outcome for edge input\n")
        lp.findings = text
        lp.state["findings"] = text
        lp.state["review_records"] = records(text)
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
            patch.object(run, "fetch", return_value=(0, "")),
            patch.object(run, "commit_identity", return_value={"head_sha": HEAD, "tree_sha": "c" * 40}),
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

    def test_own_pr_pass_joins_the_line_without_inbox(self):
        run_dir = self.launch_dir("20260927-0002-own-merge")
        opts = {"--review": None, "--review-pr": URL}
        merges, turns, inbox, events = [], [], [], []

        def turn(lp, upstream):
            turns.append(upstream)
            return nullcontext()

        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(
                run, "gh", side_effect=self.posting_gh(events, merges)))
            mocks.enter_context(patch.object(run, "merge_lock", side_effect=turn))
            mocks.enter_context(patch.object(
                watch, "ask_inbox",
                side_effect=lambda *a, **k: inbox.append(a) or 0))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        self.assertEqual(state["state"], "waiting")
        self.assertFalse(state["merged"])
        self.assertEqual(inbox, [])
        self.assertEqual(events, ["COMMENT"])
        self.assertEqual(merges, [])
        self.assertEqual(turns, [])
        self.assertIn("line", state["waiting_on"])
        self.assertNotIn("pending_inbox", state)

    def text_review(self, author):
        run_dir = self.launch_dir(f"20260927-0009-text-{author}")
        opts = {"--review": None, "--review-pr": URL}
        events, inbox = [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=author, reviewer="PASS"):
                mocks.enter_context(m)
            mocks.enter_context(patch.object(run, "text_only_pr", return_value=True))
            mocks.enter_context(patch.object(run, "checks", return_value=(True, "")))
            mocks.enter_context(patch.object(
                run, "gh_json", return_value=({"headRefOid": HEAD, "state": "OPEN"}, "")))
            mocks.enter_context(patch.object(run, "gh", side_effect=self.posting_gh(events)))
            mocks.enter_context(patch.object(
                watch, "ask_inbox", side_effect=lambda *a, **k: inbox.append(a) or 0))
            reviewed = mocks.enter_context(patch.object(run, "review", wraps=self.review_pass))
            probed = mocks.enter_context(patch.object(run, "collect_usage", return_value={}))
            with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
                state = run.review_pr(self.cfg, run_dir, URL, opts, lambda line: None)
        return state, events, inbox, reviewed, probed

    def test_the_seats_own_wording_skips_review_and_joins_the_line(self):
        state, events, inbox, reviewed, probed = self.text_review(LOGIN)
        reviewed.assert_not_called()
        probed.assert_not_called()
        self.assertEqual(events, [])        # no review to post: none was made
        self.assertEqual(inbox, [])
        self.assertEqual(state["state"], "waiting")
        self.assertIn("line", state["waiting_on"])
        self.assertTrue(state["review"]["skipped"])
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertIn("review skipped", state["round_summaries"][-1]["summary"])

    def test_anyone_elses_wording_is_reviewed_and_asks_the_inbox(self):
        state, events, inbox, reviewed, _ = self.text_review("contributor")
        reviewed.assert_called_once()
        self.assertEqual(len(inbox), 1)
        self.assertNotIn("skipped", state.get("review") or {})

    def test_delivery_takes_a_skipped_review_only_for_the_commit_it_names(self):
        """The line's delivery gate holds skipped evidence to its commit, as a review's."""
        run.git(self.repo, "init", "-q", "-b", "main")
        run.git(self.repo, "config", "user.name", "Fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "README.md").write_text("words\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", "Fixture wording")
        state = {"review_pr": URL, "own_pr": True, "verdict": "PASS", "repo": str(self.repo),
                 "review": {**run.commit_identity(self.repo), "verdict": "PASS", "skipped": True}}
        lp = SimpleNamespace(state=state, cfg=self.cfg, scratch=False, wt=self.repo)
        run.require_review_pass(lp)
        # the lander's rebase rewrites the evidence to the tree it tested, as it does a review's
        (self.repo / "NOTICE").write_text("target moved\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", "Fixture rebased onto the target")
        saved = state["review"]
        state["review"] = {**saved, **run.commit_identity(self.repo),
                           "rebased_from": saved["head_sha"]}
        run.require_review_pass(lp)
        (self.repo / "app.py").write_text("print('code')\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", "Fixture adds code after the check")
        with self.assertRaises(run.Exhausted):
            run.require_review_pass(lp)

    def test_skipped_review_evidence_counts_only_on_the_seats_own_review(self):
        state = {"review_pr": URL, "own_pr": True, "verdict": "PASS",
                 "review": {"head_sha": HEAD, "tree_sha": "c" * 40, "verdict": "PASS",
                            "skipped": True}}
        self.assertTrue(run.review_pass(state, self.cfg))
        for change in ({"own_pr": False}, {"review_pr": None}, {"verdict": "FAIL"},
                       {"review": {**state["review"], "tree_sha": None}}):
            with self.subTest(change=change):
                self.assertFalse(run.review_pass({**state, **change}, self.cfg))

    def test_text_classification_checks_complete_commit_diff_and_both_sides_of_renames(self):
        run.git(self.repo, "init", "-q", "-b", "main")
        run.git(self.repo, "config", "user.name", "Fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "app.py").write_text("print('fixture')\n")
        (self.repo / "AGENTS.md").write_text("---\ntests: test -f MISSING\n---\n# acme\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", "Fixture base")
        base = run.git(self.repo, "rev-parse", "HEAD")
        self.assertFalse(run.text_only_pr(self.repo, base, base))
        for name in ("README.md", "README.txt", "LICENSE.text", "guide.rst", "en.po", "app.xlf", "NOTICE"):
            (self.repo / name).write_text("words\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", "Fixture wording")
        words = run.git(self.repo, "rev-parse", "HEAD")
        self.assertTrue(run.text_only_pr(self.repo, base, words))
        run.git(self.repo, "mv", "app.py", "code.md")
        run.git(self.repo, "commit", "-qm", "Fixture code rename")
        self.assertFalse(run.text_only_pr(self.repo, words, "HEAD"))
        for name, content in (("requirements.txt", b"a\n"), ("binary.md", b"a\0b")):
            (self.repo / name).write_bytes(content)
            run.git(self.repo, "add", name)
            run.git(self.repo, "commit", "-qm", "Fixture requires review")
            self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        for name in ("AGENTS.md", "docs/AGENTS.md", "other/agents.MD"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\ntests: true\ncleanup: printf fixture\n---\n# acme\n")
            run.git(self.repo, "add", name)
            run.git(self.repo, "commit", "-qm", "Fixture changes repository commands")
            self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        run.git(self.repo, "mv", "AGENTS.md", "instructions.md")
        run.git(self.repo, "commit", "-qm", "Fixture renames repository commands")
        self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        run.git(self.repo, "rm", "docs/AGENTS.md")
        run.git(self.repo, "commit", "-qm", "Fixture deletes repository commands")
        self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        # a submodule's commit or a link names code elsewhere, however its path is spelled
        # and whatever the local git settings hide
        for name, ignore in (("vendor", "all"), ("docs.md", "none")):
            with self.subTest(submodule=name, ignore=ignore):
                run.git(self.repo, "config", "diff.ignoreSubmodules", ignore)
                run.git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{base},{name}")
                (self.repo / "README.md").write_text(f"before {name}\n")
                run.git(self.repo, "add", "README.md")
                run.git(self.repo, "commit", "-qm", "Fixture adds a submodule")
                run.git(self.repo, "update-index", "--cacheinfo", f"160000,{words},{name}")
                (self.repo / "README.md").write_text(f"after {name}\n")
                run.git(self.repo, "add", "README.md")
                run.git(self.repo, "commit", "-qm", "Fixture moves the submodule and the wording")
                self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        run.git(self.repo, "config", "diff.ignoreSubmodules", "none")
        # binary bytes need review even where an attribute tells the diff to read them as text
        (self.repo / ".gitattributes").write_text("*.md diff\n")
        run.git(self.repo, "add", ".gitattributes")
        run.git(self.repo, "commit", "-qm", "Fixture forces text diffs")
        (self.repo / "forced.md").write_bytes(b"a\0b\n")
        run.git(self.repo, "add", "forced.md")
        run.git(self.repo, "commit", "-qm", "Fixture adds binary prose")
        self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        # a binary file whose name git's text output would turn into a text file's name
        for binary, lookalike in ((b"binary\r.md", b"binary\n.md"),
                                  (b"binary-\xff.md", "binary-\ufffd.md".encode())):
            with self.subTest(name=binary):
                (self.repo / os.fsdecode(lookalike)).write_text("plain words\n")
                run.git(self.repo, "add", "-A")
                run.git(self.repo, "commit", "-qm", "Fixture adds a text file")
                (self.repo / os.fsdecode(binary)).write_bytes(b"a\0b\n")
                run.git(self.repo, "add", "-A")
                run.git(self.repo, "commit", "-qm", "Fixture adds a binary lookalike")
                self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        # an AGENTS.md below the root that is a link makes its target configuration too
        (self.repo / "rules.md").write_text("---\ntests: true\n---\n")
        (self.repo / "nested").mkdir()
        (self.repo / "nested/AGENTS.md").symlink_to("../rules.md")
        run.git(self.repo, "add", "-A")
        run.git(self.repo, "commit", "-qm", "Fixture links nested instructions")
        (self.repo / "rules.md").write_text("---\ntests: false\n---\n")
        run.git(self.repo, "add", "-A")
        run.git(self.repo, "commit", "-qm", "Fixture changes them through the link")
        self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))
        (self.repo / "nested/AGENTS.md").unlink()
        run.git(self.repo, "add", "-A")
        run.git(self.repo, "commit", "-qm", "Fixture drops the link")
        (self.repo / "LICENSE").symlink_to("app.py")
        run.git(self.repo, "add", "LICENSE")
        run.git(self.repo, "commit", "-qm", "Fixture links prose to code")
        self.assertFalse(run.text_only_pr(self.repo, "HEAD^", "HEAD"))


    def test_own_pr_pass_leaves_head_verification_to_delivery(self):
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
        self.assertEqual(state["state"], "waiting")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(inbox, [])
        self.assertEqual(state["head_sha"], HEAD)
        self.assertIn("line", state["waiting_on"])
        self.assertFalse(state.get("merge_failed"))

    def test_own_pr_pass_defers_required_checks_to_delivery(self):
        run_dir = self.launch_dir("20260927-0008-own-checks-fail")
        opts = {"--review": None, "--review-pr": URL}
        merges, inbox, events = [], [], []
        with ExitStack() as mocks:
            for m in self.base_patches(author=LOGIN, reviewer="PASS"):
                mocks.enter_context(m)
            checks = mocks.enter_context(patch.object(
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
        self.assertEqual(state["state"], "waiting")
        self.assertFalse(state["merged"])
        self.assertEqual([a for a in merges if a[:2] == ["pr", "merge"]], [])
        self.assertEqual(inbox, [])
        checks.assert_not_called()
        self.assertIn("line", state["waiting_on"])

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
            with patch.object(run, "launcher_world") as world, patch.object(run, "drop_checkout"):
                world.return_value.__enter__.return_value = True
                world.return_value.__exit__.return_value = False
                run.announce(record.read_state(run_dir), run_dir, lambda line: None)
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
        saved = record.read_state(run_dir)
        saved.update(own_pr=True, own_orchestrator="opus")
        record.save_state(run_dir, saved)
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
        saved = record.read_state(run_dir)
        saved.update(launch_reviewer="spark")
        record.save_state(run_dir, saved)
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
                saved = record.read_state(run_dir)
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
        saved = record.read_state(run_dir)
        self.assertTrue(saved.get("own_pr"))
        self.assertIsNone(saved.get("own_orchestrator"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
