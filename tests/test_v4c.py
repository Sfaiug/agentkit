"""Offline watcher/delivery regressions; all artifacts stay inside this checkout."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, usage, watch

URL = "https://github.com/me/repo/pull/7"
SHA = "a" * 40


def reviewed():
    cfg = config.load()
    return {"executor": "opus", "reviewer": "astra", "verdict": "PASS",
            "review": {"executor": "opus", "reviewer": "astra", "returncode": 0,
                       "executor_provider": config.model(cfg, "opus")["provider"],
                       "reviewer_provider": config.model(cfg, "astra")["provider"],
                       "verdict": "PASS", "done_when": True, "head_sha": SHA, "tree_sha": SHA}}


class Correctness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".v4c-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", config.RUN_DIR_ENV: "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.root / "sockets"),
            "AGENTKIT_DISCORD_WEBHOOK": "off", "FAKE_ROOT": str(self.root)}))
        (self.root / "sockets").mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        tmux = self.bin / "tmux"
        tmux.write_text(f'#!{sys.executable}\nimport sys\n'
                        'assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv\nsys.exit(1)\n')
        tmux.chmod(0o755)
        fake = self.bin / "gh"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ["FAKE_ROOT"])
a = sys.argv[1:]
with (p / "calls").open("a") as f: f.write(json.dumps(a) + "\\n")
r = json.loads((p / "responses").read_text())
key = " ".join(a)
if "--slurp" in a or (a[:2] == ["pr", "checks"] and "--json" in a):
    print("unsupported by gh 2.46: " + key, file=sys.stderr)
    sys.exit(2)
if key not in r:
    print("unexpected gh: " + key, file=sys.stderr)
    sys.exit(97)
row = r[key]
if isinstance(row, list):
    item = row.pop(0) if len(row) > 1 else row[0]
    (p / "responses").write_text(json.dumps(r))
else: item = row
print(item.get("text", json.dumps(item.get("json"))))
sys.exit(item.get("rc", 0))
''')
        fake.chmod(0o755)
        self.responses = {}
        self.classic(None)

    def reply(self, args, data=None, rc=0, text=None):
        if text is None and rc == 0 and "--paginate" in args.split():
            text = "\n".join(json.dumps(page) for page in data)
        self.responses[args] = {"json": data, "rc": rc} if text is None else {"text": text, "rc": rc}
        (self.root / "responses").write_text(json.dumps(self.responses))

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def lp(self):
        d = self.root / "run"
        d.mkdir(exist_ok=True)
        return SimpleNamespace(run_dir=d, target="origin/release/v4", reviewer="stub",
                               state={"head_sha": SHA}, findings="VERDICT: PASS", log=lambda s: None,
                               turn_limit=60 * run.SILENCE_MINUTES,
                               done_when_limit=3600 * run.CEILING_HOURS)

    def rules(self, checks):
        self.reply("api --paginate repos/me/repo/rules/branches/release%2Fv4?per_page=100",
                   [[{"type": "required_status_checks", "parameters": {
                       "required_status_checks": [{"context": name} for name in checks]}}]])

    def classic(self, protection):
        key = (f"api graphql -f query={run.CLASSIC_CHECKS_QUERY} -f owner=me -f name=repo "
               "-f branch=refs/heads/release/v4")
        self.reply(key, {"data": {"repository": {"ref": {"branchProtectionRule": protection}}}})
        return key

    def check_rows(self, rows):
        conclusions = {"pass": "success", "skipping": "skipped", "fail": "failure",
                       "cancel": "cancelled", "pending": None}
        return [{"id": index, "name": row["name"], "app": {"id": row.get("app", 42)},
                 "status": "in_progress" if row["bucket"] == "pending" else "completed",
                 "conclusion": conclusions[row["bucket"]]} for index, row in enumerate(rows, 1)]

    def test_paginated_json_handles_separate_documents_and_rejects_partial_output(self):
        pages = [[], [{"message": "brackets ][ in a string"}], [{"page": 3}]]
        self.reply("api --paginate pages", pages)
        self.assertEqual(run.gh_json(self.root, "api", "--paginate", "pages"), (pages, ""))
        self.assertEqual(watch.pages(self.root, "pages"), (pages[1] + pages[2], ""))
        for text in ("", "[]\n[{", '[]\n{"message":"an API error is not an array page"}'):
            self.reply("api --paginate pages", text=text)
            self.assertIsNone(watch.pages(self.root, "pages")[0])
        self.reply("api --paginate pages", rc=1, text="HTTP 502: failed\n" + "usage " * 100)
        self.assertTrue(run.gh_json(self.root, "api", "--paginate", "pages")[1].startswith("HTTP 502"))

    def test_required_checks_on_later_pages_and_legacy_statuses(self):
        self.reply("api --paginate repos/me/repo/rules/branches/release%2Fv4?per_page=100", [[], [
            {"type": "required_status_checks", "parameters": {"required_status_checks": [
                {"context": "unit"}, {"context": "legacy"}]}}]])
        self.observations([])
        self.reply(f"api --paginate repos/me/repo/commits/{SHA}/check-runs?filter=latest&per_page=100", [
            {"check_runs": []}, {"check_runs": self.check_rows([{"name": "unit", "bucket": "pass"}])}])
        key = f"api --paginate repos/me/repo/commits/{SHA}/statuses?per_page=100"
        self.reply(key, [[{"id": 3, "context": "legacy", "state": "success"}], [
            {"id": 1, "context": "legacy", "state": "failure"},
            {"id": 2, "context": "optional", "state": "pending"}]])
        self.assertEqual(run.checks(self.lp(), URL), (True, ""))
        self.reply(key, [[{"id": 4, "context": "legacy", "state": "failure"}]])
        self.assertIn("required checks failed: legacy", run.checks(self.lp(), URL)[1])
        # A successful check run cannot hide a failed status with the same required name.
        self.rules(["unit"])
        self.reply(key, [[{"id": 5, "context": "unit", "state": "error"}]])
        self.assertIn("required checks failed: unit", run.checks(self.lp(), URL)[1])
        self.reply(key, rc=1, text="HTTP 503")
        self.assertIn("cannot read required commit statuses: HTTP 503", run.checks(self.lp(), URL)[1])

    def test_classic_protection_checks_are_combined_with_rulesets(self):
        self.rules(["ruleset"])
        protection = {"requiresStatusChecks": True, "requiredStatusChecks": [
            {"context": "classic", "app": {"databaseId": 42}}]}
        key = self.classic(protection)
        self.observations([{"name": "ruleset", "bucket": "pass"},
                           {"name": "classic", "bucket": "pass", "app": 12}])
        with patch.object(run, "CHECKS_CAP", 0):
            self.assertIn("never registered: classic", run.checks(self.lp(), URL)[1])
        self.observations([{"name": "ruleset", "bucket": "pass"},
                           {"name": "classic", "bucket": "pending"}])
        with patch.object(run, "CHECKS_CAP", 0):
            self.assertIn("did not finish: classic", run.checks(self.lp(), URL)[1])
        self.observations([{"name": "ruleset", "bucket": "pass"},
                           {"name": "classic", "bucket": "pass"}])
        self.assertEqual(run.checks(self.lp(), URL), (True, ""))
        self.rules([])  # classic protection alone must also wait
        protection["requiredStatusChecks"][0]["app"] = None
        self.classic(protection)
        self.observations([])
        self.reply(f"api --paginate repos/me/repo/commits/{SHA}/statuses?per_page=100",
                   [[{"id": 1, "context": "classic", "state": "success"}]])
        self.assertEqual(run.checks(self.lp(), URL), (True, ""))
        self.reply(key, rc=1, text="HTTP 503")
        self.assertIn("cannot read classic required checks", run.checks(self.lp(), URL)[1])
        protection["requiresStatusChecks"] = False
        self.classic(protection)
        self.observations([])
        self.assertEqual(run.checks(self.lp(), URL), (True, ""))

    def test_enterprise_checks_use_the_pr_host(self):
        self.rules(["unit"])
        self.observations([{"name": "unit", "bucket": "pass"}])
        self.responses = {key.replace("api ", "api --hostname github.example.com ", 1): value
                          for key, value in self.responses.items()}
        (self.root / "responses").write_text(json.dumps(self.responses))
        self.assertEqual(run.checks(self.lp(), URL.replace("github.com", "github.example.com")), (True, ""))
        self.assertEqual(len(self.calls()), 4)
        self.assertTrue(all(call[:3] == ["api", "--hostname", "github.example.com"] for call in self.calls()))

    def test_smoke_notification_check_distinguishes_preflight_from_fallback(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source.split("# --- 4d:", 1)[1].split("# --- 5:", 1)[0]
        block = block.split("\n", 1)[1]
        # This section closes the enclosing model-quota gate; exercise its eligible branch.
        block = "if true; then\n" + block
        preflight = ("[12:00:00] notification: none: no orchestrator session launched this run, so "
                     "nothing is sent; the result is here and in `ak run status`\n")
        fallback = ("[12:01:00] the orchestrator session orch-9 this run was launched from is gone; "
                    "asking the user to continue the task\n"
                    "notify: no webhook configured; message: Needs you · orch-9: Its orchestrator "
                    "session orch-9 is gone. Run finished: PASS. Press n in the menu, then say: "
                    "continue Smoke make hello pass.\n")
        log = self.root / "run.log"
        run_dir = self.root / "started-run"
        run_dir.mkdir()
        cases = [(preflight, 0, "started", 0, "1 passed, 0 failed, 0 skipped"),
                 (preflight + fallback, 0, "started", 1, "0 passed, 1 failed, 0 skipped"),
                 (preflight, 1, "started", 0, "1 passed, 0 failed, 0 skipped"),
                 (preflight + fallback, 1, "started", 1, "0 passed, 1 failed, 0 skipped"),
                 (preflight, 1, "", 2, "0 passed, 0 failed, 1 skipped"),
                 (preflight, 1, None, 2, "0 passed, 0 failed, 1 skipped")]
        for text, run_rc, run_log, expected, counts in cases:
            with self.subTest(run_rc=run_rc, run_log=run_log, fallback=fallback in text):
                log.write_text(text)
                (run_dir / "log.txt").write_text(run_log or "")
                script = f'. "{REPO}/tests/acceptance.sh"\n' + block + '\nfinish\n'
                result = subprocess.run(["bash", "-c", script],
                                        env=dict(os.environ, WORK=str(self.root), RC=str(run_rc),
                                                 RUNDIR=str(run_dir) if run_log is not None else "",
                                                 AGENTKIT_ACCEPTANCE_REQUIRED="1"),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertIn(counts, result.stdout)

    def observations(self, rows):
        self.reply(f"api --paginate repos/me/repo/commits/{SHA}/check-runs?filter=latest&per_page=100",
                   [{"check_runs": self.check_rows(rows)}])
        self.reply(f"api --paginate repos/me/repo/commits/{SHA}/statuses?per_page=100", [[]])

    def test_required_checks_ignore_optional_and_name_missing(self):
        lp = self.lp()
        self.rules(["unit", "build"])
        self.observations([
            {"name": "unit", "bucket": "pass"}, {"name": "optional", "bucket": "fail"}])
        with patch.object(run, "CHECKS_CAP", 0):
            green, why = run.checks(lp, URL)
        self.assertFalse(green)
        self.assertIn("required checks never registered: build", why)
        self.observations([
            {"name": "unit", "bucket": "pass"}, {"name": "build", "bucket": "skipping"},
            {"name": "optional", "bucket": "fail"}])
        self.assertEqual(run.checks(lp, URL), (True, ""))
        self.observations([])
        with patch.object(run, "CHECKS_CAP", 0):
            self.assertIn("build, unit", run.checks(lp, URL)[1])

    def test_required_checks_failure_pending_and_api_errors(self):
        lp = self.lp()
        self.rules(["unit"])
        for bucket, expected in (("fail", "failed"), ("cancel", "failed"), ("pending", "did not finish")):
            self.observations([{"name": "unit", "bucket": bucket}])
            with patch.object(run, "CHECKS_CAP", 0):
                green, why = run.checks(lp, URL)
            self.assertFalse(green)
            self.assertIn(expected, why)
        self.rules([])
        self.assertEqual(run.checks(lp, URL), (True, ""))
        self.reply("api --paginate repos/me/repo/rules/branches/release%2Fv4?per_page=100",
                   rc=1, text="HTTP 503")
        self.assertIn("cannot read required checks", run.checks(lp, URL)[1])

    def test_check_registers_on_later_poll(self):
        self.rules(["unit"])
        self.observations([])
        key = f"api --paginate repos/me/repo/commits/{SHA}/check-runs?filter=latest&per_page=100"
        self.responses[key] = [{"json": {"check_runs": []}},
                               {"json": {"check_runs": self.check_rows([{"name": "unit", "bucket": "pass"}])}}]
        (self.root / "responses").write_text(json.dumps(self.responses))
        with patch.object(run, "time", wraps=run.time) as clock:
            clock.sleep.return_value = None
            self.assertEqual(run.checks(self.lp(), URL), (True, ""))
        clock.sleep.assert_called_once_with(run.CHECKS_POLL)

    def test_required_check_app_cannot_be_substituted(self):
        lp = self.lp()
        self.reply("api --paginate repos/me/repo/rules/branches/release%2Fv4?per_page=100",
                   [[{"type": "required_status_checks", "parameters": {
                       "required_status_checks": [{"context": "unit", "integration_id": 42}]}}]])
        self.observations([{"name": "unit", "bucket": "pass"}])
        key = f"api --paginate repos/me/repo/commits/{SHA}/check-runs?filter=latest&per_page=100"
        check = {"id": 1, "name": "unit", "app": {"id": 12}, "status": "completed", "conclusion": "success"}
        self.reply(key, [{"check_runs": [check]}])
        with patch.object(run, "CHECKS_CAP", 0):
            self.assertIn("never registered: unit", run.checks(lp, URL)[1])
        check["app"]["id"] = 42
        self.reply(key, [{"check_runs": [check]}])
        self.assertEqual(run.checks(lp, URL), (True, ""))

    def test_review_head_is_checked_and_submission_is_pinned(self):
        lp = self.lp()
        key = f"pr view {URL} --json headRefOid,state"
        self.reply(key, {"headRefOid": "b" * 40, "state": "OPEN"})
        self.assertFalse(run.post_review(lp, URL, "PASS"))
        self.assertTrue(lp.state["review_stale"])
        self.assertEqual(len(self.calls()), 1)
        self.reply(key, {"headRefOid": SHA, "state": "OPEN"})
        for verdict, event in (("PASS", "COMMENT"), ("FAIL", "REQUEST_CHANGES")):
            self.reply(f"api repos/me/repo/pulls/7/reviews --method POST -f commit_id={SHA} "
                       f"-f event={event} -F body=@{lp.run_dir / 'review.md'}", {})
            self.assertTrue(run.post_review(lp, URL, verdict))
            self.assertIn(f"commit_id={SHA}", self.calls()[-1])

    def test_review_restores_test_mutations_and_keeps_the_commit_diff(self):
        lp = self.lp()
        lp.scratch, lp.wt = False, lp.run_dir
        run.git(lp.wt, "init", "-b", "main")
        run.git(lp.wt, "config", "user.name", "smoke")
        run.git(lp.wt, "config", "user.email", "smoke@localhost")
        tracked = lp.wt / "lockfile"
        tracked.write_text("base\n")
        run.git(lp.wt, "add", ".")
        run.git(lp.wt, "commit", "-m", "base")
        lp.base_sha, lp.base = run.git(lp.wt, "rev-parse", "HEAD"), "main"
        tracked.write_text("PR version\n")
        run.git(lp.wt, "commit", "-am", "PR")
        head = run.git(lp.wt, "rev-parse", "HEAD")
        lp.state["review_pr"] = URL
        lp.state["head_sha"], lp.state["round_summaries"] = head, []
        lp.rnd, lp.body, lp.cfg, lp.review_sid = 1, "Review the PR", config.load(), None
        lp.executor, lp.reviewer = None, "astra"
        lp.dir, lp.role, lp.save = lambda name: lp.run_dir / name, lambda role: role, lambda: None
        tracked.write_text("generated by tests\n")
        staged = lp.wt / "generated"
        staged.write_text("new staged file\n")
        run.git(lp.wt, "add", str(staged))
        def reviewer(*args, **kwargs):
            self.assertEqual(tracked.read_text(), "PR version\n")
            self.assertFalse(staged.exists())
            self.assertIn("+PR version", args[2])
            self.assertNotIn("generated by tests", args[2])
            self.assertEqual(run.git(lp.wt, "diff", head), "")
            return 0, "VERDICT: PASS", "session", False
        with patch.object(run, "call_retrying", side_effect=reviewer) as call, patch.object(
                run, "commit_leftovers") as commit:
            self.assertEqual(run.review(lp, "", True, "tests passed"), "PASS")
            call.assert_called_once()
            commit.assert_not_called()
        self.assertIn("generated by tests", (lp.run_dir / "tests-changes.patch").read_text())
        self.assertEqual(run.git(lp.wt, "rev-parse", "HEAD"), head)
        run.git(lp.wt, "commit", "--allow-empty", "-m", "unexpected commit")
        with self.assertRaisesRegex(config.Error, "HEAD changed"):
            run.restore_review_checkout(lp, "reviewer")

    def test_github_review_requires_matching_sha_author_and_marker(self):
        key = f"pr view {URL} --json reviews"
        for head, author, body, expected in ((SHA, "me", "agentkit review of", True),
                                             ("old", "me", "agentkit review of", False),
                                             (SHA, "other", "agentkit review of", False),
                                             (SHA, "me", "looks fine", False)):
            self.reply(key, {"reviews": [{"author": {"login": author}, "body": body,
                                         "commit": {"oid": head}}]})
            self.assertEqual(watch.reviewed_on_github(URL, SHA, "me"), expected)

    def incoming_fixture(self):
        config.CODE.mkdir()
        (config.CODE / "repo" / ".git").mkdir(parents=True)
        self.reply("repo view --json nameWithOwner,owner", {"nameWithOwner": "me/repo", "owner": {"login": "me"}})
        self.reply("api --paginate repos/me/repo/pulls?state=open&per_page=100",
                   [[], [{"html_url": URL, "head": {"sha": SHA}, "user": {"login": "bob"}, "number": 7}]])
        self.reply(f"pr view {URL} --json reviews", {"reviews": []})

    def test_retry_delays_recover_old_giveup_and_failed_launches(self):
        self.incoming_fixture()
        now = [1000]
        state = {"reviewed": {URL: {"sha": SHA, "run": "gone", "attempts": 1, "gave_up": True}}, "own": {}}
        with patch.object(watch.time, "time", side_effect=lambda: now[0]), patch.object(
                watch, "launch", return_value="gone") as launch:
            for attempt, delay in enumerate((600, 1800, 3600, 3600, 3600), 1):
                watch.incoming(state, "me", False, lambda s: None)
                self.assertEqual(state["reviewed"][URL]["retry_at"], now[0] + delay)
                now[0] += delay - 1
                watch.incoming(state, "me", False, lambda s: None)
                self.assertEqual(launch.call_count, attempt - 1)
                now[0] += 1
                watch.incoming(state, "me", False, lambda s: None)
                self.assertEqual(launch.call_count, attempt)
                self.assertNotIn("gave_up", state["reviewed"][URL])
            state["reviewed"] = {}
            launch.side_effect = config.Error("provider unavailable")
            watch.incoming(state, "me", False, lambda s: None)
            self.assertEqual(watch.settled(state["reviewed"][URL]), "failed")
            self.assertEqual(state["reviewed"][URL]["retry_at"], now[0] + 600)

    def test_dry_run_does_not_create_or_reap_or_chmod(self):
        self.incoming_fixture()
        self.reply("api user", {"login": "me"})
        self.reply("api --paginate search/issues?q=is:pr+is:open+author:@me&per_page=100", [{"items": []}])
        with patch.object(config, "ensure_dirs", side_effect=AssertionError("write")), patch.object(
                run, "reap", side_effect=AssertionError("reap")), patch.object(
                watch, "launch", side_effect=AssertionError("launch")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(watch.main(["--dry-run"]), 0)
            self.assertFalse(config.STATE.exists())
            config.RUNS.mkdir()
            config.STATE.mkdir(mode=0o755)
            d = config.RUNS / "dead"
            d.mkdir()
            run.save_state(d, {"state": "running", "pid": 999999999})
            state = {"reviewed": {URL: {"sha": SHA, "run": "dead", "at": 0}}, "own": {}}
            watch.state_path().write_text(json.dumps(state))
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (d / "run.json", watch.state_path())}
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(watch.main(["--dry-run"]), 0)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
            self.assertEqual(config.STATE.stat().st_mode & 0o777, 0o755)

    def test_authored_search_discovers_foreign_prs_on_later_pages_and_tracks_their_outcome(self):
        foreign = "https://github.com/other/theirs/pull/8"
        search = "api --paginate search/issues?q=is:pr+is:open+author:@me&per_page=100"
        self.reply(search, [
            {"total_count": 2, "incomplete_results": False,
             "items": [{"pull_request": {"html_url": URL}}]},
            {"total_count": 2, "incomplete_results": False,
             "items": [{"pull_request": {"html_url": foreign}}]}])
        state = {"reviewed": {}, "own": {}}
        self.assertEqual(watch.own_prs(state, "me", self.fail), {foreign: None})
        key = f"pr view {foreign} --json state,reviewDecision,title,number"
        self.reply(key, {"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED", "title": "Foreign", "number": 8})
        # Neither decision is Discord's business: with the launching seat gone and no run
        # left to note it on, following the PR simply ends.
        with patch.object(watch.notify, "shaped", side_effect=AssertionError("posted")) as shaped:
            watch.outgoing(state, "me", False, lambda s: None)
            self.assertEqual(state["own"][foreign]["decision"], "CHANGES_REQUESTED")
            self.reply(search, [{"items": []}])  # a merged PR disappears from open search
            self.reply(key, {"state": "MERGED", "title": "Foreign", "number": 8})
            watch.outgoing(state, "me", False, lambda s: None)
            self.assertTrue(state["own"][foreign]["done"])
            shaped.assert_not_called()
        self.reply(search, [{"total_count": 1}])
        self.assertIsNone(watch.pages(config.RUNS, search.removeprefix("api --paginate "), "items")[0])

    def test_settled_rejects_posted_review_of_a_different_head(self):
        d = config.RUNS / "posted"
        d.mkdir(parents=True)
        run.save_state(d, {"state": "pass", "review_posted": True, "head_sha": "old"})
        self.assertEqual(watch.settled({"sha": SHA, "run": "posted"}), "failed")

    def test_fallback_needs_speaks_only_for_the_seat_that_launched_the_run(self):
        config.STATE.mkdir(parents=True)
        for status, verdict in (("pass", "PASS"), ("fail", "FAIL"), ("error", "FAIL")):
            lp = self.lp()
            state = {**reviewed(), "state": status, "title": "Fix watcher", "launched_session": "missing"}
            with patch.object(orch, "find", return_value=None), patch.object(
                    notify := run.notify, "shaped", return_value=0) as shaped:
                run.announce(state, lp.run_dir, lambda s: None)
            shaped.assert_called_once_with("needs", "Its orchestrator session missing is gone. Run "
                                            f"finished: {verdict}. Press n in the menu, then say: "
                                            "continue Fix watcher.", session="missing",
                                            event_id="orphan:run:None:None")
        with patch.object(orch, "find", return_value={"name": "missing"}), patch.object(notify, "shaped") as shaped:
            run.announce(state, lp.run_dir, lambda s: None)
            shaped.assert_not_called()
        # a run.json written before the field was renamed still names the seat it was launched from
        with patch.object(orch, "find", return_value=None), patch.object(notify, "shaped") as shaped:
            run.announce({"state": "fail", "title": "Fix watcher", "session": "missing"},
                         lp.run_dir, lambda s: None)
            shaped.assert_called_once()
        # launched from no seat at all: nobody was handed this task, so nobody is asked to continue it
        for orphan in ({"state": "fail", "title": "By hand"},
                       {"state": "fail", "title": "By hand", "launched_session": None}):
            with patch.object(orch, "find", return_value=None), patch.object(notify, "shaped") as shaped:
                run.announce(orphan, lp.run_dir, lambda s: None)
                shaped.assert_not_called()

    def test_worker_default_and_explicit_session(self):
        cfg = config.load()
        other = next(n for n in config.offered(cfg) if n not in cfg["defaults"]["workers"])
        with patch.object(config, "active_session", return_value=None):
            self.assertNotIn(other, usage.pick_order(cfg, {}))
            self.assertEqual(config.workers(cfg), cfg["defaults"]["workers"])
        with patch.object(config, "active_session", return_value={"workers": [other]}):
            self.assertEqual(usage.pick_order(cfg, {}), [other])

    def test_review_only_never_suggests_continuing_an_executor_task(self):
        lp = self.lp()
        for posted in (True, False):
            for verdict in ("pass", "fail", "error"):
                state = {"review_pr": URL, "review_posted": posted, "state": verdict,
                         "launched_session": "missing"}
                with patch.object(orch, "find", return_value=None), patch.object(
                        run.notify, "shaped") as shaped:
                    run.announce(state, lp.run_dir, lambda s: None)
                shaped.assert_not_called()

    def test_bad_done_when_leaves_no_orphan_run_directory(self):
        task = self.root / "bad-task.md"
        for block in ("", "## Done when\nmissing fence", "## Done when\n```bash\n# no commands\n```\n"):
            task.write_text("---\nrepo: none\n---\n# Bad task\n\n" + block)
            with self.assertRaisesRegex(config.Error, "Done when"):
                run.main([str(task)])
            self.assertEqual(run.run_dirs(), [])

    def test_delivery_headlines(self):
        for state, expected in (({"verdict": "PASS", "merged": True}, "PASS, merged"),
                                ({"verdict": "PASS", "merge_note": "build missing"}, "PASS, not merged: build missing"),
                                ({"verdict": "FAIL"}, "FAIL"),
                                ({"verdict": "PASS", "state": "error"}, "FAIL")):
            self.assertEqual(run.delivery({**reviewed(), **state}), expected)

    def test_unchanged_merge_retry_uses_no_workers_and_keeps_pass_on_failure(self):
        config.ensure_dirs()
        d = config.RUNS / "passed"
        d.mkdir()
        (d / "task.md").write_text("---\nrepo: none\n---\n# Test\n\n## Done when\n```bash\ntrue\n```\n")
        state = {**reviewed(), "run_id": "passed", "title": "Test", "state": "pass", "verdict": "PASS",
                 "base": "origin/dev", "target": "release/v4", "base_sha": SHA,
                 "worktree": str(d), "rounds": 1, "round_summaries": [], "findings": "",
                 "executor": "opus", "reviewer": "astra", "branch": "ak/test", "pr": URL,
                 "delivery_sha": SHA, "merge_method": "squash", "merged": False}
        run.save_state(d, state)
        self.reply(f"pr view {URL} --json number,title,body,author,baseRefName,headRefOid,url,state,isDraft",
                   {"headRefOid": SHA, "baseRefName": "release/v4", "state": "OPEN"})
        self.rules([])
        key = f"pr merge {URL} --squash --delete-branch --match-head-commit {SHA}"
        self.reply(key, rc=1, text="approvals missing")
        self.reply(f"pr view {URL} --json mergeStateStatus -q .mergeStateStatus", text="BLOCKED")
        with patch.object(run.worker, "call", side_effect=AssertionError("worker")), patch.object(
                run, "integrate", return_value=True), patch.object(
                run, "push", side_effect=AssertionError("push")), patch.object(run, "announce"), patch.object(
                run, "git", return_value=SHA), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["merge", "passed"]), 1)
            self.assertIn("# PASS, not merged: gh pr merge --squash failed", (d / "result.md").read_text())
            self.reply(key, {})
            self.assertEqual(run.main(["merge", "passed"]), 0)
            after = run.read_state(d)
            self.assertTrue(after["merged"])
            self.assertFalse(after["merge_failed"])
            self.assertEqual(after["round_summaries"], [])
            self.assertTrue((d / "result.md").read_text().startswith("# PASS, merged"))
            self.assertEqual(run.main(["merge", "passed"]), 0)
            after["merged"] = False
            run.save_state(d, after)
            self.reply(f"pr view {URL} --json number,title,body,author,baseRefName,headRefOid,url,state,isDraft",
                       {"headRefOid": "changed", "baseRefName": "release/v4", "state": "OPEN"})
            self.assertEqual(run.main(["merge", "passed"]), 1)
            self.assertIn("PR head or target changed since PASS", (d / "result.md").read_text())
        self.assertEqual(sum(args[:2] == ["pr", "merge"] for args in self.calls()), 2)

    def test_merge_retry_rejects_nonpass(self):
        config.ensure_dirs()
        d = config.RUNS / "failed"
        d.mkdir()
        for status in ("fail", "error", "running"):
            run.save_state(d, {"state": status, "verdict": "PASS"})
            with self.assertRaises(config.Error):
                run.main(["merge", "failed"])
        self.assertEqual(self.calls(), [])

    def test_env_uses_repo_basename_with_and_without_worktree(self):
        repo = self.root / "actual-repo"
        repo.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init", "-b", "main")
        git("config", "user.email", "smoke@localhost")
        git("config", "user.name", "smoke")
        (repo / "seed").touch()
        git("add", ".")
        git("commit", "-m", "seed")
        home = self.root / "worker-home"
        envdir = home / ".agentkit" / "env"
        envdir.mkdir(parents=True)
        (envdir / "actual-repo.env").write_text("V4C_SECRET=from-basename\n")
        (envdir / "different-title.env").write_text("V4C_SECRET=wrong\n")
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in ("claude", "codex", "muse"):
            path = adapters / f"{harness}.sh"
            path.write_text('''#!/bin/sh
if [ "$1" = usage ]; then echo '{"meters":[],"error":"offline"}'; exit 0; fi
mkdir -p "$6"
printf '%s\\n' "$V4C_SECRET" >"$6/env-seen"
case "$0" in
  */claude.sh) printf '%s\\n' "$V4C_SECRET" >"$4/delivered"; echo '## Summary' >"$6/final.md" ;;
  *) printf 'VERDICT: PASS\\n\\n## Findings\\n- none\\n' >"$6/final.md" ;;
esac
''')
            path.chmod(0o755)
        # No notification transport or real tmux server is needed for a worker run.
        tmux = self.bin / "tmux"
        tmux.write_text("#!/bin/sh\nexit 1\n")
        tmux.chmod(0o755)
        task = self.root / "task.md"
        task.write_text(f"---\nrepo: {repo}\nbase: main\n---\n# Different title\n\n"
                        "## Done when\n```bash\ntest \"$(cat delivered)\" = from-basename\n```\n")
        env = dict(os.environ, HOME=str(home), AGENTKIT_ADAPTER_DIR=str(adapters),
                   AK_SLOT_POLL=".05",
                   AK_HOST_READINGS=json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                                "load": 1, "cpus": 8,
                                                "unit_memory_current_mb": 100,
                                                "unit_memory_high_mb": 1000}))
        for flags in ([], ["--no-worktree"]):
            cmd = [sys.executable, str(REPO / "bin" / "ak"), "run", str(task), "--no-merge",
                   "--exec", "opus", "--review", "astra", *flags]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("preflight", result.stdout)
            self.assertIn("done-when:", result.stdout)
            self.assertIn("PASS, not merged: --no-merge", result.stdout)
        states = list((home / ".agentkit" / "runs").glob("*/run.json"))
        self.assertEqual(len(states), 2)
        for path in states:
            state = json.loads(path.read_text())
            self.assertEqual(state["verdict"], "PASS")
            self.assertEqual((path.parent / "round-1/executor/env-seen").read_text().strip(), "from-basename")
            self.assertEqual((path.parent / "round-1/reviewer/env-seen").read_text().strip(), "from-basename")

    def test_claude_list_warns_only_for_old_seats(self):
        config.ensure_dirs()
        cfg = config.load()
        (config.STATE / "installed-at").write_text("1000")
        for name, model in (("old", "opus"), ("new", "opus"), ("codex", "astra")):
            config.save_session(cfg, name, model, ["spark"])
        seats = [{"name": name, "path": "/repo", "created": when, "attached": False}
                 for name, when in (("old", 900), ("new", 1100), ("codex", 900))]
        out = io.StringIO()
        with patch.object(orch, "sessions", return_value=seats), contextlib.redirect_stdout(out):
            orch.cmd_list([])
        flagged = [line for line in out.getvalue().splitlines() if "restart to pick up updates" in line]
        self.assertEqual(len(flagged), 1)
        self.assertTrue(flagged[0].startswith("old "))

    def adapters(self, cannot_pin=()):
        """A fake adapter for every harness, and $AGENTKIT_ADAPTER_DIR pointing at them.

        `interactive` writes down the arguments it was given and prints a command; a harness
        named in `cannot_pin` answers CANNOT_PIN when asked for a new conversation, the way the
        Codex and Muse adapters do, because their TUIs take no id.  `usage` answers unknown, so
        selecting a model never reaches a provider.
        """
        root = self.root / "adapters"
        root.mkdir(exist_ok=True)
        for harness in ("claude", "codex", "muse"):
            refuse = ('[ "${4:-}" = new ] && exit 3\n' if harness in cannot_pin else "")
            path = root / f"{harness}.sh"
            path.write_text('#!/usr/bin/env bash\n'
                            'set -uo pipefail\n'
                            '[ "${1:-}" = usage ] && { printf \'%s\\n\' '
                            '\'{"meters":[],"error":"unknown: fake"}\'; exit 0; }\n'
                            '[ "${1:-}" = interactive ] || exit 0\n'
                            'shift\n'
                            f'printf \'%s\\n\' "$*" >>"{root}/{harness}.args"\n'
                            + refuse +
                            'echo "sleep 600"\n')
            path.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ,
                                            {config.ADAPTER_DIR_ENV: str(root)}))
        return root

    def test_a_seat_is_launched_with_the_conversation_it_owns(self):
        """A seat's conversation is the one its launcher gave it, or none at all.

        A harness whose TUI takes an id is handed one this end generated, so the record names
        the conversation before the seat exists, and a resume hands the harness that id and no
        other.  A harness whose TUI takes none -- Codex, Muse -- gets no id: the record says
        `resumable: false`, nothing goes looking afterwards for what it opened, and that seat's
        number starts it again under the same name instead.
        """
        root = self.adapters(cannot_pin=("codex",))
        cfg = config.load()
        config.ensure_dirs()
        cwd = self.root / "seat-cwd"
        cwd.mkdir()

        with patch.object(orch, "sessions", return_value=[]), \
                patch.object(orch, "start", lambda *a, **k: None), \
                contextlib.redirect_stdout(io.StringIO()):
            orch.create(cfg, "pinned", cwd, forced="fable", forced_workers="opus")
        record = json.loads(config.session_path("pinned").read_text())
        pinned = record["conversation"]
        self.assertTrue(record["resumable"])
        # the id is the one the adapter was told to open a new conversation under
        self.assertIn(f"{pinned} new", (root / "claude.args").read_text())

        # a seat nobody typed into has no transcript, so the id it owns is handed back as one to
        # open: `--resume` on a conversation that was never begun is an error, not a seat
        def reopened(seat):
            with patch.object(orch, "sessions", return_value=[]), \
                    patch.object(orch, "start", lambda *a, **k: None), \
                    patch.object(orch, "attach", lambda *a, **k: 0), \
                    contextlib.redirect_stdout(io.StringIO()):
                orch.resume(cfg, seat, log=lambda *a: None)
            return (root / "claude.args").read_text().rstrip().rsplit("\n", 1)[-1]

        self.assertTrue(reopened("pinned").endswith(f" {pinned} new"))
        # once its harness has written that conversation down, the resume is a resume
        store = self.root / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{pinned}.jsonl").write_text('{"type":"mode"}\n')
        self.assertTrue(reopened("pinned").endswith(f" {pinned}"))
        # and a transcript somebody else left in that directory is nobody's business: the seat
        # keeps the id it was launched with
        (store / "conv-stranger.jsonl").write_text('{"type":"mode"}\n')
        self.assertTrue(reopened("pinned").endswith(f" {pinned}"))
        self.assertEqual(json.loads(config.session_path("pinned").read_text())["conversation"],
                         pinned)

        # a record from before any of this names no conversation: the seat opens one of its own
        # as it comes back, under an id of the launcher's, and owns that one from here on
        config.save_session(cfg, "old-seat", "fable", ["opus"], {"cwd": str(cwd), "created": 1})
        with patch.object(orch, "sessions", return_value=[]), \
                patch.object(orch, "start", lambda *a, **k: None), \
                patch.object(orch, "attach", lambda *a, **k: 0), \
                contextlib.redirect_stdout(io.StringIO()):
            orch.resume(cfg, "old-seat", log=lambda *a: None)
        opened = json.loads(config.session_path("old-seat").read_text())["conversation"]
        self.assertIn(f"{opened} new", (root / "claude.args").read_text())

        # the harness that cannot be told one: no id, and the record says the seat cannot come
        # back on a conversation.  Its transcript store is never read -- one written in that
        # directory afterwards is not offered to it, and never was its
        with patch.object(orch, "sessions", return_value=[]), \
                patch.object(orch, "start", lambda *a, **k: None), \
                contextlib.redirect_stdout(io.StringIO()):
            orch.create(cfg, "unpinned", cwd, forced="astra", forced_workers="opus")
        record = json.loads(config.session_path("unpinned").read_text())
        self.assertNotIn("conversation", record)
        self.assertIs(record["resumable"], False)
        self.assertFalse(orch.resumable(record))
        with patch.object(orch, "sessions", return_value=[]):
            orch.stamp()
        self.assertNotIn("conversation",
                         json.loads(config.session_path("unpinned").read_text()))
        # An unbound Codex seat stays in the menu with an explicit fresh-start explanation.
        with patch.object(orch, "sessions", return_value=[]):
            rows = orch.listing()
            self.assertEqual([s["name"] for s in rows], ["old-seat", "pinned", "unpinned"])
            self.assertFalse(rows[-1]["resumable"])
            self.assertIn("starts fresh", rows[-1]["restart"])

    def test_a_renamed_seats_old_name_is_not_handed_to_a_new_one(self):
        """The orchestrator renamed away still answers to the name it was started under.

        Until the seat it was renamed to is stopped: the pointer goes with the record it led
        to, and the old name is a name again -- for the menu and for `create` alike, which read
        the one rule so that they cannot disagree about whether a name is free.
        """
        self.adapters()
        config.ensure_dirs()
        cfg = config.load()
        config.save_session(cfg, "atoll", "fable", ["opus"],
                            {"cwd": "/w", "created": 1, "conversation": "conv-atoll"})
        config.rename_session("atoll", "parser")
        with patch.object(orch, "sessions", return_value=[]):
            self.assertIn("atoll", orch.taken_names())
            with self.assertRaises(config.Error):
                orch.create(cfg, "atoll", "/w", prompting=False, dry_run=True)
            # stopping the seat the pointer leads to takes the pointer with it
            with contextlib.redirect_stdout(io.StringIO()):
                orch.cmd_stop(["parser"])
            self.assertFalse(config.session_path("atoll").exists())
            self.assertNotIn("atoll", orch.taken_names())
            with contextlib.redirect_stdout(io.StringIO()):
                orch.create(cfg, "atoll", "/w", forced="fable", forced_workers="opus",
                            dry_run=True)
        # and a pointer left leading nowhere by anything else is nobody's name to keep either
        config.save_session(cfg, "atoll", "fable", ["opus"], {"cwd": "/w", "created": 1})
        config.rename_session("atoll", "parser")
        config.session_path("parser").unlink()
        with patch.object(orch, "sessions", return_value=[]):
            self.assertNotIn("atoll", orch.taken_names())


if __name__ == "__main__":
    unittest.main(verbosity=2)
