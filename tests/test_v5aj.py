"""agentkit v5aj: a reviewer that gives no verdict is asked once more. Offline fixtures."""

import io
import json
import os
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, usage, worker

NO_VERDICT_PROMPT = ("Your previous turn ended without a verdict. Review the diff now and end "
                     "your answer with VERDICT: PASS or VERDICT: FAIL. Do not start commands you "
                     "will not wait for in this turn.")
NO_VERDICT = "All checks passed. No issues found.\n"
PASS = "VERDICT: PASS\n\n## Findings\n- none\n"
FAIL = "VERDICT: FAIL\n\n## Findings\n- file.py:1 - issue - why it matters\n"

ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["V5AJ_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt, "session": sys.argv[7:],
        "out": str(out)}) + "\\n")
if role == "executor":
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
    (out / "final.md").write_text("## Summary\\nFixture work.")
    (out / "stderr.log").write_text("")
    (out / "events.jsonl").write_text("")
    (out / "session_id").write_text("session-executor")
    sys.exit(0)
plan = json.loads((root / "reviews.json").read_text())
answer = plan.pop(0) if len(plan) > 1 else plan[0]
(root / "reviews.json").write_text(json.dumps(plan))
if isinstance(answer, dict):
    code = answer.get("code", 0)
    text = answer.get("text", "")
    stderr = answer.get("stderr", "")
    events = answer.get("events", [])
    session = answer.get("session", "session-reviewer")
else:
    code, text, stderr, events, session = 0, answer, "", [], "session-reviewer"
