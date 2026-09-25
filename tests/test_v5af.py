"""agentkit v5af: a done-when line ending in `# once` runs once, on the commit that ships.

Entirely offline: throwaway repositories with a bare `origin`, a fake adapter and a
fake `gh`, with done-when commands that append to a counter file so each test can
count executions.
"""

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
root = pathlib.Path(os.environ["V5AF_FIXTURE"])
def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True,
                                   stderr=subprocess.STDOUT).strip()
def record(kind, cwd, **extra):
    row = dict(kind=kind, head_sha=git(cwd, "rev-parse", "HEAD"),
               tree_sha=git(cwd, "rev-parse", "HEAD^{tree}"), **extra)
    with (root / "events.jsonl").open("a") as f: f.write(json.dumps(row) + "\\n")
    return row
'''

ADAPTER = SUPPORT + '''import sys
assert sys.argv[1] == "run", sys.argv
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
plan = json.loads((root / "plan.json").read_text())
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"prompt": prompt}) + "\\n")
reviewer = prompt.startswith("You are the reviewer")
if reviewer:
    previous = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()] if (root / "events.jsonl").exists() else []
    count = sum(e["kind"] == "review" for e in previous)
    record("review", cwd, model=sys.argv[2])
    reviews = plan.get("reviews", ["PASS"])
    verdict = reviews[count] if count < len(reviews) else reviews[-1]
    text = "VERDICT: " + verdict
    if verdict == "FAIL":
        text += "\\n\\n## Findings\\n- work.txt:1 - stale pattern - why it matters\\n"
    code = 0
elif "## The final check failed" in prompt:
    with (cwd / "fixed").open("a") as fh: fh.write("fixed\\n")
    git(cwd, "add", "fixed")
    git(cwd, "commit", "-m", "fix the final check")
    record("final-fixer", cwd)
    text, code = "## Summary\\nFixed the root cause.", 0
else:
    with (cwd / "work.txt").open("a") as fh: fh.write("branch\\n")
    git(cwd, "add", ".")
    git(cwd, "commit", "-m", "task work")
    record("executor", cwd)
    text, code = "## Summary\\nDid the work.", 0
