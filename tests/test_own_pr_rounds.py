"""Own PRs carry findings across pushes, while other PRs get one review. Offline.

Real git commits in a temporary acme checkout; GitHub, reviewer turns, seats and
processes are fakes. A fake sleep pushes the next head or closes the PR.
"""

from contextlib import ExitStack, nullcontext, redirect_stdout
import io
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
from fixtures.hand_in import submitting
from fixtures.landing import landing
from agentkit import gate, host, config, gc, menu, orch, run, worktrees, status, watch, worker
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"


class OwnPrRounds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-own-pr-rounds-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "fix-api",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1"}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / "AGENTS.md").write_text("---\nusers: none\ntests: test -f fence.txt\n---\n# acme\n")
        (self.repo / "fence.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Base")
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        self.git("checkout", "-qb", "fix-api")
        self.heads = []
        for n in range(1, 5):
            (self.repo / "fence.txt").write_text(f"fix {n}\n" * (5000 if n > 1 else 1))
            self.git("commit", "-qam", f"Fix {n}")
            self.heads.append(self.git("rev-parse", "HEAD"))
        self.pr = {"state": "OPEN", "title": "Mend the fence", "author": "owner",
                   "baseRefName": "main", "headRefOid": self.heads[0], "body": "Fix the fence"}
        self.run_dir = config.RUNS / "own-pr-rounds"
        self.run_dir.mkdir()
        (self.run_dir / "log.txt").touch()
        run.capture_launch(self.run_dir, {"--review-pr": URL})
        self.prompts, self.notices, self.events, self.merges, self.waits = [], [], [], [], []
        self.verdicts = []
        self.close = False
        for name, value in (("viewer_login", "owner"), ("checkout_for", self.repo),
                            ("fetch", (0, "")),
                            ("collect_usage", {}), ("checks", (True, "")),
                            ("process_active", True), ("scope_alive", None),
                            ("host_status_line", "fixture host")):
            self.stack.enter_context(patch.object(record if name == "process_active" else
                                                gate if name == "host_status_line" else
                                                status if name == "scope_alive" else run,
                                                name, return_value=value))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "pr_view", side_effect=lambda *_: dict(self.pr)))
        self.stack.enter_context(patch.object(run, "gh_json", side_effect=self.gh_json))
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run, "join_line", side_effect=lambda lp, _upstream, deliver:
                                             landing(lp, deliver=deliver)))
        self.stack.enter_context(patch.object(run, "merge_lock", side_effect=lambda *a, **k: nullcontext()))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.reviewer)))
        clock = self.stack.enter_context(patch.object(run, "time", wraps=time))
        clock.sleep.side_effect = self.push
        self.stack.enter_context(patch.object(run, "launcher_world", side_effect=lambda *a, **k: nullcontext(True)))
        self.stack.enter_context(patch.object(orch, "find", return_value={"name": "fix-api"}))
        self.stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.tell))
        self.stack.enter_context(patch.object(host, "frozen_cgroup", return_value=None))
        self.stack.enter_context(patch.object(watch, "step_for_run", return_value=("none", "no child", None, [])))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.resume = self.stack.enter_context(patch.object(watch, "launch_resume"))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def gh(self, cwd, *args, **_kw):
        if args[:2] == ("pr", "merge"):
            self.merges.append(args)
        if args[0] == "api":
            self.events.append(args[args.index("-f") + 3])
        return 0, ""

    def gh_json(self, _cwd, *args, **_kw):
        if args[:2] == ("api", "repos/acme/widget/pulls/7"):
            return {"state": self.pr["state"].lower(), "merged": self.pr["state"] == "MERGED",
                    "head": {"sha": self.pr["headRefOid"]}, "base": {"ref": "main"}}, ""
        return dict(self.pr), ""

    def tell(self, seat, line, *args, **_kw):
        self.notices.append(line)
        return True

    def reviewer(self, cfg, name, body, workspace, out_dir, role, session, **_kw):
        self.prompts.append(body)
        n = len(self.prompts)
        self.assertLessEqual(n, len(self.verdicts), "reviewed a head twice")
        self.assertEqual(run.git(workspace, "rev-parse", "HEAD"), self.pr["headRefOid"])
        verdict = self.verdicts[n - 1]
        text = (f"## Findings\n- fence.txt:1 - defect {n} - wrong edge outcome\n"
                if verdict == "FAIL" else "## Findings\n- none\n") + f"VERDICT: {verdict}\n"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, f"review-{n}", False

    def push(self, seconds):
        if seconds != gate.SLOT_POLL:
            return
        state = record.read_state(self.run_dir)
        self.waits.append(state)
        self.assertEqual(state["state"], "running")
        self.assertIsNone(state.get("finished_at"))
        self.assertFalse(state.get("handed_back"))
        self.assertTrue(self.notices, "the seat must receive findings before waiting for its push")
        self.assertIn(f"defect {len(self.prompts)}", self.notices[-1])
        out = io.StringIO()
        with redirect_stdout(out):
            status.cmd_status([self.run_dir.name])
        self.assertIn("waiting for", out.getvalue())
        self.assertIn("push", out.getvalue())
        with patch.object(watch, "run_last_write", return_value=time.time() - 7200):
            watch.recover_runs(self.cfg, log=lambda _: None)
        self.kill.assert_not_called()
        self.resume.assert_not_called()
        if self.close:
            self.pr["state"] = "CLOSED"
        else:
            self.pr["headRefOid"] = self.heads[len(self.prompts)]

    def review(self, verdicts):
        self.verdicts = verdicts
        return run.review_pr(self.cfg, self.run_dir, URL,
                             {"--review": None, "--review-pr": URL}, lambda _: None)

    def test_an_own_prs_first_review_is_refused_past_the_ceiling(self):
        self.pr["headRefOid"] = self.heads[1]           # 5001 changed lines of fence.txt
        state = self.review([])
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        self.assertIn("PR #7 changes 5001 lines", state["error"])
        self.assertIn("split it", state["blocked"])
        self.assertEqual((self.prompts, self.merges), ([], []))

    def test_somebody_elses_pr_is_reviewed_whatever_its_size(self):
        self.pr.update(author="stranger", headRefOid=self.heads[1])
        state = self.review(["PASS"])
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(self.prompts), 1)

    def test_an_own_pr_of_text_only_lands_whatever_its_size(self):
        self.git("checkout", "-qb", "notes", "main")
        (self.repo / "notes.md").write_text("note\n" * 500)
        self.git("add", "notes.md")
        self.git("commit", "-qm", "Notes")
        self.pr["headRefOid"] = self.git("rev-parse", "HEAD")
        state = self.review([])
        self.assertTrue(state["merged"])
        self.assertEqual(state["round_summaries"][0]["summary"], "Text and translation files only; review skipped.")
        self.assertEqual(self.prompts, [])

    def test_fail_push_pass_in_round_two_merges(self):
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(state["state"], "pass")
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertEqual(len(self.waits), 1)
        self.assertIn("defect 1", self.prompts[1])
        self.assertIn("first rule on each previous finding", self.prompts[1])
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][-1], self.heads[1])

    def test_a_push_moves_the_next_round_onto_the_installed_agentkit(self):
        moves = []

        def execv(_python, argv):
            moves.append(argv[2:])
            raise SystemExit(0)      # the resumed process reviews the pushed head

        push = self.push

        def rename_then_push(seconds):
            push(seconds)
            with record.record(self.run_dir) as current:     # the seat renamed meanwhile
                current["launched_session"] = "mend-api"

        run.time.sleep.side_effect = rename_then_push
        self.addCleanup(setattr, run, "_PICKUP_START", run._PICKUP_START)
        run._PICKUP_START = "aaa1111"           # merged while the seat was fixing
        with patch.object(run, "installed_head", return_value="bbb2222"), \
                patch.object(run.os, "execv", side_effect=execv), self.assertRaises(SystemExit):
            self.review(["FAIL", "PASS"])
        self.assertEqual(moves, [["run", "resume", self.run_dir.name]])
        self.assertEqual(len(self.prompts), 1)
        state = record.read_state(self.run_dir)
        self.assertEqual(state["pickup"]["to"], "bbb2222")
        self.assertEqual(state["own_pr_wait"], self.heads[0])   # still owed its next round
        self.assertEqual(state["launched_session"], "mend-api")

    def moved_reviews(self, told):
        """The reviewers of two rounds whose process, told `told`, moves onto new code between
        them; its launch named opus."""
        reviewers = []

        def review(cfg, name, *args, **kwargs):
            reviewers.append(name)
            return self.reviewer(cfg, name, *args, **kwargs)

        def execv(_python, argv):
            run._PICKUP_START = "bbb2222"        # what the resumed process starts on
            raise SystemExit(run.resume_run(argv[4:]))

        with record.record(self.run_dir) as current:
            current["launch_opts"] = {"--review": "opus", "--review-pr": URL}
        self.verdicts = ["FAIL", "PASS"]
        self.addCleanup(setattr, run, "_PICKUP_START", run._PICKUP_START)
        run._PICKUP_START = "aaa1111"
        with patch.object(run, "installed_head", return_value="bbb2222"), \
                patch.object(run, "ready_order", return_value=["astra", "opus"]), \
                patch.object(run.os, "execv", side_effect=execv), \
                patch.object(run, "drive", side_effect=lambda *a, job, **k: job()), \
                patch.object(run.box, "check"), \
                patch.object(worker, "call", side_effect=submitting(review)), \
                self.assertRaises(SystemExit):
            run.review_pr(self.cfg, self.run_dir, URL, {"--review": told, "--review-pr": URL},
                          lambda _: None)
        self.assertTrue(record.read_state(self.run_dir)["merged"])
        return reviewers

    def test_the_reviewer_its_process_was_told_reviews_on_after_the_move(self):
        self.assertEqual(self.moved_reviews("opus"), ["opus", "opus"])

    def test_a_resumed_review_that_was_told_no_reviewer_still_picks_after_the_move(self):
        # a crash resume drops the launch's --review; the move keeps that, not the launch's
        self.assertEqual(self.moved_reviews(None), ["astra", "astra"])

    def test_three_fails_end_with_the_last_findings(self):
        state = self.review(["FAIL", "FAIL", "FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(len(self.waits), 2)
        self.assertIn("defect 2", self.prompts[2])
        self.assertFalse(state["merged"])
        self.assertEqual(self.merges, [])
        result = (self.run_dir / "result.md").read_text()
        self.assertIn("defect 3", result)
        self.assertNotIn("defect 1", result)
        run.announce(state, self.run_dir, lambda _: None, self.cfg)
        self.assertIn("defect 3", self.notices[-1])
        self.assertIn("three rounds spent", self.notices[-1])

    def test_closed_pr_ends_the_run(self):
        self.close = True
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(len(self.waits), 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertIsNotNone(state["finished_at"])
        self.assertIn("closed", state["error"].lower())
        self.assertIn("defect 1", (self.run_dir / "result.md").read_text())
        self.assertEqual(self.merges, [])

    def test_other_pr_fail_keeps_its_single_review(self):
        self.pr["author"] = "contributor"
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.waits, [])
        self.assertEqual(self.events, ["event=REQUEST_CHANGES"])

    def test_wait_resumes_without_repeating_the_round_or_notice(self):
        clock = run.time

        def die(seconds):
            if seconds == gate.SLOT_POLL:
                raise InterruptedError("fixture: loop died while waiting")

        clock.sleep.side_effect = die
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        self.assertEqual(saved["own_pr_round_told"], 1)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        clock.sleep.side_effect = self.push
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(len(self.waits), 1)

    def test_busy_seat_gets_the_findings_once_before_the_push(self):
        sends = []

        def busy(seat, line, *args, **kw):
            sends.append(kw.get("typed"))
            if len(sends) == 1:
                kw["receipt"]({"fixture": "typed"})
                return False
            return self.tell(seat, line)

        def wait(seconds):
            if len(sends) > 1:
                self.push(seconds)

        run.time.sleep.side_effect = wait
        with patch.object(watch, "type_at_prompt", side_effect=busy):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(sends, [None, {"fixture": "typed"}])
        self.assertEqual(len(self.notices), 1)

    def test_failed_github_read_keeps_waiting_for_the_next_head(self):
        reads = 0

        def unavailable(url):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise config.Error("fixture: GitHub unavailable")
            return dict(self.pr)

        with patch.object(run, "pr_view", side_effect=unavailable):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.notices), 1)

    def test_default_status_names_the_push_wait(self):
        def push(seconds):
            if seconds != gate.SLOT_POLL:
                return
            for args in ([], ["--plain"], ["--why"], [self.run_dir.name]):
                with self.subTest(args=args), redirect_stdout(io.StringIO()) as out:
                    status.cmd_status(args)
                self.assertIn("waiting for", out.getvalue())
                self.assertIn("push", out.getvalue())
                if "--plain" not in args:
                    self.assertIn("round 1/3", out.getvalue())
            self.push(seconds)

        run.time.sleep.side_effect = push
        self.assertTrue(self.review(["FAIL", "PASS"])["merged"])

    def test_push_wait_is_never_reported_as_silent(self):
        def push(seconds):
            if seconds != gate.SLOT_POLL:
                return
            state = record.read_state(self.run_dir)
            with patch.object(watch, "run_last_write", return_value=time.time() - 7200):
                bare = {**state, "own_pr_wait": None}
                self.assertEqual(menu.silent_for_run(self.run_dir, bare), "2h")
                self.assertIsNone(menu.silent_for_run(self.run_dir, state))
                with patch.object(record, "process_active", return_value=False):
                    self.assertEqual(menu.silent_for_run(self.run_dir, state), "2h")
                for silent in (None, {self.run_dir.name: "2h"}):
                    found = watch.session_state(
                        "fix-api", session={"name": "fix-api"}, cfg=self.cfg, live={},
                        records=[(self.run_dir, state)], auth_out={}, gh_out={}, token_out={},
                        silent=silent)
                    self.assertEqual(found["word"], "working")
                    self.assertNotIn("silent", found["reason"])
            self.push(seconds)

        run.time.sleep.side_effect = push
        self.assertTrue(self.review(["FAIL", "PASS"])["merged"])

    def assert_resumed_post_finishes_round_one(self):
        saved = record.read_state(self.run_dir)
        self.assertEqual(len(saved["round_summaries"]), 1)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([(s["round"], s["head_sha"]) for s in state["round_summaries"]],
                         [(1, self.heads[0]), (2, self.heads[1])])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(len(self.waits), 1)
        self.assertEqual(self.merges[0][-1], self.heads[1])

    def test_killed_while_posting_resumes_the_recorded_round(self):
        def killed(cwd, *args, **_kw):
            if args[0] == "api":
                raise InterruptedError("fixture: loop died while posting")
            return self.gh(cwd, *args)

        with patch.object(run, "gh", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        self.assert_resumed_post_finishes_round_one()
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])

    def test_killed_after_posting_resumes_before_the_push_wait(self):
        post = run.post_review

        def killed(lp, url, verdict, **_kw):
            post(lp, url, verdict)
            raise InterruptedError("fixture: loop died after posting")

        with patch.object(run, "post_review", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        self.assert_resumed_post_finishes_round_one()
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])

    def test_failed_post_retries_without_spending_another_round(self):
        with patch.object(run, "gh", return_value=(1, "HTTP 502: fixture")):
            state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "error")
        self.assertTrue(worktrees.resume_holds_tree(state, self.run_dir))
        self.assert_resumed_post_finishes_round_one()

    def test_round_three_pass_with_a_failed_post_can_still_merge(self):
        def failed(cwd, *args, **_kw):
            if args[0] == "api" and len(self.prompts) == 3:
                return 1, "HTTP 502: fixture"
            return self.gh(cwd, *args)

        with patch.object(run, "gh", side_effect=failed):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(state["state"], "error")
        state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "FAIL", "PASS"])
        self.assertEqual(len(self.prompts), 3)
        self.assertEqual(self.merges[0][-1], self.heads[2])

    def assert_moved_round_merges(self, state):
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertEqual([(s["round"], s["head_sha"]) for s in state["round_summaries"]],
                         list(enumerate(self.heads[:3], 1)))
        self.assertEqual(len(self.prompts), 3)
        self.assertIn("first rule on each previous finding", self.prompts[2])
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][-1], self.heads[2])

    def test_push_during_review_advances_with_the_recorded_findings(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 2:
                self.pr["headRefOid"] = self.heads[2]
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assert_moved_round_merges(state)
        self.assertIn("defect 2", self.prompts[2])
        self.assertEqual(len(self.notices), 2)

    def test_push_during_pass_reviews_the_new_head_before_merging(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 2:
                self.pr["headRefOid"] = self.heads[2]
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "PASS", "PASS"])
        self.assert_moved_round_merges(state)
        self.assertEqual(len(self.notices), 1)

    def test_pending_round_resumes_after_a_push_during_review(self):
        def killed(lp, url, verdict, **_kw):
            if len(self.prompts) == 2:
                self.pr["headRefOid"] = self.heads[2]
                raise InterruptedError("fixture: loop died before posting the moved head")
            return post(lp, url, verdict)

        post = run.post_review
        with patch.object(run, "post_review", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(record.read_state(self.run_dir)["own_pr_round_pending"], 2)
        self.assert_moved_round_merges(self.review(["FAIL", "FAIL", "PASS"]))
        self.assertIn("defect 2", self.prompts[2])

    def test_failed_post_resumes_on_a_new_head(self):
        def failed(cwd, *args, **_kw):
            if args[0] == "api" and len(self.prompts) == 2:
                return 1, "HTTP 502: fixture"
            return self.gh(cwd, *args)

        with patch.object(run, "gh", side_effect=failed):
            state = self.review(["FAIL", "PASS", "PASS"])
        self.assertEqual(state["state"], "error")
        self.pr["headRefOid"] = self.heads[2]
        self.assert_moved_round_merges(self.review(["FAIL", "PASS", "PASS"]))

    def test_closed_pr_settles_a_pending_round(self):
        with patch.object(run, "gh", return_value=(1, "HTTP 502: fixture")):
            self.assertEqual(self.review(["FAIL"])["state"], "error")
        self.pr["state"] = "CLOSED"
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertIsNotNone(state["finished_at"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertIn("closed", state["error"].lower())
        self.assertIn("defect 1", (self.run_dir / "result.md").read_text())
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.events, [])
        self.assertEqual(self.merges, [])

    def test_push_during_round_three_ends_without_a_fourth_review(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 3:
                self.pr["headRefOid"] = self.heads[3]
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIsNotNone(state["finished_at"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertIn("head changed", state["error"])
        self.assertEqual(len(self.prompts), 3)
        self.assertEqual(self.merges, [])

    def test_killed_after_merge_settles_without_another_merge(self):
        merge = run.merge_own_pr

        def killed(lp, url, **_kw):
            merge(lp, url)
            self.pr["state"] = "MERGED"
            raise InterruptedError("fixture: loop died after merging")

        with patch.object(run, "merge_own_pr", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertFalse(state.get("merge_failed"))
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.merges), 1)


    def test_a_crash_before_the_new_heads_review_leaves_it_to_be_reviewed(self):
        def dies_once_checked_out(*_args, **_kw):
            if record.read_state(self.run_dir).get("head_sha") == self.heads[1]:
                raise InterruptedError("the process died before the new head's review")
            return {}

        with patch.object(run, "collect_usage", side_effect=dies_once_checked_out), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = record.read_state(self.run_dir)
        self.assertEqual(run.git(state["worktree"], "rev-parse", "HEAD"), self.heads[1])
        self.assertNotIn("review", state)      # the old head's review went with its round
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.prompts), 2)

    def test_a_crash_right_after_checking_out_the_new_head_is_resumed(self):
        git = run.git

        def dies_after_reset(cwd, *args, **kw):
            result = git(cwd, *args, **kw)
            if args == ("reset", "--hard", self.heads[1]):
                raise InterruptedError("the process died after the reset, before recording it")
            return result

        with patch.object(run, "git", side_effect=dies_after_reset), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["head_sha"], self.heads[1])
        self.assertTrue(state["merged"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
