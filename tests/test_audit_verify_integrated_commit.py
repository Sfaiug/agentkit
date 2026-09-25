"""Finding 1: delivery evidence must cover the integrated commit. Entirely offline."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage

URL = "https://github.com/fixture/repo/pull/1"

# Both done-when and the fake adapters record the actual checkout, independently of run.json.
SUPPORT = '''import json, os, pathlib, subprocess
root = pathlib.Path(os.environ["INTEGRATION_FIXTURE"])
def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True,
                                   stderr=subprocess.STDOUT).strip()
def record(kind, cwd, **extra):
    row = dict(kind=kind, head_sha=git(cwd, "rev-parse", "HEAD"),
               tree_sha=git(cwd, "rev-parse", "HEAD^{tree}"), **extra)
    with (root / "events.jsonl").open("a") as f: f.write(json.dumps(row) + "\\n")
    return row
def move_target(changes):
    target = root / "target"
    for name, value in changes.items(): (target / name).write_text(value + "\\n")
    git(target, "add", ".")
    git(target, "commit", "-m", "independent target change")
    git(target, "push", "origin", "main")
'''

ADAPTER = SUPPORT + '''import sys
assert sys.argv[1] == "run", sys.argv
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
plan = json.loads((root / "plan.json").read_text())
reviewer = prompt.startswith("You are the reviewer")
if reviewer:
    previous = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()]
    count = sum(e["kind"] == "review" for e in previous)
    record("review", cwd, model=sys.argv[2], prompt=prompt)
    if count == 0 and plan.get("target"): move_target(plan["target"])
    if count == 0 and plan.get("empty_target"):
        git(root / "target", "commit", "--allow-empty", "-m", "target metadata change")
        git(root / "target", "push", "origin", "main")
    text = "VERDICT: " + ("FAIL" if count and plan.get("reject") else "PASS")
    code = plan.get("review_code", 0) if count else 0
elif "## Resolve the " in prompt:
    (cwd / "shared").write_text("both intents\\n")
    git(cwd, "add", "shared")
    if "## Resolve the merge conflict" in prompt: git(cwd, "commit", "--no-edit")
    else: git(cwd, "-c", "core.editor=true", "rebase", "--continue")
    record("conflict-fixer", cwd)
    text, code = "## Summary\\nResolved both sides.", 0
else:
    (cwd / "expected").write_text("10\\n")
    if plan.get("conflict"): (cwd / "shared").write_text("task intent\\n")
    git(cwd, "add", ".")
    git(cwd, "commit", "-m", "task expects original limit")
    record("executor", cwd)
    text, code = "## Summary\\nAdded the task expectation.", 0
(out / "final.md").write_text(text)
(out / "stderr.log").write_text("offline fixture")
sys.exit(code)
'''


class IntegratedCommit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".verify-integration-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "INTEGRATION_FIXTURE": str(self.root)}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        self.script(self.bin / "tmux", 'import sys\nassert sys.argv[1:3] == ["-L", "agentkit-test"]\nsys.exit(1)\n')
        self.script(self.bin / "gh", 'raise AssertionError("external GitHub call")\n')
        self.stack.enter_context(patch.object(run.notify, "shaped", side_effect=AssertionError("notification")))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(usage, "pick_order", return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(run, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run.time, "sleep"))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        verify = self.root / "verify.py"
        verify.write_text(SUPPORT + '''import sys
cwd = pathlib.Path.cwd()
ok = (cwd / "limit").read_text() == (cwd / "expected").read_text()
record("once" if sys.argv[1:] == ["once"] else "tests", cwd, ok=ok)
sys.exit(0 if ok else 1)
''')
        self.command = f"{shlex.quote(sys.executable)} {shlex.quote(str(verify))}"
        self.remote, self.target, self.wt = (self.root / n for n in ("origin.git", "target", "task"))
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        run.git(self.root, "clone", str(self.remote), str(self.target))
        self.identity(self.target)
        (self.target / "limit").write_text("10\n")
        (self.target / "shared").write_text("base\n")
        run.git(self.target, "add", ".")
        run.git(self.target, "commit", "-m", "baseline limit=10")
        run.git(self.target, "push", "origin", "main")
        run.git(self.root, "clone", str(self.remote), str(self.wt))
        self.identity(self.wt)
        run.git(self.wt, "checkout", "-b", "ak/task")
        self.task = self.root / "task.md"
        self.plan = {}
        self.merge_mode, self.retry_target, self.pr_head = "success", None, None
        self.required, self.check_failure, self.merges = True, False, 0
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        git_out = run.git_out
        def observed_git(cwd, *args):
            if args[0] == "push":
                self.assertEqual(Path(cwd), self.wt)
                self.assertEqual(args[-2:], ("origin", "ak/task"))
                self.record("push")
                self.pr_head = run.git(self.wt, "rev-parse", "HEAD")
            return git_out(cwd, *args)
        self.stack.enter_context(patch.object(run, "git_out", side_effect=observed_git))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, text):
        path.write_text(f"#!{sys.executable}\n{text}")
        path.chmod(0o755)

    def identity(self, cwd):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")

    def record(self, kind, **extra):
        row = dict(kind=kind, **run.commit_identity(self.wt), **extra)
        with (self.root / "events.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def events(self, kind=None):
        path = self.root / "events.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        # a failing done-when runs once more at once, on the same commit: the pair is one gate
        gates, rerun = [], False
        for row in rows:
            rerun = (not rerun and bool(gates) and row == gates[-1]
                     and row["kind"] == "tests" and not row["ok"])
            if not rerun:
                gates.append(row)
        return [r for r in gates if kind is None or r["kind"] == kind]

    def move_target(self, changes):
        for name, value in changes.items():
            (self.target / name).write_text(value + "\n")
        run.git(self.target, "add", ".")
        run.git(self.target, "commit", "-m", "target moved during delivery")
        run.git(self.target, "push", "origin", "main")

    def gh(self, cwd, *args, **kwargs):
        if args[:2] == ("repo", "view"):
            return 0, json.dumps({"nameWithOwner": "fixture/repo", "viewerPermission": "WRITE"})
        if args[:2] == ("pr", "create"):
            self.record("pr")
            return 0, URL
        if args[:2] == ("pr", "view"):
            if "mergeStateStatus" in args:
                return 0, "BEHIND" if self.merge_mode == "retry" else "BLOCKED"
            return 0, json.dumps({"headRefOid": self.pr_head, "baseRefName": "main", "state": "OPEN"})
        if args[:2] == ("pr", "merge"):
            head = args[args.index("--match-head-commit") + 1]
            self.assertEqual(head, self.pr_head)
            self.assertEqual(head, run.git(self.remote, "rev-parse", "refs/heads/ak/task"))
            self.record("merge", delivered=head)
            self.merges += 1
            if self.retry_target:
                self.move_target(self.retry_target)
                self.retry_target = None
                self.merge_mode = "retry"
                return 1, "base moved"
            if self.merge_mode == "blocked":
                return 1, "approvals missing"
            return 0, "merged"
        if args[:2] == ("api", "graphql"):
            return 0, json.dumps({"data": {"repository": {"ref": {"branchProtectionRule": None}}}})
        if args[:2] == ("api", "--paginate"):
            endpoint = args[2]
            if "/rules/branches/" in endpoint:
                return 0, json.dumps([{"type": "required_status_checks", "parameters": {
                    "required_status_checks": [{"context": "unit"}]}}] if self.required else [])
            if "/check-runs?" in endpoint:
                head = endpoint.split("/commits/", 1)[1].split("/", 1)[0]
                self.record("checks", checked=head)
                return 0, json.dumps({"check_runs": [{"id": 1, "name": "unit", "app": {"id": 42},
                    "status": "completed", "conclusion": "failure" if self.check_failure else "success"}]})
            if "/statuses?" in endpoint:
                return 0, "[]"
        raise AssertionError(f"unexpected gh: {args}")

    def launch(self, rounds=3, method="squash", once=False):
        (self.root / "plan.json").write_text(json.dumps(self.plan))
        once = f"\n{self.command} once  # once" if once else ""
        self.task.write_text(f"---\nrepo: {self.wt}\nbase: origin/main\nrounds: {rounds}\n"
                             f"merge: {method}\n---\n# Integrated fixture\n\n## Done when\n"
                             f"```bash\n{self.command}{once}\n```\n")
        code = run.main([str(self.task), "--exec", "opus", "--review", "astra", "--no-worktree"])
        dirs = run.run_dirs()
        self.assertEqual(len(dirs), 1)
        self.directory = dirs[0]
        return code, run.read_state(self.directory)

    def retry(self):
        code = run.main(["merge", self.directory.name])
        return code, run.read_state(self.directory)

    def assert_bound(self, state, count):
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), count)
        self.assertEqual(len(reviews), count)
        for tested, reviewed, summary in zip(tests, reviews, state["round_summaries"]):
            for key in ("head_sha", "tree_sha"):
                self.assertEqual(tested[key], reviewed[key])
                self.assertEqual(summary[key], tested[key])
            self.assertIn(tested["head_sha"], reviewed["prompt"])
        for key in ("head_sha", "tree_sha"):
            self.assertEqual(state["review"][key], tests[-1][key])
        for index, event in enumerate(self.events()):
            if event["kind"] not in ("push", "pr", "merge"):
                continue
            earlier = self.events()[:index]
            self.assertTrue(any(e["kind"] == "tests" and e["ok"] and
                                e["head_sha"] == event["head_sha"] for e in earlier))
            self.assertTrue(any(e["kind"] == "review" and
                                e["head_sha"] == event["head_sha"] for e in earlier))
        for event in self.events("checks"):
            self.assertEqual(event["head_sha"], event["checked"])

    def assert_kept(self, state, tests_count):
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), tests_count)
        self.assertEqual(len(reviews), 1)
        self.assertTrue(all(t["ok"] for t in tests))
        for key in ("head_sha", "tree_sha"):
            self.assertEqual(state["review"][key], tests[-1][key])
        self.assertEqual(state["review"]["rebased_from"], tests[-2]["head_sha"])
        self.assertTrue(state["review"]["patch_id"])
        self.assertTrue(state["review"]["done_when"])
        self.assertEqual(len(state["round_summaries"]), 1)
        for key in ("head_sha", "tree_sha"):
            self.assertEqual(state["round_summaries"][0][key], tests[0][key])
        for index, event in enumerate(self.events()):
            if event["kind"] not in ("push", "pr", "merge"):
                continue
            earlier = self.events()[:index]
            self.assertTrue(any(e["kind"] == "tests" and e["ok"] and
                                e["head_sha"] == event["head_sha"] for e in earlier))
        for event in self.events("checks"):
            self.assertEqual(event["head_sha"], event["checked"])
        self.assertIn("review kept", (self.directory / "log.txt").read_text())

    def assert_no_delivery(self):
        self.assertFalse([e for e in self.events() if e["kind"] in ("push", "pr", "merge")])
        self.assertEqual(run.git(self.remote, "branch", "--list", "ak/task"), "")

    def test_clean_rebase_failure_never_delivers_without_required_ci(self):
        self.required = False
        self.plan = {"target": {"limit": "11"}}
        code, state = self.launch(rounds=2)
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertTrue(run.integrated(self.wt, "origin/main"))
        self.assertEqual([e["ok"] for e in self.events("tests")], [True, False])
        self.assertNotEqual(self.events("tests")[0]["head_sha"], self.events("tests")[1]["head_sha"])
        self.assert_bound(state, 2)
        self.assert_no_delivery()

    def test_changed_rebase_gets_new_tests_before_delivery(self):
        # v5ac: a clean rebase re-runs the done-when and keeps the review.
        self.plan = {"target": {"independent": "new work"}}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        self.assert_kept(state, 2)
        self.assertEqual(state["delivery_sha"], state["review"]["head_sha"])

    def test_unchanged_integration_reuses_evidence_even_at_budget_limit(self):
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 0)
        self.assert_bound(state, 1)

    def test_merge_commit_gets_new_tests(self):
        # v5ac: a clean merge re-runs the done-when and keeps the review.
        self.plan = {"target": {"independent": "new work"}}
        code, state = self.launch(method="merge")
        self.assertEqual(code, 0)
        self.assertEqual(len(run.git(self.wt, "show", "-s", "--format=%P", "HEAD").split()), 2)
        self.assert_kept(state, 2)

    def test_merge_commit_failure_never_delivers(self):
        self.plan = {"target": {"limit": "11"}}
        code, state = self.launch(rounds=2, method="merge")
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(len(run.git(self.wt, "show", "-s", "--format=%P", "HEAD").split()), 2)
        self.assert_bound(state, 2)
        self.assert_no_delivery()

    def test_changed_sha_with_identical_tree_still_gets_new_evidence(self):
        # v5ac: an empty target move keeps the review; the done-when still runs again.
        self.plan = {"empty_target": True}
        code, state = self.launch()
        self.assertEqual(code, 0)
        before, after = self.events("tests")
        self.assertNotEqual(before["head_sha"], after["head_sha"])
        self.assertEqual(before["tree_sha"], after["tree_sha"])
        self.assert_kept(state, 2)

    def test_new_review_failure_blocks_delivery_even_when_tests_pass(self):
        # v5ac: a conflict fix is reviewed again; one round, so the reject lands.
        self.plan = {"target": {"shared": "target intent"}, "conflict": True, "reject": True}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 1)
        self.assertTrue(all(e["ok"] for e in self.events("tests")))
        self.assert_bound(state, 2)
        self.assert_no_delivery()

    def test_nonzero_new_review_cannot_authorize_delivery(self):
        # v5ac: a conflict fix is reviewed again; one round, so the exit 1 lands.
        self.plan = {"target": {"shared": "target intent"}, "conflict": True, "review_code": 1}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 1)
        self.assertEqual(state["review"]["returncode"], 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assert_bound(state, 2)
        self.assert_no_delivery()

    def test_budget_exhaustion_invalidates_pass_and_resumes_only_with_more_rounds(self):
        # v5ac: a clean rebase keeps the review; a failing done-when after it binds the budget.
        self.plan = {"target": {"limit": "11"}}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")
        self.assertIsNone(state["verdict"])
        self.assertIsNone(state["review"])
        self.assertEqual(state["review_pending"]["round"], 2)
        self.assertEqual(state["rounds"], 1)
        self.assertIn("--rounds 2", (self.directory / "result.md").read_text())
        self.assert_no_delivery()
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        self.assertEqual(len(self.events("tests")), 2)
        self.assertEqual(run.cmd_resume([self.directory.name, "--rounds", "2"]), 1)
        self.assertEqual(run.read_state(self.directory)["verdict"], "FAIL")
        self.assertEqual([e["ok"] for e in self.events("tests")], [True, False, False])
        self.assertEqual(len(self.events("review")), 2)
        self.assertEqual(len(self.events("executor")), 1)
        self.assert_no_delivery()

    def test_saved_pass_retry_reuses_unchanged_evidence(self):
        self.merge_mode = "blocked"
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "PASS")
        self.merge_mode = "success"
        code, state = self.retry()
        self.assertEqual(code, 0)
        self.assert_bound(state, 1)
        self.assertEqual(len(self.events("push")), 1)

    def test_saved_pass_retry_verifies_changed_target(self):
        # v5ac: identical patch re-runs done-when and keeps the review, without a new round.
        self.merge_mode = "blocked"
        self.assertEqual(self.launch()[0], 1)
        self.move_target({"independent": "new work"})
        self.merge_mode = "success"
        code, state = self.retry()
        self.assertEqual(code, 0)
        self.assert_kept(state, 2)
        self.assertEqual(len(self.events("push")), 2)

    def test_saved_pass_retry_blocks_failing_integration(self):
        self.merge_mode = "blocked"
        self.assertEqual(self.launch(rounds=2)[0], 1)
        self.move_target({"limit": "11"})
        self.merge_mode = "success"
        code, state = self.retry()
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assert_bound(state, 2)
        self.assertEqual(len(self.events("push")), 1)
        self.assertEqual(len(self.events("merge")), 1)

    def test_target_movement_during_normal_merge_retry_is_reverified(self):
        # v5ac: identical patch re-runs done-when and keeps the review across the retry.
        self.retry_target = {"independent": "moved during checks"}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assert_kept(state, 2)
        self.assertEqual(len(self.events("merge")), 2)

    def test_target_movement_during_retry_cannot_push_a_failing_commit(self):
        self.retry_target = {"limit": "11"}
        code, state = self.launch(rounds=2)
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assert_bound(state, 2)
        self.assertEqual(len(self.events("push")), 1)
        self.assertEqual(len(self.events("merge")), 1)

    def test_target_movement_during_retry_cannot_exceed_review_budget(self):
        # v5ac: a failing done-when after the clean rebase binds the budget.
        self.retry_target = {"limit": "11"}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")
        self.assertIsNone(state["review"])
        self.assertEqual(state["review_pending"]["head_sha"], run.git(self.wt, "rev-parse", "HEAD"))
        self.assertEqual(len(self.events("push")), 1)
        self.assertEqual(len(self.events("merge")), 1)

    def test_target_movement_during_saved_merge_retry_is_reverified(self):
        # v5ac: identical patches re-run done-when twice and keep the one review.
        self.merge_mode = "blocked"
        self.assertEqual(self.launch()[0], 1)
        self.move_target({"independent": "first change"})
        self.retry_target = {"another": "second change"}
        code, state = self.retry()
        self.assertEqual(code, 0)
        self.assert_kept(state, 3)
        self.assertEqual(len(self.events("push")), 3)

    def test_merge_retries_run_the_final_check_before_pushing(self):
        # the saved-PR retry pushes a new head, then the BEHIND retry inside it another
        self.merge_mode = "blocked"
        self.assertEqual(self.launch(once=True)[0], 1)
        self.move_target({"independent": "first change"})
        self.retry_target = {"another": "second change"}
        self.assertEqual(self.retry()[0], 0)
        self.assertEqual(len(self.events("push")), 3)
        for index, event in enumerate(self.events()):
            if event["kind"] == "push":
                self.assertTrue(any(e["kind"] == "once" and e["ok"] and
                                    e["head_sha"] == event["head_sha"]
                                    for e in self.events()[:index]))

    def test_saved_retry_budget_exhaustion_is_resumable(self):
        # v5ac: a failing done-when after the clean rebase binds the budget.
        self.merge_mode = "blocked"
        self.assertEqual(self.launch(rounds=1)[0], 1)
        self.move_target({"limit": "11"})
        code, state = self.retry()
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")
        self.assertIsNone(state["review"])
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(self.events("push")), 1)
        self.merge_mode = "success"
        self.assertEqual(run.cmd_resume([self.directory.name, "--rounds", "2"]), 1)
        self.assertEqual(run.read_state(self.directory)["verdict"], "FAIL")
        self.assertEqual(len(self.events("push")), 1)

    def test_conflict_fixer_path_still_retests_and_reviews(self):
        self.plan = {"target": {"shared": "target intent"}, "conflict": True}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.events("conflict-fixer")), 1)
        self.assert_bound(state, 2)
        self.assertEqual((self.wt / "shared").read_text(), "both intents\n")

    def test_required_check_failure_and_changed_pr_head_still_block_merge(self):
        self.check_failure = True
        code, state = self.launch()
        self.assertEqual(code, 1)
        self.assertIn("required checks failed", state["merge_note"])
        self.assertEqual(len(self.events("merge")), 0)
        self.pr_head = "a" * 40
        code, state = self.retry()
        self.assertEqual(code, 1)
        self.assertIn("PR head or target changed", state["merge_note"])
        self.assertEqual(len(self.events("merge")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