(out / "final.md").write_text(text)
(out / "stderr.log").write_text(stderr)
(out / "events.jsonl").write_text("".join(json.dumps(e) + "\\n" for e in events))
(out / "session_id").write_text(session)
sys.exit(code)
'''


def make_repos(root):
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    for cwd in (owner,):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")
    (owner / "base.txt").write_text("base\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "base")
    run.git(owner, "push", "origin", "main")
    wt = root / "wt"
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", "ak/test")
    (wt / "work.txt").write_text("work\n")
    run.git(wt, "add", ".")
    run.git(wt, "commit", "-m", "work")
    return remote, owner, wt


def move_owner(owner, name, value="x\n"):
    (owner / name).write_text(value)
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", f"move {name}")
    run.git(owner, "push", "origin", "main")


class V5aj(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5aj-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "V5AJ_FIXTURE": str(self.root)}))
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        # every model but Fable, in config order: an executor, a reviewer on another company
        # and a spare on a third
        workers = [name for name in config.offered(self.cfg) if name != "fable"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.spare = next(name for name in workers
                          if name not in (self.executor, self.reviewer)
                          and config.model(self.cfg, name)["provider"] not in (
                              config.model(self.cfg, self.executor)["provider"],
                              config.model(self.cfg, self.reviewer)["provider"]))
        self.task = self.root / "task.md"
        self.reviews(PASS)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        # Deterministic pick order: executor, reviewer, one spare on a third provider.
        self.order = [self.executor, self.reviewer, self.spare]
        self.stack.enter_context(patch.object(usage, "pick_order", side_effect=lambda cfg, *a, **k: list(self.order)))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    def launch(self, rounds=1, done_when="test -f deliverable"):
        self.task.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# V5aj fixture\n\n"
                             f"## Done when\n```bash\n{done_when}\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def log(self, directory):
        return (directory / "log.txt").read_text()

    def test_v5aj_no_verdict_asks_once_more_and_pass_counts(self):
        self.reviews(NO_VERDICT, PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(state["state"], "pass")
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(state["round_summaries"][0]["round"], 1)
        reviewers = self.calls("reviewer")
        self.assertEqual(len(reviewers), 2)
        self.assertNotIn(NO_VERDICT_PROMPT, reviewers[0]["prompt"])
        self.assertIn(NO_VERDICT_PROMPT, reviewers[1]["prompt"])
        self.assertEqual(reviewers[0]["session"], [])
        self.assertEqual(reviewers[1]["session"], ["session-reviewer"])
        first_out = Path(reviewers[0]["out"])
        second_out = Path(reviewers[1]["out"])
        self.assertEqual(first_out.parent.name, "round-1")
        self.assertEqual(second_out.parent.name, "round-1")
        self.assertNotEqual(first_out, second_out)
        self.assertTrue(second_out.name.startswith("reviewer-attempt"))
        self.assertIn(f"reviewer {self.reviewer} gave no verdict; asking once more",
                      self.log(directory))
        # the loop's only backoff announces itself; usage probes may sleep
        # while reaping, so the absence of backoff is pinned on the log
        self.assertNotIn("retrying in", self.log(directory))
        self.assertEqual((directory / "round-1" / second_out.name / "final.md").read_text(), PASS)

    def test_v5aj_second_answer_fail_records_one_fail(self):
        self.reviews(NO_VERDICT, FAIL)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(state["round_summaries"][0]["verdict"], "FAIL")
        self.assertEqual(len(self.calls("reviewer")), 2)
        self.assertIn(f"reviewer {self.reviewer} gave no verdict; asking once more",
                      self.log(directory))
        # the loop's only backoff announces itself; usage probes may sleep
        # while reaping, so the absence of backoff is pinned on the log
        self.assertNotIn("retrying in", self.log(directory))

    def test_v5aj_unfinished_no_verdict_gets_one_combined_ask(self):
        first = {"text": NO_VERDICT, "stderr": "Background tasks still running\n",
                 "session": "sess-1"}
        self.reviews(first, PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        reviewers = self.calls("reviewer")
        # one mechanism, one extra call: it finishes the background work and asks
        # for the verdict in the same turn, on the same session
        self.assertEqual(len(reviewers), 2)
        self.assertIn(run.FINISH_IN_FOREGROUND, reviewers[1]["prompt"])
        self.assertIn(NO_VERDICT_PROMPT, reviewers[1]["prompt"])
        self.assertEqual(reviewers[1]["session"], ["sess-1"])
        self.assertEqual(Path(reviewers[1]["out"]).name, "reviewer-retry-foreground")
        self.assertIn("asking it to finish in the foreground", self.log(directory))
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(state["verdict"], "PASS")
        # the loop's only backoff announces itself; usage probes may sleep
        # while reaping, so the absence of backoff is pinned on the log
        self.assertNotIn("retrying in", self.log(directory))

    def test_v5aj_unfinished_then_silent_is_gone_without_a_third_call(self):
        self.order = [self.executor, self.reviewer]
        first = {"text": NO_VERDICT, "stderr": "Background tasks still running\n",
                 "session": "sess-1"}
        self.reviews(first, NO_VERDICT)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "exhausted")
        # the combined ask already spent the turn's one extra call: silence twice
        # means the reviewer is gone, never a third call and never a FAIL round
        self.assertEqual(len(self.calls("reviewer")), 2)
        self.assertEqual(len(state.get("round_summaries") or []), 0)
        self.assertIsNone(state.get("verdict"))
        self.assertEqual(state.get("review_pending", {}).get("round"), 1)
        self.assertIn("gave no verdict twice", state.get("error", ""))
        self.assertEqual(run.continue_line(state, directory),
                         f"continue: ak run resume {directory.name}")

    def test_v5aj_two_no_verdicts_fall_back_to_spare(self):
        self.reviews(NO_VERDICT, NO_VERDICT, PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        reviewers = self.calls("reviewer")
        self.assertEqual(len(reviewers), 3)
        self.assertIn(NO_VERDICT_PROMPT, reviewers[1]["prompt"])
        self.assertEqual(state["reviewer"], self.spare)
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertIn(f"reviewer {self.reviewer} gave no verdict; asking once more",
                      self.log(directory))
        self.assertIn(f"WARN reviewer fell back to {self.spare}", self.log(directory))
        outs = [Path(row["out"]).name for row in reviewers]
        self.assertIn(f"reviewer-{self.spare}", outs)

    def test_v5aj_two_no_verdicts_no_spare_exhausted_and_resumable(self):
        self.order = [self.executor, self.reviewer]
        self.reviews(NO_VERDICT, NO_VERDICT, PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "exhausted")
        self.assertEqual(len(state.get("round_summaries") or []), 0)
        self.assertIsNone(state.get("verdict"))
        self.assertEqual(state.get("review_pending", {}).get("round"), 1)
        self.assertIn("gave no verdict twice", state.get("error", ""))
        self.assertIn("gave no verdict twice", self.log(directory))
        self.assertEqual(len(self.calls("reviewer")), 2)
        self.assertEqual(run.continue_line(state, directory),
                         f"continue: ak run resume {directory.name}")
        executors_before = len(self.calls("executor"))
        self.assertEqual(executors_before, 1)
        self.assertEqual(run.cmd_resume([directory.name]), 0, self.log(directory))
        after = run.read_state(directory)
        self.assertEqual(after["state"], "pass")
        self.assertEqual(after["verdict"], "PASS")
        self.assertEqual(len(after["round_summaries"]), 1)
        self.assertEqual(after["round_summaries"][0]["round"], 1)
        self.assertNotIn("review_pending", after)
        self.assertEqual(len(self.calls("executor")), executors_before)

    def test_v5aj_post_rebase_no_verdicts_exhausted_branch_untouched(self):
        _, owner, wt = make_repos(self.root)
        run_dir = self.root / "run-post"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        move_owner(owner, "new.txt", "new\n")
        run.git(wt, "fetch", "origin")
        run.git(wt, "rebase", "origin/main")
        head_rebased = run.git(wt, "rev-parse", "HEAD")
        base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
        old_head = run.git(wt, "rev-parse", "HEAD~1")
        old_tree = run.git(wt, "rev-parse", "HEAD~1^{tree}")
        lines = []

        def log(msg):
            line = f"[00:00:00] {msg}"
            lines.append(line)
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(line + "\n")

        state = {
            "run_id": "v5aj-post", "title": "v5aj post", "state": "running", "verdict": None,
            "review": None,
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": "work", "head_sha": old_head, "tree_sha": old_tree}],
            "rounds": 3, "base": "origin/main", "target": "origin/main",
            "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
            "repo": str(wt), "executor": self.executor, "reviewer": self.reviewer,
            "merge_method": "squash", "merged": False, "merge_failed": False,
            "merge_note": None,
            "review_pending": {"round": 2, "summary": "work",
                               "reason": "Re-review after the rebase of origin/main."},
        }
        run.save_state(run_dir, state)
        lp = run.Loop(self.cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])
        lp.rnd = 2
        self.reviews(NO_VERDICT, NO_VERDICT)
        with self.assertRaises(run.Exhausted) as ctx:
            run.resume_review(lp)
        self.assertIn("gave no verdict twice", str(ctx.exception))
        self.assertEqual(run.git(wt, "rev-parse", "HEAD"), head_rebased)
        after = run.read_state(run_dir)
        self.assertEqual(len(after["round_summaries"]), 1)
        self.assertIsNone(after.get("verdict"))
        self.assertEqual(after.get("review_pending", {}).get("round"), 2)
        self.assertIn(NO_VERDICT.strip().splitlines()[0], after.get("findings", ""))
        # The same commit re-reviews with no executor turn once the reviewer answers.
        self.reviews(PASS)
        with patch.object(run, "execute", side_effect=AssertionError("no executor turn")):
            self.assertEqual(run.resume_review(lp), "PASS")
        self.assertEqual(run.git(wt, "rev-parse", "HEAD"), head_rebased)
        resumed = run.read_state(run_dir)
        self.assertEqual(len(resumed["round_summaries"]), 2)
        self.assertEqual(resumed["round_summaries"][-1]["verdict"], "PASS")

    def test_v5aj_judged_fail_after_rebase_resumes_with_fixer(self):
        _, owner, wt = make_repos(self.root)
        head = run.git(wt, "rev-parse", "HEAD")
        tree = run.git(wt, "rev-parse", "HEAD^{tree}")
        base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
        run_dir = config.RUNS / "20260918-0000-v5aj-judged"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(
            "---\nrepo: none\nrounds: 4\n---\n# Judged fixture\n\n## Done when\n```bash\ntrue\n```\n")
        findings_text = FAIL
        review_dir = run_dir / "round-2" / "reviewer"
        review_dir.mkdir(parents=True)
        (review_dir / "final.md").write_text(findings_text)
        state = {
            "run_id": run_dir.name, "title": "judged fixture", "state": "fail",
            "verdict": "FAIL", "review": None,
            "round_summaries": [
                {"round": 1, "verdict": "PASS", "done_when": True,
                 "summary": "work", "head_sha": head, "tree_sha": tree},
                {"round": 2, "verdict": "FAIL", "done_when": True,
                 "summary": "fixer work", "head_sha": head, "tree_sha": tree}],
            "rounds": 4, "base": "origin/main", "target": "origin/main",
            "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
            "repo": str(wt), "executor": self.executor, "reviewer": self.reviewer,
            "merge_method": "squash", "merged": False, "merge_failed": False,
            "merge_note": "done-when or review after the rebase of origin/main did not pass",
            "findings": findings_text.strip()[-8000:],
            "findings_file": str(review_dir / "final.md"),
        }
        run.save_state(run_dir, state)
        (run_dir / "log.txt").write_text(
            "[00:00:00] WARN not merged: done-when or review after the rebase "
            "of origin/main did not pass\n")
        self.assertFalse(run.failed_in_integration(run.read_state(run_dir), run_dir))
        self.assertEqual(run.continue_line(run.read_state(run_dir), run_dir),
                         f"continue: ak run resume {run_dir.name}")
        self.reviews(PASS)
        URL = "https://github.com/fixture/repo/pull/1"

        def fake_gh(cwd, *args, **kwargs):
            if args[:2] == ("repo", "view"):
                return 0, json.dumps({"nameWithOwner": "fixture/repo",
                                      "viewerPermission": "WRITE"})
            if args[:2] == ("pr", "create"):
                return 0, URL
            if args[:2] == ("pr", "merge"):
                return 0, "merged"
            if args[:2] == ("api", "graphql"):
                return 0, json.dumps({"data": {"repository": {"ref": {
                    "branchProtectionRule": None}}}})
            if args[:2] == ("api", "--paginate"):
                return 0, "[]"
            raise AssertionError(f"unexpected gh: {args[:4]}")

        with patch.object(run, "gh", side_effect=fake_gh):
            self.assertEqual(run.cmd_resume([run_dir.name]), 0,
                             (run_dir / "log.txt").read_text())
        after = run.read_state(run_dir)
        self.assertEqual(after["state"], "pass")
        executors = self.calls("executor")
        self.assertEqual(len(executors), 1)
        self.assertIn("## Reviewer findings to fix", executors[0]["prompt"])
        self.assertIn("file.py:1", executors[0]["prompt"])
        self.assertEqual([entry["round"] for entry in after["round_summaries"]], [1, 2, 3])
        self.assertEqual(after["round_summaries"][-1]["verdict"], "PASS")

    def test_v5aj_clean_verdict_no_extra_call_and_quota_exhaustion(self):
        self.reviews(PASS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, self.log(directory))
        self.assertEqual(len(self.calls("reviewer")), 1)
        self.assertNotIn("gave no verdict", self.log(directory))
        # the loop's only backoff announces itself; usage probes may sleep
        # while reaping, so the absence of backoff is pinned on the log
        self.assertNotIn("retrying in", self.log(directory))
        quota = {"code": 1, "text": "You have hit your usage limit\n"}
        self.order = [self.executor, self.reviewer]
        (self.root / "calls.jsonl").unlink()
        self.reviews(quota)
        with patch.object(run.time, "sleep"):
            code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "exhausted")
        self.assertIn("refused", state.get("error", ""))
        reviewers = [row for row in self.calls("reviewer")
                     if Path(row["out"]).parent.name.startswith("round-")]
        self.assertEqual(len(reviewers), 1)
        self.assertNotIn("gave no verdict; asking once more", self.log(directory))


if __name__ == "__main__":
    unittest.main()