(out / "final.md").write_text(text)
(out / "stderr.log").write_text("offline fixture")
sys.exit(code)
'''


def task_body(*cmds):
    return "# v5af fixture\n\n## Done when\n```bash\n" + "\n".join(cmds) + "\n```\n"


class V5af(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5af-", dir=REPO)
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
            "V5AF_FIXTURE": str(self.root)}))
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
        self.counter = self.root / "counter"
        self.counter.write_text("")
        self.remote, self.target, self.wt = (self.root / n for n in ("origin.git", "target", "task"))
        run.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        run.git(self.root, "clone", str(self.remote), str(self.target))
        self.identity(self.target)
        (self.target / "base.txt").write_text("base\n")
        run.git(self.target, "add", ".")
        run.git(self.target, "commit", "-m", "baseline")
        run.git(self.target, "push", "origin", "main")
        run.git(self.root, "clone", str(self.remote), str(self.wt))
        self.identity(self.wt)
        run.git(self.wt, "checkout", "-b", "ak/task")
        self.task = self.root / "task.md"
        self.plan = {}
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, text):
        path.write_text(f"#!{sys.executable}\n{text}")
        path.chmod(0o755)

    def identity(self, cwd):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")

    def every_cmd(self, word="every"):
        return f"echo {word} >> {shlex.quote(str(self.counter))}"

    def gh(self, cwd, *args, **kwargs):
        if args[:2] == ("repo", "view"):
            return 0, json.dumps({"nameWithOwner": "fixture/repo", "viewerPermission": "WRITE"})
        if args[:2] == ("pr", "create"):
            return 0, URL
        if args[:2] == ("pr", "view"):
            head = run.git(self.wt, "rev-parse", "HEAD")
            return 0, json.dumps({"headRefOid": head, "baseRefName": "main", "state": "OPEN"})
        if args[:2] == ("pr", "merge"):
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

    def launch(self, *cmds, rounds=3, flags=()):
        (self.root / "plan.json").write_text(json.dumps(self.plan))
        self.task.write_text(f"---\nrepo: {self.wt}\nbase: origin/main\nrounds: {rounds}\n"
                             f"---\n{task_body(*cmds)}")
        code = run.main([str(self.task), "--exec", "opus", "--review", "astra",
                         "--no-worktree", *flags])
        dirs = run.run_dirs()
        self.assertEqual(len(dirs), 1)
        self.directory = dirs[0]
        return code, run.read_state(self.directory)

    def counts(self, word):
        return self.counter.read_text().split().count(word)

    def prompts(self):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row["prompt"] for row in rows]

    def log_text(self):
        return (self.directory / "log.txt").read_text()

    def test_v5af_parsing_splits_only_a_trailing_unquoted_once(self):
        body = task_body("cmd-a", "cmd-b  # once", "cmd-c #once",
                         "cmd-d # once more", 'echo "# once"', "echo '# once'")
        every, once = run.done_when_groups(body, Path("task.md"))
        self.assertEqual(every, ["cmd-a", "cmd-d # once more", 'echo "# once"', "echo '# once'"])
        self.assertEqual(once, ["cmd-b", "cmd-c"])
        # done_when itself is unchanged: the flat list, markers intact
        self.assertEqual(run.done_when(body, Path("task.md")),
                         ["cmd-a", "cmd-b  # once", "cmd-c #once", "cmd-d # once more",
                          'echo "# once"', "echo '# once'"])

    def test_v5af_rounds_run_only_the_every_commands(self):
        self.plan = {"reviews": ["FAIL", "PASS"]}
        code, state = self.launch(self.every_cmd(), f"{self.every_cmd('once')}  # once",
                                  rounds=3, flags=("--no-merge",))
        self.assertEqual(code, 0, self.log_text())
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertEqual(self.counts("every"), 2)
        self.assertEqual(self.counts("once"), 0)

    def test_v5af_final_check_runs_the_once_command_on_the_pushed_commit(self):
        once = (f"echo \"once $(git rev-parse HEAD)\" >> {shlex.quote(str(self.counter))}"
                "  # once")
        code, state = self.launch(self.every_cmd(), once)
        self.assertEqual(code, 0, self.log_text())
        self.assertTrue(state["merged"])
        self.assertEqual(self.counts("every"), 2)     # one round plus the final check
        rows = [line.split() for line in self.counter.read_text().splitlines()
                if line.startswith("once ")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], state["delivery_sha"])
        pushed = run.git(self.remote, "rev-parse", f"refs/heads/{state['branch']}")
        self.assertEqual(rows[0][1], pushed)
        self.assertIn("final check: all passed", self.log_text())
        self.assertIn(" ; once: ", self.log_text())
        log = (self.directory / "final-check.log").read_text()
        self.assertIn("Commit: ", log)
        result = (self.directory / "result.md").read_text()
        self.assertIn(f"final check: passed on {state['delivery_sha']}", result)

    def test_v5af_failing_once_command_gets_a_fixer_turn_then_merges(self):
        gate = ("if test -f fixed; then echo once-pass >> "
                f"{shlex.quote(str(self.counter))}; else echo once-fail >> "
                f"{shlex.quote(str(self.counter))}; exit 1; fi  # once")
        code, state = self.launch(self.every_cmd(), gate)
        self.assertEqual(code, 0, self.log_text())
        self.assertTrue(state["merged"])
        self.assertTrue(any("## The final check failed. Fix the root cause." in prompt
                            for prompt in self.prompts()),
                        "no fixer turn ran on the final check output")
        self.assertEqual(self.counts("once-fail"), 2)     # the failing run and its re-run
        self.assertEqual(self.counts("once-pass"), 1)
        self.assertIn("final check: FAILED", self.log_text())
        self.assertIn("final check: all passed", self.log_text())
        result = (self.directory / "result.md").read_text()
        self.assertIn(f"final check: passed on {state['delivery_sha']}", result)

    def test_v5af_once_command_failing_at_the_budget_fails_with_a_continue_hint(self):
        code, state = self.launch(self.every_cmd(),
                                  f"{self.every_cmd('once')}; exit 1  # once", rounds=1)
        self.assertEqual(code, 1, self.log_text())
        # the check fails the same way after its own fixer round: blocked on the line it
        # fails on, never a FAIL that spends the budget and asks for `--rounds`
        self.assertEqual(state["verdict"], "BLOCKED")
        self.assertIn("final check: FAILED", self.log_text())
        result = (self.directory / "result.md").read_text()
        self.assertIn("final check: failed on ", result)
        self.assertIn("the final check still fails on `echo once", state["error"])
        self.assertNotIn("--rounds", result)

    def test_v5af_no_once_commands_means_no_final_check(self):
        code, state = self.launch(self.every_cmd())
        self.assertEqual(code, 0, self.log_text())
        self.assertTrue(state["merged"])
        self.assertNotIn("final check", self.log_text())
        self.assertFalse((self.directory / "final-check.log").exists())
        self.assertTrue(state["review"]["done_when"])
        self.assertIn("[exit 0]", (self.directory / "round-1" / "donewhen.log").read_text())
        result = (self.directory / "result.md").read_text()
        self.assertIn("final check: none (no once-commands)", result)

    def test_v5af_executor_prompt_lists_once_commands_under_their_heading(self):
        code, _ = self.launch(self.every_cmd(), f"{self.every_cmd('once')}  # once",
                              flags=("--no-merge",))
        self.assertEqual(code, 0, self.log_text())
        prompt = (self.directory / "round-1" / "executor" / "prompt.md").read_text()
        self.assertIn("Done-when commands, all must exit 0", prompt)
        heading = ("Once, on your final commit before you hand over "
                   "(the loop runs these once more before the merge):")
        self.assertIn(heading, prompt)
        self.assertLess(prompt.index("Done-when commands, all must exit 0"),
                        prompt.index(heading))
        self.assertIn(self.every_cmd(), prompt.split(heading)[0])
        self.assertIn(self.every_cmd("once"), prompt.split(heading)[1])


if __name__ == "__main__":
    unittest.main()
