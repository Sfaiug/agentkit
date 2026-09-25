"""agentkit v5ac: a clean rebase keeps its review, whatever the patch. Entirely offline."""

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

SUPPORT = '''import json, os, pathlib, subprocess
root = pathlib.Path(os.environ["V5AC_FIXTURE"])
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
    previous = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()] if (root / "events.jsonl").exists() else []
    count = sum(e["kind"] == "review" for e in previous)
    record("review", cwd, model=sys.argv[2], prompt=prompt)
    if count == 0 and plan.get("target"): move_target(plan["target"])
    if count == 0 and plan.get("reviewer_leftover"): (cwd / "leftover.txt").write_text("leftover\\n")
    text, code = "VERDICT: PASS", 0
elif "## Resolve the " in prompt:
    (cwd / "shared").write_text("both intents\\n")
    git(cwd, "add", "shared")
    if "## Resolve the merge conflict" in prompt: git(cwd, "commit", "--no-edit")
    else: git(cwd, "-c", "core.editor=true", "rebase", "--continue")
    record("conflict-fixer", cwd)
    text, code = "## Summary\\nResolved both sides.", 0
else:
    (cwd / "work.txt").write_text("branch\\n")
    if plan.get("executor_extra"): (cwd / "extra.txt").write_text("same\\n")
    if plan.get("conflict"): (cwd / "shared").write_text("branch intent\\n")
    git(cwd, "add", ".")
    git(cwd, "commit", "-m", "task work")
    record("executor", cwd)
    text, code = "## Summary\\nDid the work.", 0
(out / "final.md").write_text(text)
(out / "stderr.log").write_text("offline fixture")
sys.exit(code)
'''


