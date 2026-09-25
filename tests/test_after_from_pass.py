"""agentkit: a task after another starts from its passed branch, and lands after its merge. Offline."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run

URL = "https://github.com/acme/widget/pull"

ADAPTER = '''import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["AFP_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
def commit(name, text, message):
    (cwd / name).write_text(text + "\\n")
    subprocess.run(["git", "-C", str(cwd), "add", name], check=True)
    subprocess.run(["git", "-C", str(cwd), "commit", "-qm", message], check=True)
if prompt.startswith("You are the reviewer"):
    role, answer = "reviewer", "VERDICT: PASS\\n\\n## Findings\\n- none\\n"
elif "## Resolve the " in prompt:
    role, answer = "conflict-fixer", "## Summary\\nNothing resolved."
elif "Work: alpha" in prompt:
    # two commits, so the squash that lands them matches neither
    commit("a.txt", "one", "alpha: first")
    commit("a.txt", "two", "alpha: second")
    role, answer = "executor", "## Summary\\nAlpha work."
else:
    commit("b.txt", "beta", "beta: work")
    role, answer = "executor", "## Summary\\nBeta work."
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role}) + "\\n")
(out / "final.md").write_text(answer)
(out / "session_id").write_text("session-" + role)
'''


class AfterFromPass(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".after-from-pass-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "seat-acme", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets), "TMUX": "",
            "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "AFP_FIXTURE": str(self.root), "AK_SLOT_POLL": ".01",
            "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                             "load": 1, "cpus": 8,
                                             "unit_memory_current_mb": 100,
                                             "unit_memory_high_mb": 1000})}))
        self.script(self.bin / "tmux", 'import sys\nassert sys.argv[1:3] == ["-L", "agentkit-test"]\n'
                                       'sys.exit(1)\n')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        self.stack.enter_context(patch.object(orch, "watching", return_value=True))
        self.stack.enter_context(patch.object(run, "JOB_TICK", 0.05))
        self.stack.enter_context(patch.object(run, "JOB_PICKER_INTERVAL", 0))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"]
                             != config.model(self.cfg, self.executor)["provider"])
        self.origin = self.root / "widget.git"
        self.repo = self.root / "widget"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.git(self.root, "clone", "-q", str(self.origin), str(self.repo))
        self.identity(self.repo)
        (self.repo / "seed").write_text("seed\n")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", "seed")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.prs, self.merges = {}, []
        self.alpha_merge = "squash"     # what the host does with alpha's PR
        self.alpha = self.task("alpha.md", "Alpha widget", "alpha", 'test "$(cat a.txt)" = two')
        self.beta = self.task("beta.md", "Beta widget", "beta",
                              'test "$(cat a.txt)" = two && test -f b.txt', after="alpha.md")

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def identity(self, cwd):
        self.git(cwd, "config", "user.name", "fixture")
        self.git(cwd, "config", "user.email", "fixture@localhost")

    def task(self, name, title, work, check, after=None):
        lines = ["---", f"repo: {self.repo}", "base: main", "rounds: 1"]
        if after:
            lines.append(f"after: {after}")
        lines += ["---", f"# {title}", "", f"Work: {work}", "", "## Done when", "```bash", check,
                  "```", ""]
        path = self.root / name
        path.write_text("\n".join(lines))
        return str(path)

    def squash(self, branch):
        """What GitHub's squash merge does: the branch's whole diff, one commit on main."""
        merger = self.root / "merger"
        if not merger.exists():
            self.git(self.root, "clone", "-q", str(self.origin), str(merger))
            self.identity(merger)
        self.git(merger, "fetch", "-q", "origin")
        self.git(merger, "checkout", "-q", "-B", "main", "origin/main")
        self.git(merger, "merge", "--squash", f"origin/{branch}")
        self.git(merger, "commit", "-qm", f"{branch} (squashed)")
        self.git(merger, "push", "-q", "origin", "main")
        self.merges.append(branch)

    def run_of(self, title):
        for directory in run.run_dirs():
            state = run.read_state(directory) or {}
            if state.get("title") == title:
                return directory, state
        return None, {}

    def beta_waits(self):
        directory, _ = self.run_of("Beta widget")
        return directory is not None and \
            "waiting for alpha.md to merge" in (directory / "log.txt").read_text()

    def wait_for(self, predicate, seconds=120):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("the job did not get there")
            time.sleep(0.05)

    def gh(self, cwd, *args, **kwargs):
        if args[:2] == ("repo", "view"):
            return 0, json.dumps({"nameWithOwner": "acme/widget", "viewerPermission": "WRITE"})
        if args[:2] == ("pr", "create"):
            branch = args[args.index("--head") + 1]
            return 0, self.prs.setdefault(branch, f"{URL}/{len(self.prs) + 1}")
        branch = next((b for b, url in self.prs.items() if len(args) > 2 and url == args[2]), None)
        if args[:2] == ("pr", "view"):
            head = self.git(self.origin, "rev-parse", f"refs/heads/{branch}")
            return 0, json.dumps({"headRefOid": head, "baseRefName": "main", "state": "OPEN",
                                  "mergeable": "MERGEABLE"})
        if args[:2] == ("pr", "merge"):
            if branch.startswith("ak/alpha"):
                # the dependant must be standing on this PASS, waiting, before it lands
                self.wait_for(self.beta_waits)
                if self.alpha_merge == "refused":
                    return 1, "approvals missing"
                if self.alpha_merge == "raced":
                    return 1, "Base branch was modified"
            self.squash(branch)
            return 0, "merged"
        if args[:2] == ("api", "graphql"):
            return 0, json.dumps({"data": {"repository": {"ref": {"branchProtectionRule": None}}}})
        if args[:2] == ("api", "--paginate"):
            return 0, "[]"
        raise AssertionError(f"unexpected gh: {args}")

    def job(self):
        with redirect_stdout(io.StringIO()):
            return run.main([self.alpha, self.beta, "--exec", self.executor,
                             "--review", self.reviewer])

    def tasks(self):
        job_dir = next(d for d in config.JOBS.iterdir() if d.is_dir())
        job = json.loads((job_dir / "job.json").read_text())
        return {task["name"]: task for task in job["tasks"]}, job_dir

    def calls(self, role):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if row["role"] == role]

    def test_dependant_starts_from_the_pass_branch_before_it_merges(self):
        self.assertEqual(self.job(), 0)
        tasks, _ = self.tasks()
        _, alpha = self.run_of("Alpha widget")
        _, beta = self.run_of("Beta widget")
        tip = alpha["review"]["head_sha"]
        # started while alpha was still landing, and alpha's merge waited for it to stand there
        self.assertLess(tasks["beta.md"]["started_at"], tasks["alpha.md"]["finished_at"])
        self.assertEqual(tasks["beta.md"]["from_pass"],
                         {"task": "alpha.md", "branch": alpha["branch"], "tip": tip})
        self.assertEqual(beta["from_pass"]["tip"], tip)
        # cut from that tip: the executor's one commit sits right on it
        first = beta["round_summaries"][0]["head_sha"]
        self.assertEqual(self.git(self.repo, "rev-parse", f"{first}^"), tip)

    def test_it_lands_after_the_squash_merge_with_only_its_own_commits(self):
        self.assertEqual(self.job(), 0)
        tasks, _ = self.tasks()
        _, alpha = self.run_of("Alpha widget")
        directory, beta = self.run_of("Beta widget")
        self.assertEqual(self.merges, [alpha["branch"], beta["branch"]])
        self.assertEqual((tasks["alpha.md"]["state"], tasks["beta.md"]["state"]),
                         ("merged", "merged"))
        # the delivered branch is alpha's squash plus beta's own commit, and nothing of alpha's
        squashed = self.git(self.origin, "rev-parse", "main~1")
        delivered = beta["review"]["head_sha"]
        self.assertEqual(self.git(self.repo, "rev-parse", f"{delivered}^"), squashed)
        self.assertEqual(self.git(self.origin, "log", "--format=%s", "main"),
                         f"{beta['branch']} (squashed)\n{alpha['branch']} (squashed)\nseed")
        self.assertEqual(self.git(self.origin, "show", "--name-only", "--format=", "main"), "b.txt")
        self.assertEqual(self.calls("conflict-fixer"), [])
        log = (directory / "log.txt").read_text()
        self.assertLess(log.index("waiting for alpha.md to merge"),
                        log.index("alpha.md merged; landing"))

    def test_a_dependency_that_does_not_merge_skips_it_with_its_branch_kept(self):
        self.alpha_merge = "refused"
        self.assertEqual(self.job(), 1)
        tasks, job_dir = self.tasks()
        directory, beta = self.run_of("Beta widget")
        self.assertEqual(tasks["alpha.md"]["state"], "failed")
        self.assertEqual(tasks["beta.md"]["state"], "skipped")
        self.assertEqual(tasks["beta.md"]["verdict_line"], "beta.md: skipped: alpha.md did not merge")
        self.assertIn("beta.md: skipped: alpha.md did not merge", (job_dir / "log.txt").read_text())
        self.assertEqual(beta["skipped_dep"], "alpha.md")
        self.assertFalse(beta["merged"])
        # stopped before landing: nothing pushed, no PR, the branch and its worktree kept
        self.assertNotIn(beta["branch"], self.prs)
        self.assertEqual(self.git(self.origin, "branch", "--list", beta["branch"]), "")
        self.assertEqual(self.git(self.repo, "rev-parse", beta["branch"]),
                         beta["round_summaries"][0]["head_sha"])
        self.assertTrue(Path(beta["worktree"]).is_dir())
        # `ak run status` reads the run's own word the same way once its launcher is gone
        now = run.job_now({"tasks": [{**tasks["beta.md"], "state": "running"}]}, False, self.cfg)
        self.assertEqual((now["tasks"][0]["state"], now["tasks"][0]["verdict_line"]),
                         ("skipped", "beta.md: skipped: alpha.md did not merge"))

    def test_a_parked_pass_keeps_its_dependants_waiting(self):
        self.alpha_merge = "raced"
        result = {}
        thread = threading.Thread(target=lambda: result.update(rc=self.job()), daemon=True)
        with patch.object(run, "MERGE_RETRIES", 0), \
                patch.object(run, "tick_admission", return_value="the tick takes it up"):
            thread.start()
            try:
                self.wait_for(lambda: self.run_of("Alpha widget")[1].get("state") == "waiting")
                time.sleep(0.5)     # a few scheduler passes over the parked PASS
                tasks, job_dir = self.tasks()
                self.assertEqual(tasks["alpha.md"]["state"], "running")
                self.assertEqual(tasks["beta.md"]["state"], "running")
                self.assertTrue(self.beta_waits())
                self.assertNotIn("skipped", (job_dir / "log.txt").read_text())
                self.assertEqual(self.merges, [])
                # the tick's retry after the next merge to main lands it
                directory, alpha = self.run_of("Alpha widget")
                self.squash(alpha["branch"])
                run.save_state(directory, {**alpha, "state": "pass", "merged": True, "pid": None})
            finally:
                thread.join(timeout=120)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["rc"], 0)
        tasks, _ = self.tasks()
        _, beta = self.run_of("Beta widget")
        self.assertEqual((tasks["alpha.md"]["state"], tasks["beta.md"]["state"]),
                         ("merged", "merged"))
        self.assertEqual(self.merges[-1], beta["branch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
