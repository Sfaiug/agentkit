"""Own PRs share the landing line: independently green changes cannot land a red stack.

Offline: real Git and the declared fixture suite, fake GitHub, reviewers and seats.
"""

from contextlib import nullcontext, redirect_stdout
import io
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gc, land, record, run, watch, worker
from fixtures.hand_in import submitting
from test_lander import LanderFixture

SUITE = "test ! -f first.txt || test ! -f second.txt"


class OwnPrLine(LanderFixture, unittest.TestCase):
    def setUp(self):
        turn, do_merge = worker.turn, run.do_merge
        super().setUp()
        self.stack.enter_context(patch.object(worker, "turn", side_effect=turn))
        self.stack.enter_context(patch.object(run, "do_merge", side_effect=do_merge))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        (self.repo / "AGENTS.md").write_text(f"---\nusers: none\ntests: {SUITE}\n---\n")
        self.commit("suite for the combined changes")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        self.prs, self.reviews, self.merges, self.notices = {}, [], [], []
        for name, value in (("viewer_login", "owner"), ("checkout_for", self.repo),
                            ("collect_usage", {}), ("ready_order", ["astra"]),
                            ("post_review", True), ("checks", (True, ""))):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "pr_view", side_effect=self.view))
        self.stack.enter_context(patch.object(run, "gh_json", side_effect=self.gh_json))
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.reviewer)))
        self.stack.enter_context(patch.object(run, "launcher_world", side_effect=lambda *_: nullcontext(True)))
        self.stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.tell))
        self.stack.enter_context(patch.object(run.orch, "find", return_value={"name": "fix-api"}))
        fetch = run.fetch

        def local_fetch(repo, remote, *args, **kw):
            return (0, "") if any(arg.startswith("pull/") for arg in args) else fetch(repo, remote, *args, **kw)

        self.stack.enter_context(patch.object(run, "fetch", side_effect=local_fetch))

    def tell(self, _seat, text, *_args, **_kw):
        self.notices.append(text)
        return True

    def check(self, cmds, cwd, log_path, *args, **kw):
        self.checks.append((list(cmds), str(cwd), str(log_path)))
        return self.gate_run(cmds, cwd, log_path, *args, **kw)

    def reviewer(self, _cfg, _name, body, _wt, out, *_args, **_kw):
        self.reviews.append(body)
        out.mkdir(parents=True, exist_ok=True)
        text = "VERDICT: PASS\n## Findings\n- none\n"
        (out / "final.md").write_text(text)
        return 0, text, "fixture-review", False

    def view(self, url):
        pr = self.prs[url]
        return {"state": pr["state"], "headRefOid": pr["head"], "baseRefName": "main",
                "author": "owner", "title": "Mend the fence", "body": "Fix the fence"}

    def gh_json(self, _cwd, *args, **_kw):
        if "graphql" in args:
            return "Mend the fence", ""
        url = next((url for url in self.prs if url in args), None)
        if url:
            return self.view(url), ""
        number = args[1].rsplit("/", 1)[-1]
        pr = self.prs[f"https://github.com/acme/widget/pull/{number}"]
        return {"state": pr["state"].lower(), "merged": pr["state"] == "MERGED",
                "head": {"sha": pr["head"], "ref": pr["branch"],
                         "repo": {"clone_url": str(self.remote)}},
                "base": {"ref": "main"}}, ""

    def gh(self, _cwd, *args, **_kw):
        self.assertEqual(args[:2], ("pr", "merge"))
        url = args[2]
        pr = self.prs[url]
        pinned = args[args.index("--match-head-commit") + 1]
        remote_head = run.git(self.remote, "rev-parse", pr["branch"])
        if remote_head != pinned:
            return 1, "head changed"
        tree = run.git(self.repo, "rev-parse", f"{pinned}^{{tree}}")
        self.assertIsNotNone(land.passed(self.turn, tree), "merged an untested tree")
        run.git(self.repo, "fetch", "origin", "main")
        run.git(self.repo, "checkout", "main")
        run.git(self.repo, "reset", "--hard", "origin/main")
        run.git(self.repo, "merge", "--squash", pinned)
        self.assertEqual(run.git(self.repo, "write-tree"), tree)
        self.commit("land the tested tree")
        run.git(self.repo, "push", "origin", "main")
        pr.update(state="MERGED", head=pinned)
        self.merges.append((url, pinned, tree))
        return 0, ""

    def own_pr(self, name, number):
        branch = f"feature/{name}"
        run.git(self.repo, "checkout", "-b", branch, self.base)
        (self.repo / f"{name}.txt").write_text(name + "\n")
        self.commit(name)
        run.git(self.repo, "push", "origin", branch)
        url = f"https://github.com/acme/widget/pull/{number}"
        self.prs[url] = dict(branch=branch, head=run.git(self.repo, "rev-parse", "HEAD"), state="OPEN")
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "log.txt").touch()
        with patch.dict(run.os.environ, {config.SESSION_ENV: "fix-api"}):
            run.capture_launch(directory, {"--review-pr": url})
        return directory, url

    def review(self, directory, url):
        return run.review_pr(self.cfg, directory, url, {"--review": None, "--review-pr": url}, lambda _: None)

    def push_fix(self, url, rename=False):
        pr = self.prs[url]
        run.git(self.repo, "checkout", pr["branch"])
        if rename:
            run.git(self.repo, "mv", "second.txt", "repaired.txt")
        else:
            (self.repo / "fix.txt").write_text("new seat push\n")
        self.commit("the seat's fix")
        run.git(self.repo, "push", "origin", pr["branch"])
        pr["head"] = run.git(self.repo, "rev-parse", "HEAD")

    def test_review_round_starts_no_suite(self):
        directory, url = self.own_pr("first", 1)
        with patch.object(run, "gh", return_value=(0, "")):
            state = self.review(directory, url)
        self.assertEqual(self.checks, [], "a review round ran the landing suite")
        self.assertEqual(state["state"], "waiting")
        self.assertIsNone(state["review"]["done_when"])
        self.assertNotIn("final_check", state)
        self.assertIn("runs once at landing", self.reviews[0])
        self.assertEqual(self.merges, [])

    def test_two_changes_that_pass_alone_never_both_merge(self):
        first, first_url = self.own_pr("first", 1)
        second, second_url = self.own_pr("second", 2)
        for directory, url in ((first, first_url), (second, second_url)):
            state = self.review(directory, url)
            wt = Path(state["worktree"])
            self.assertFalse((wt / "first.txt").exists() and (wt / "second.txt").exists())
            self.assertEqual(state["state"], "waiting")
            self.assertEqual(state["waiting_on"]["line"], self.turn.name)
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertIn("fix", self.wait(second))
        self.assertEqual(len(self.checks), 2)
        passed = self.review(first, first_url)
        self.assertTrue(passed["merged"])
        self.assertEqual(len(self.checks), 2, "delivery repeated the suite")
        self.assertEqual(len(self.reviews), 2, "delivery repeated the review")
        self.assertEqual(self.merges[0][1], run.git(Path(passed["worktree"]), "rev-parse", "HEAD"))
        self.assertNotEqual(self.merges[0][1], passed["round_summaries"][0]["head_sha"])
        with patch.object(run, "wait_for_own_pr", return_value=False):
            failed = self.review(second, second_url)
        self.assertEqual(failed["verdict"], "FAIL")
        self.assertEqual(failed["own_pr_wait"], self.prs[second_url]["head"])
        self.assertIn(SUITE, failed["findings"])
        run.tell_own_pr_round(self.cfg, second, failed, lambda _: None)
        self.assertTrue(self.notices)
        self.assertIn("Fix the findings and push", self.notices[-1])
        self.assertEqual(len(self.merges), 1)
        self.assertFalse(record.read_state(second)["merged"])
        self.assertFalse(list(config.WT.glob("land-*")))

    def test_a_red_tree_goes_back_to_its_seat_and_the_push_is_checked(self):
        directory, url = self.own_pr("second", 1)
        self.review(directory, url)
        self.advance(**{"first.txt": "first\n"})
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        checks = len(self.checks)

        def push(seconds):
            if seconds != run.SLOT_POLL:
                return
            self.assertTrue(self.notices, "the seat received no landing failure")
            self.assertIn("final check failed at landing", self.notices[-1])
            self.push_fix(url, rename=True)

        with patch.object(run.time, "sleep", side_effect=push):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertIn("Landing failed", self.reviews[-1])
        self.assertEqual(len(self.checks), checks, "the seat's next review ran a suite")
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.checks), checks + 1)
        self.assertEqual(len(self.reviews), 2)

    def test_a_changed_target_keeps_its_place_and_checks_the_new_tree(self):
        directory, url = self.own_pr("first", 1)
        state = self.review(directory, url)
        joined = state["waiting_on"]["joined"]
        land.check_line(self.turn)
        self.advance(**{"later.txt": "later\n"})
        state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["waiting_on"]["joined"], joined)
        self.assertNotIn("land", state["waiting_on"])
        self.assertEqual(self.merges, [])
        land.check_line(self.turn)
        self.assertTrue(self.review(directory, url)["merged"])
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(len(self.reviews), 1)

    def test_a_seats_new_head_is_reviewed_instead_of_overwritten(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        self.advance()
        land.check_line(self.turn)
        self.push_fix(url)
        newest = self.prs[url]["head"]
        state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["head_sha"], newest)
        self.assertEqual(run.git(self.remote, "rev-parse", self.prs[url]["branch"]), newest)
        self.assertEqual(len(self.reviews), 2)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.merges, [])

    def test_a_seat_push_racing_the_tested_push_is_protected_by_the_lease(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        self.advance()
        land.check_line(self.turn)
        git_out = run.git_out

        def race(cwd, *args, **kw):
            if args[0] == "push" and Path(cwd) != self.repo:
                self.push_fix(url)
            return git_out(cwd, *args, **kw)

        with patch.object(run, "git_out", side_effect=race):
            with self.assertRaisesRegex(config.Error, "pushing the tested PR head failed"):
                self.review(directory, url)
        self.assertEqual(run.git(self.remote, "rev-parse", self.prs[url]["branch"]), self.prs[url]["head"])
        self.assertEqual(self.merges, [])
        self.assertEqual(len(self.checks), 1)

    def test_a_push_that_outlives_its_receipt_resumes_without_another_suite(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        self.advance()
        land.check_line(self.turn)
        git_out = run.git_out

        def killed(cwd, *args, **kw):
            answer = git_out(cwd, *args, **kw)
            if args[0] == "push":
                self.prs[url]["head"] = run.git(self.remote, "rev-parse", self.prs[url]["branch"])
                raise InterruptedError("the push completed before the run died")
            return answer

        with patch.object(run, "git_out", side_effect=killed):
            with self.assertRaises(InterruptedError):
                self.review(directory, url)
        self.assertTrue(self.review(directory, url)["merged"])
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(len(self.reviews), 1)

    def test_a_failed_required_check_returns_to_the_prs_seat(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        with patch.object(run, "checks", return_value=(False, "required checks failed: fence")), \
                patch.object(run, "wait_for_own_pr", return_value=False):
            state = self.review(directory, url)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertIn("required checks failed: fence", state["findings"])
        self.assertIn("own_pr_wait", state)
        self.assertEqual(self.merges, [])
        self.assertEqual(len(self.checks), 1)

    def test_a_delivery_refusal_records_an_ending(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        with patch.object(run, "checks", return_value=(False, "cannot read required checks")):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merge_failed"])
        self.assertIsNotNone(state["finished_at"])
        self.assertNotIn("waiting_on", state)
        self.assertEqual(self.merges, [])

    def test_somebody_elses_pr_runs_its_suite_in_its_review(self):
        # no line lands it, only the inbox's yes: a red suite is never offered
        run.git(self.repo, "checkout", "-b", "feature/both", self.base)
        for name in ("first", "second"):
            (self.repo / f"{name}.txt").write_text(name + "\n")
        self.commit("both halves")
        run.git(self.repo, "push", "origin", "feature/both")
        url = "https://github.com/acme/widget/pull/9"
        self.prs[url] = dict(branch="feature/both", head=run.git(self.repo, "rev-parse", "HEAD"),
                             state="OPEN")
        directory = config.RUNS / "both"
        directory.mkdir()
        (directory / "log.txt").touch()
        with patch.dict(run.os.environ, {config.SESSION_ENV: ""}):
            run.capture_launch(directory, {"--review-pr": url})
        with patch.object(watch, "ask_inbox", side_effect=AssertionError("offered for merge")):
            state = self.review(directory, url)
        self.assertFalse(state["own_pr"])
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(self.merges, [])

    def test_a_delivery_error_keeps_the_checkout_its_retry_delivers_from(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        api = self.gh_json
        down = lambda cwd, *args, **kw: ((None, "HTTP 503") if args[:1] == ("api",)
                                         else api(cwd, *args, **kw))
        with patch.object(run, "gh_json", side_effect=down), self.assertRaises(config.Error):
            self.review(directory, url)
        # drive records the error, and the seat's hand-back cleans up after it
        state = run.mark_state(directory, "error", "cannot verify the PR before delivery")
        run.settle_run({**state, "handed_back": True}, directory)
        self.assertTrue(Path(state["worktree"]).is_dir())
        state = self.review(directory, url)
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.merges), 1)

    def test_a_landing_failure_recorded_just_before_a_crash_lets_the_next_head_be_reviewed(self):
        directory, url = self.own_pr("first", 1)
        def posted(lp, *_args, **_kw):
            lp.state["review_posted"] = True
            lp.write()
            raise InterruptedError("the process died after posting")
        with patch.object(run, "post_review", side_effect=posted), \
                self.assertRaises(InterruptedError):
            self.review(directory, url)
        self.advance()
        self.push_fix(url)
        newest = self.prs[url]["head"]
        self.assertEqual(self.review(directory, url)["state"], "waiting")
        land.check_line(self.turn)
        write = run.Loop.write

        def dies_after_the_failure(lp):
            answer = write(lp)
            if lp.state.get("verdict") == "FAIL" and lp.state.get("own_pr_wait"):
                raise InterruptedError("the process died after recording the failure")
            return answer

        with patch.object(run.Loop, "write", dies_after_the_failure), \
                self.assertRaises(InterruptedError):
            self.review(directory, url)
        self.assertNotIn("own_pr_round_pending", record.read_state(directory))
        self.assertEqual(self.review(directory, url)["head_sha"], newest)
        self.assertEqual(self.merges, [])

    def fetch_dies_on_the_fix(self, red_suite):
        """A landing goes red -- its suite, or its required checks -- the seat pushes a fix, and
        the process dies fetching it: the next attempt still reviews that fix."""
        directory, url = self.own_pr("second", 1)
        with patch.object(run, "gh", return_value=(0, "")):
            self.assertEqual(self.review(directory, url)["state"], "waiting")
        if red_suite:
            self.advance(**{"first.txt": "first\n"})
        land.check_line(self.turn)
        failed = (nullcontext() if red_suite else
                  patch.object(run, "checks", return_value=(False, "required checks failed: fence")))
        with failed, patch.object(run, "wait_for_own_pr", return_value=False):
            self.assertEqual(self.review(directory, url)["verdict"], "FAIL")
        self.push_fix(url, rename=True)
        newest, fetch = self.prs[url]["head"], run.fetch

        def dies(repo, remote, *args, **kw):
            if any(arg.startswith("pull/") for arg in args):
                raise InterruptedError("the process died fetching the seat's fix")
            return fetch(repo, remote, *args, **kw)

        with patch.object(run, "fetch", side_effect=dies), self.assertRaises(InterruptedError):
            self.review(directory, url)
        state = self.review(directory, url)
        self.assertEqual((state["head_sha"], state["state"]), (newest, "waiting"))
        self.assertEqual(len(self.reviews), 2)
        self.assertEqual(self.merges, [])

    def test_a_fetch_that_dies_on_the_fix_for_a_red_suite_leaves_it_to_be_reviewed(self):
        self.fetch_dies_on_the_fix(red_suite=True)

    def test_a_fetch_that_dies_on_the_fix_for_red_checks_leaves_it_to_be_reviewed(self):
        self.fetch_dies_on_the_fix(red_suite=False)

    def test_an_earlier_rounds_push_never_overwrites_a_newer_seat_push(self):
        directory, url = self.own_pr("first", 1)
        with patch.object(run, "gh", return_value=(0, "")):
            self.assertEqual(self.review(directory, url)["state"], "waiting")
        self.advance()
        land.check_line(self.turn)
        git_out = run.git_out

        def pushed(cwd, *args, **kw):
            result = git_out(cwd, *args, **kw)
            if args[0] == "push" and Path(cwd) != self.repo and result[0] == 0:
                self.prs[url]["head"] = run.git(self.remote, "rev-parse", self.prs[url]["branch"])
            return result

        with patch.object(run, "git_out", side_effect=pushed), \
                patch.object(run, "checks", return_value=(False, "required checks failed: fence")), \
                patch.object(run, "wait_for_own_pr", return_value=False):
            earlier = self.review(directory, url)["delivery_sha"]
        run.git(self.repo, "checkout", self.prs[url]["branch"])
        run.git(self.repo, "reset", "--hard", earlier)
        self.push_fix(url)
        self.assertEqual(self.review(directory, url)["state"], "waiting")
        land.check_line(self.turn)
        # the seat withdraws its fix with a newer force-push while this round waits
        run.git(self.repo, "checkout", self.prs[url]["branch"])
        run.git(self.repo, "reset", "--hard", earlier)
        run.git(self.repo, "push", "--force", "origin", self.prs[url]["branch"])
        self.prs[url]["head"] = earlier
        with patch.object(run, "wait_for_own_pr", return_value=False):
            self.review(directory, url)
        self.assertEqual(self.merges, [])
        self.assertEqual(run.git(self.remote, "rev-parse", self.prs[url]["branch"]), earlier)

    def test_a_merge_recorded_just_before_a_crash_is_finished_never_rejoined(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        write = run.Loop.write

        def dies_once_merged(lp):
            answer = write(lp)
            if lp.state.get("merged"):
                raise InterruptedError("the process died after recording the merge")
            return answer

        with patch.object(run.Loop, "write", dies_once_merged), \
                self.assertRaises(InterruptedError):
            self.review(directory, url)
        self.assertTrue(record.read_state(directory)["merged"])
        self.advance(**{"later.txt": "another delivery\n"})
        state = self.review(directory, url)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertNotIn("waiting_on", state)
        self.assertEqual(len(self.merges), 1)

    def test_a_red_target_goes_back_to_the_prs_seat_and_its_repair_lands(self):
        # a solo seat's PR, which no repair run could ever serve
        seat = config.session_path("fix-api")
        seat.write_text(json.dumps({**json.loads(seat.read_text()), "solo": True}))
        (self.repo / "AGENTS.md").write_text("---\nusers: none\ntests: test ! -f broken.txt\n---\n")
        self.commit("declare the target check")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        directory, url = self.own_pr("first", 1)
        pr = self.prs[url]
        (self.repo / "broken.txt").write_text("broken\n")
        self.commit("the branch has the same failure")
        run.git(self.repo, "push", "origin", pr["branch"])
        pr["head"] = run.git(self.repo, "rev-parse", "HEAD")
        self.advance(**{"broken.txt": "broken\n"})
        with patch.object(run, "gh", return_value=(0, "")), \
                patch.object(watch, "seat_closed", return_value=False), \
                patch.object(run, "prepare", side_effect=AssertionError("solo seat started a repair run")), \
                patch.object(run, "wait_for_own_pr", side_effect=lambda cfg, directory, url, state, log:
                             self.prs[url]["head"] != state["head_sha"]):
            state = self.review(directory, url)
            if state["state"] == "waiting":
                land.check_line(self.turn)
                state = self.review(directory, url)
            self.assertEqual(state["verdict"], "FAIL")
            run.git(self.repo, "checkout", pr["branch"])
            run.git(self.repo, "fetch", "origin", "main")
            run.git(self.repo, "merge", "--no-edit", "origin/main")
            run.git(self.repo, "rm", "broken.txt")
            self.commit("the seat repairs the target in its PR")
            run.git(self.repo, "push", "origin", pr["branch"])
            pr["head"] = run.git(self.repo, "rev-parse", "HEAD")
            self.assertEqual(run.git_out(self.repo, "diff", "--quiet", "HEAD")[0], 0)
            self.assertFalse((self.repo / "broken.txt").exists())
            state = self.review(directory, url)
            self.assertEqual(state["head_sha"], pr["head"])
            self.assertEqual(len(self.reviews), 2)
            if state["state"] == "waiting":
                land.check_line(self.turn)
                state = self.review(directory, url)
            self.assertTrue(state["merged"],
                            f"the repaired PR never lands: verdict={state['verdict']}, "
                            f"wait={state.get('own_pr_wait')}, suite calls={len(self.checks)}, "
                            f"finding={state.get('final_check')}")

    def test_a_pr_mending_the_target_lands_past_a_repair_that_failed(self):
        suite = "test ! -f broken.txt"
        (self.repo / "AGENTS.md").write_text(f"---\nusers: none\ntests: {suite}\n---\n")
        self.commit("declare the target check")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        self.advance(**{"broken.txt": "broken\n"})
        run.fetch(self.repo, "origin", "main", check=True)
        tip = run.git(self.repo, "rev-parse", "origin/main")
        tree = run.git(self.repo, "rev-parse", "origin/main^{tree}")
        repair = config.RUNS / "target-repair"
        repair.mkdir()
        record.save_state(repair, {"run_id": repair.name, "state": "fail", "merged": False,
                                  "repair_tip": tip, "repo": str(self.repo)})
        self.assertTrue(run.repair_open(record.read_state(repair), tip))
        land.note(self.turn, [], repair.name, red={tree: {
            "run": repair.name, "probe": {"sha": tip, "command": suite, "check": f"{suite}  # once",
                                         "text": f"{suite} fails on origin/main at {tip}"}}})
        directory, url = self.own_pr("first", 1)
        pr = self.prs[url]
        run.git(self.repo, "merge", "--no-edit", "origin/main")
        run.git(self.repo, "rm", "broken.txt")
        self.commit("the seat takes over the failed repair in its own PR")
        run.git(self.repo, "push", "origin", pr["branch"])
        pr["head"] = run.git(self.repo, "rev-parse", "HEAD")
        self.assertFalse((self.repo / "broken.txt").exists())
        with patch.object(run, "gh", return_value=(0, "")):
            state = self.review(directory, url)
            if state["state"] == "waiting":
                for _ in range(3):
                    land.check_line(self.turn)
                state = self.review(directory, url)
            self.assertTrue(state["merged"],
                            f"the target repair is stuck in {state['state']} behind an ended "
                            f"repair run; suite calls={len(self.checks)}, wait={state.get('waiting_on')}")

    def test_a_review_parked_in_its_line_is_no_success_until_it_lands(self):
        directory, url = self.own_pr("first", 1)
        with patch.object(run, "run_slot", side_effect=lambda *_: nullcontext()), \
                patch.object(run.history, "Sampler"), \
                patch.object(run.history, "sample_rss", return_value=None), \
                patch.object(run, "settle_run"), patch.object(run, "stop_run_tree"), \
                patch.object(run, "finish", return_value=0), \
                patch.object(run, "gh", return_value=(0, "")):
            rc = run.review_pr_main(self.cfg, {"--review": None, "--review-pr": url},
                                    {"--bg": False}, ["--review-pr", url], directory)
        self.assertEqual((rc, record.read_state(directory)["state"]), (1, "waiting"))

    def test_a_terminal_follows_its_review_to_the_ending_as_a_task_run_does(self):
        url = "https://github.com/acme/widget/pull/1"
        followed = []
        with patch.object(run, "foreground_cli", return_value=True), \
                patch.object(run, "prepare"), \
                patch.object(run, "spawn_bg", return_value=0) as spawned, \
                patch.object(run, "follow_run",
                             side_effect=lambda directory, _cfg, _offset: followed.append(directory) or 0), \
                patch.object(run, "drive", side_effect=AssertionError("reviewed in the terminal")):
            self.assertEqual(run.review_pr_main(self.cfg, {"--review": None, "--review-pr": url},
                                                {"--bg": False}, ["--review-pr", url], None), 0)
        self.assertEqual(spawned.call_args.args[1], ["--review-pr", url])
        self.assertEqual(followed, [spawned.call_args.args[0]])

    def test_a_terminal_resuming_a_review_follows_it_too(self):
        directory, url = self.own_pr("first", 1)
        with patch.object(run, "gh", return_value=(0, "")):
            self.review(directory, url)
        state = record.read_state(directory)
        state.pop("waiting_on", None)
        state.update(state="interrupted", recovery_pending=True)
        record.save_state(directory, state)
        with patch.object(run, "foreground_cli", return_value=True), \
                patch.object(run, "spawn_bg", return_value=0) as spawned, \
                patch.object(run, "follow_run", return_value=0) as followed, \
                patch.object(run, "drive", side_effect=AssertionError("resumed in the terminal")):
            self.assertEqual(run.resume_run([directory.name]), 0)
        self.assertEqual(spawned.call_args.args[1], ["resume", directory.name])
        followed.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