class V5ac(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5ac-", dir=REPO)
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
            "V5AC_FIXTURE": str(self.root), "INTEGRATION_FIXTURE": str(self.root)}))
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
ok = (cwd / "work.txt").read_text() == "branch\\n" and (cwd / "base.txt").read_text() == "base\\n"
record("tests", cwd, ok=ok)
sys.exit(0 if ok else 1)
''')
        self.command = f"{shlex.quote(sys.executable)} {shlex.quote(str(verify))}"
        self.remote, self.target, self.wt = (self.root / n for n in ("origin.git", "target", "task"))
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        run.git(self.root, "clone", str(self.remote), str(self.target))
        self.identity(self.target)
        (self.target / "base.txt").write_text("base\n")
        (self.target / "shared").write_text("base\n")
        run.git(self.target, "add", ".")
        run.git(self.target, "commit", "-m", "baseline")
        run.git(self.target, "push", "origin", "main")
        run.git(self.root, "clone", str(self.remote), str(self.wt))
        self.identity(self.wt)
        run.git(self.wt, "checkout", "-b", "ak/task")
        self.task = self.root / "task.md"
        self.plan = {}
        self.merge_mode = "success"
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, text):
        path.write_text(f"#!{sys.executable}\n{text}")
        path.chmod(0o755)

    def identity(self, cwd):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")

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
        run.git(self.target, "commit", "-m", "target moved")
        run.git(self.target, "push", "origin", "main")

    def gh(self, cwd, *args, **kwargs):
        if args[:2] == ("repo", "view"):
            return 0, json.dumps({"nameWithOwner": "fixture/repo", "viewerPermission": "WRITE"})
        if args[:2] == ("pr", "create"):
            return 0, URL
        if args[:2] == ("pr", "view"):
            head = run.git(self.wt, "rev-parse", "HEAD")
            return 0, json.dumps({"headRefOid": head, "baseRefName": "main", "state": "OPEN"})
        if args[:2] == ("pr", "merge"):
            if self.merge_mode == "blocked":
                return 1, "approvals missing"
            return 0, "merged"
        if args[:2] == ("api", "graphql"):
            return 0, json.dumps({"data": {"repository": {"ref": {"branchProtectionRule": None}}}})
        if args[:2] == ("api", "--paginate"):
            endpoint = args[2]
            if "/rules/branches/" in endpoint:
                return 0, "[]"
            if "/check-runs?" in endpoint or "/statuses?" in endpoint:
                return 0, "[]"
        raise AssertionError(f"unexpected gh: {args}")

    def launch(self, rounds=3):
        (self.root / "plan.json").write_text(json.dumps(self.plan))
        self.task.write_text(f"---\nrepo: {self.wt}\nbase: origin/main\nrounds: {rounds}\n"
                             f"---\n# v5ac fixture\n\n## Done when\n"
                             f"```bash\n{self.command}\n```\n")
        code = run.main([str(self.task), "--exec", "opus", "--review", "astra", "--no-worktree"])
        dirs = run.run_dirs()
        self.assertEqual(len(dirs), 1)
        self.directory = dirs[0]
        return code, run.read_state(self.directory)

    def log_text(self):
        return (self.directory / "log.txt").read_text()

    def retry(self):
        code = run.main(["merge", self.directory.name])
        return code, run.read_state(self.directory)

    def test_v5ac_identical_patch_keeps_review(self):
        self.plan = {"target": {"independent": "new work"}}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), 2)
        self.assertEqual(len(reviews), 1)
        self.assertNotEqual(tests[0]["head_sha"], tests[1]["head_sha"])
        self.assertEqual(reviews[0]["head_sha"], tests[0]["head_sha"])
        self.assertEqual(state["review"]["head_sha"], tests[1]["head_sha"])
        self.assertEqual(state["review"]["head_sha"], run.git(self.wt, "rev-parse", "HEAD"))
        self.assertEqual(state["review"]["rebased_from"], tests[0]["head_sha"])
        self.assertTrue(state["review"]["patch_id"])
        self.assertTrue(state["review"]["done_when"])
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(state["round_summaries"][0]["head_sha"], tests[0]["head_sha"])
        self.assertIn(tests[0]["head_sha"], (self.directory / "round-1" / "donewhen.log").read_text())
        self.assertIn(tests[1]["head_sha"], (self.directory / "round-2" / "donewhen.log").read_text())
        self.assertIn("review kept", self.log_text())
        self.assertIn("clean rebase", self.log_text())

    def test_v5ac_different_patch_keeps_review(self):
        # target already carries extra.txt, so the rebased patch is work.txt alone; one
        # round, so it lands only if keeping the review spends none -- even where colour
        # leaves git unable to compute a patch id
        run.git(self.wt, "config", "color.ui", "always")
        self.plan = {"executor_extra": True, "target": {"extra.txt": "same"}}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), 2)
        self.assertEqual(len(reviews), 1)
        self.assertIn("review kept", self.log_text())
        self.assertEqual(run.git(self.wt, "show", "--name-only", "--format=", "HEAD"), "work.txt")
        self.assertEqual(state["review"]["head_sha"], tests[-1]["head_sha"])
        self.assertEqual(state["review"]["rebased_from"], tests[0]["head_sha"])
        self.assertEqual(len(state["round_summaries"]), 1)

    def test_v5ac_work_already_on_main_ends_passed_without_a_pr(self):
        # main takes the branch's whole change while it is reviewed, so the rebase leaves no
        # diff; one round, so it passes only if keeping the review spends none
        self.plan = {"target": {"work.txt": "branch"}}
        code, state = self.launch(rounds=1)
        self.assertEqual(code, 0)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual(run.job_classify(state, self.cfg), "passed")
        self.assertIsNone(state["pr"])
        self.assertEqual(len(self.events("review")), 1)
        self.assertEqual(run.git(self.wt, "ls-remote", "origin", "ak/task"), "")
        self.assertIn("its work is already on main", self.log_text())
        self.assertIn("its work is already on main", (self.directory / "result.md").read_text())

    def test_v5ac_merge_retry_finds_the_work_already_on_main(self):
        # main takes the branch's whole change while its PR waits: the retry's clean rebase
        # leaves no diff, so it pushes nothing and the run still ends passed
        self.merge_mode = "blocked"
        self.assertEqual(self.launch()[0], 1)
        pushed = run.git(self.wt, "ls-remote", "origin", "ak/task")
        self.move_target({"work.txt": "branch"})
        self.merge_mode = "success"
        code, state = self.retry()
        self.assertEqual(code, 0)
        self.assertEqual(state["state"], "pass")
        self.assertFalse(state["merged"])
        self.assertEqual(run.job_classify(state, self.cfg), "passed")
        self.assertEqual(run.git(self.wt, "ls-remote", "origin", "ak/task"), pushed)
        self.assertEqual(len(self.events("review")), 1)
        self.assertIn("its work is already on main", self.log_text())

    def test_v5ac_conflict_calls_fixer_and_reviewer(self):
        self.plan = {"target": {"shared": "target intent"}, "conflict": True}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.events("conflict-fixer")), 1)
        self.assertEqual(len(self.events("tests")), 2)
        self.assertEqual(len(self.events("review")), 2)
        self.assertEqual((self.wt / "shared").read_text(), "both intents\n")

    def test_v5ac_identical_patch_failed_donewhen_reviews_once(self):
        # two rounds: the failed re-review lands on the budget rather than a fixer round
        self.plan = {"target": {"base.txt": "broken"}}
        code, state = self.launch(rounds=2)
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), 2)
        self.assertEqual(len(reviews), 2)
        rebased = [t for t in tests if t["head_sha"] != tests[0]["head_sha"]]
        self.assertEqual(len(rebased), 1)
        second_reviews = [r for r in reviews if r["head_sha"] == rebased[0]["head_sha"]]
        self.assertEqual(len(second_reviews), 1)
        self.assertIn("exit 1", second_reviews[0].get("prompt", ""))
        self.assertTrue((self.directory / "round-2" / "donewhen.log").exists())
        self.assertFalse(state.get("merged"))

    def test_v5ac_reviewer_leftover_is_reviewed_not_kept(self):
        self.plan = {"target": {"independent": "new work"}, "reviewer_leftover": True}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), 2)
        self.assertEqual(len(reviews), 2)
        self.assertIn("leftover.txt", reviews[1].get("prompt", ""))
        self.assertNotIn("rebased_from", state["review"])
        self.assertIn("leftover.txt", run.git(self.wt, "show", "--name-only", "--format=",
                                              state["review"]["head_sha"]))

    def test_v5ac_merge_resume_leftover_is_reviewed_not_kept(self):
        self.merge_mode = "blocked"
        self.plan = {}
        code, state = self.launch()
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "PASS")
        self.move_target({"independent": "new work"})
        (self.wt / "generated.out").write_text("droppings\n")
        self.merge_mode = "success"
        code, state = self.retry()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        tests, reviews = self.events("tests"), self.events("review")
        self.assertEqual(len(tests), 2)
        self.assertEqual(len(reviews), 2)
        self.assertIn("generated.out", reviews[1].get("prompt", ""))
        self.assertNotIn("rebased_from", state["review"])

    def test_v5ac_unchanged_commit_reuses_evidence(self):
        self.plan = {}
        code, state = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.events("tests")), 1)
        self.assertEqual(len(self.events("review")), 1)
        self.assertIn("unchanged commit; reusing", self.log_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
