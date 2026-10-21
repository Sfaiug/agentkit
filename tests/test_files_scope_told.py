"""Every worker is told a task's `files:` scope in its first prompt, once.

A fresh run, a resumed one and the review of a seat's own PR alike: the prompt each worker
is handed (`round-1/<role>/prompt.md`) ends its task with the scope, and a task without
`files:` gets no such line.  Offline: a throwaway repository and its bare origin, a fake
adapter for every harness, a temporary HOME; the own PR is `fixtures/own_pr.py`'s.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
from fixtures.hand_in import scripted, stateful
from fixtures.own_pr import OwnPr
from agentkit import config, gc, gitcall, run, staffing, task as taskfile, turns, worker

TASK = "# Fix the api\n\n## Goal\nChange src/api.py.\n\n## Done when\n```bash\ntrue\n```\n"

# The executor commits src/api.py; the reviewer passes.
ADAPTER = '''import pathlib, subprocess, sys
if sys.argv[1] == "auth":
    print("fixture token")
    sys.exit(0)
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
if pathlib.Path(sys.argv[5]).read_text().startswith("You are the reviewer"):
    text = "VERDICT: PASS\\n\\n## Findings\\n"
else:
    (cwd / "src" / "api.py").write_text("fixed\\n")
    subprocess.run(["git", "-C", str(cwd), "commit", "-qam", "fix api"], check=True)
    text = "## Summary\\nFixed the api."
(out / "final.md").write_text(text)
'''


def told(prompt):
    """The scope lines a prompt carries."""
    return [line for line in Path(prompt).read_text().splitlines() if line.startswith("files:")]


class Interrupted(Exception):
    """The host went down before the run's first turn."""


class TaskRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-files-told-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", config.RUN_DIR_ENV: "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@localhost",
            "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@localhost",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters)}))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            path = adapters / f"{harness}.sh"
            path.write_text(f"#!{sys.executable}\n{scripted(ADAPTER)}")
            path.chmod(0o755)
            stateful(path, self.root)
        for module, name, value in ((gc, "disk_pressure", False), (run, "launch_session", None),
                                    (run, "collect_usage", {}), (run, "pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(gitcall, "gh", side_effect=AssertionError("GitHub")))
        origin, self.repo = self.root / "origin.git", self.root / "acme"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        self.git(self.root, "clone", "-q", str(origin), str(self.repo))
        (self.repo / "AGENTS.md").write_text("---\nusers: none\n---\n# acme\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "api.py").write_text("broken\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "acme base")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "remote", "set-head", "origin", "main")
        self.opts = {"--rounds": None, "--exec": None, "--review": None,
                     "--no-worktree": False, "--no-merge": True}

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)

    def launch(self, front, interrupted=False):
        """A run of TASK under `front`, its first launch cut off before any turn when
        `interrupted`, then resumed; the run's first round."""
        directory = config.RUNS / "fix-api"
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\nrounds: 1\n{front}---\n{TASK}")
        logs = []
        prior = None
        if interrupted:
            with patch.object(run, "rounds", side_effect=Interrupted), self.assertRaises(Interrupted):
                run.loop(self.cfg, directory, task, self.opts, logs.append, None)
            prior = run.run_record.read_state(directory)
        state = run.loop(self.cfg, directory, task, self.opts, logs.append, prior)
        self.assertEqual(state["state"], "pass", logs)
        return directory / "round-1"

    def test_a_fresh_run_tells_every_worker_the_scope_once(self):
        rnd = self.launch("files: src/\n")
        for role in ("executor", "reviewer"):
            self.assertEqual(told(rnd / role / "prompt.md"), ["files: src/"], role)

    def test_a_resumed_run_tells_every_worker_the_scope_once(self):
        rnd = self.launch("files: src/\n", interrupted=True)
        for role in ("executor", "reviewer"):
            self.assertEqual(told(rnd / role / "prompt.md"), ["files: src/"], role)

    def test_a_task_without_files_tells_no_scope(self):
        rnd = self.launch("")
        for role in ("executor", "reviewer"):
            self.assertEqual(told(rnd / role / "prompt.md"), [], role)


class SeatsOwnPr(OwnPr):
    def reviewer(self, cfg, name, body, workspace, out_dir, role, session, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prompt.md").write_text(
            worker.PREAMBLES[role].format(workspace=workspace) + "\n\n" + body)
        return super().reviewer(cfg, name, body, workspace, out_dir, role, session, **kw)

    def fixer(self, lp, role, text, name):
        out = turns.free_dir(lp, name)
        summary = super().fixer(lp, role, text, name)
        (out / "prompt.md").write_text(worker.PREAMBLES[role].format(workspace=lp.wt) + "\n\n" + text)
        return summary

    def test_its_reviewer_and_fixer_are_told_the_scope_once(self):
        # An own PR's task.md is written by its review and names no files; the scope it would
        # hold reaches its workers as a task's does.
        with patch.object(taskfile, "task_files", return_value=["fence.txt"]), \
                patch.object(run, "ready_order", return_value=["astra", "opus"]), \
                patch.object(staffing, "ready_order", return_value=["astra", "opus"]):
            state = self.review(["FAIL", "PASS"])
        self.assertEqual([row["verdict"] for row in state["round_summaries"]], ["FAIL", "PASS"])
        prompts = sorted(self.run_dir.glob("round-*/*/prompt.md"))
        self.assertEqual({p.parent.name for p in prompts}, {"reviewer", "executor"}, prompts)
        for prompt in prompts:
            self.assertEqual(told(prompt), ["files: fence.txt"], prompt)

    def test_without_a_scope_none_is_told(self):
        with patch.object(run, "ready_order", return_value=["astra", "opus"]), \
                patch.object(staffing, "ready_order", return_value=["astra", "opus"]):
            self.review(["PASS"])
        prompt = self.run_dir / "round-1" / "reviewer" / "prompt.md"
        self.assertEqual(told(prompt), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
