"""Every worker gets the same rules from ak itself, whatever its harness loads on its own.

The repository's AGENTS.md body rides the executor, fixer and reviewer prompts as it is on
the base commit; no prompt asks a worker to run the `# once` suite; a fixer gets the
review's findings and never its follow-ups.  Offline: a throwaway repository, a fake
adapter for every harness, a temporary HOME.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

TASK = "# Acme rules\n\n## Goal\nTouch acme.txt.\n\n## Done when\n```bash\ntrue\n```\n"
RULES = "---\ntests: echo acme-suite\nusers: none\n---\n# acme\n\n- Name every fixture acme.\n"
BODY = "# acme\n\n- Name every fixture acme."
SECTION = ("## Repository AGENTS.md\nThe repository's own instructions, as on the base commit. "
           "Where they differ from the rest of this prompt, the rest of this prompt wins.\n\n"
           f"{BODY}\n")
FINDING = "acme.txt:1 - acme finding - the file is empty"
FOLLOWUP = "old.py:1 - acme follow-up - base abc123: `old()` raises"

# One turn: record the prompt, then answer as its role would.  The first review fails
# with a finding and a follow-up.
ADAPTER = '''import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["SAME_RULES_FIXTURE"])
if sys.argv[1] == "auth":
    print("fixture token")
    sys.exit(0)
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
calls = root / "calls.jsonl"
reviews = sum(json.loads(l)["prompt"].startswith("You are the reviewer")
              for l in calls.read_text().splitlines()) if calls.exists() else 0
with calls.open("a") as fh:
    fh.write(json.dumps({"prompt": prompt}) + "\\n")
if prompt.startswith("You are the reviewer"):
    text = ("VERDICT: FAIL\\n\\n## Findings\\n- %s\\n\\n## Follow-ups\\n- %s\\n" % (FINDING, FOLLOWUP)
            if reviews == 0 else "VERDICT: PASS\\n\\n## Findings\\n")
else:
    with (cwd / "acme.txt").open("a") as fh:
        fh.write("acme\\n")
    subprocess.run(["git", "-C", str(cwd), "add", "."], check=True)
    subprocess.run(["git", "-C", str(cwd), "commit", "-qm", "acme work"], check=True)
    text = "## Summary\\nDid the acme work."
(out / "final.md").write_text(text)
'''.replace("FINDING", repr(FINDING)).replace("FOLLOWUP", repr(FOLLOWUP))


class SameRules(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".same-rules-", dir=REPO)
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
            "PYTHONDONTWRITEBYTECODE": "1", "SAME_RULES_FIXTURE": str(self.root),
            config.ADAPTER_DIR_ENV: str(adapters)}))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            path = adapters / f"{harness}.sh"
            path.write_text(f"#!{sys.executable}\n{ADAPTER}")
            path.chmod(0o755)
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        for name, value in (("disk_pressure", False), ("launch_session", None),
                            ("collect_usage", {}), ("pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def launch(self):
        self.git("add", ".")
        self.git("commit", "-q", "--allow-empty", "-m", "acme base")
        directory = config.RUNS / "acme-run"
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\nbase: main\nrounds: 2\n---\n{TASK}")
        opts = {"--rounds": None, "--exec": None, "--review": None,
                "--no-worktree": False, "--no-merge": True}
        logs = []
        state = run.loop(self.cfg, directory, task, opts, logs.append, None)
        self.assertEqual(state["state"], "pass", logs)
        self.state = state
        calls = (self.root / "calls.jsonl").read_text().splitlines()
        prompts = [json.loads(line)["prompt"] for line in calls]
        roles = {"You are the executor. Work": "executor",
                 "You are the executor, continuing": "fixer", "You are the reviewer": "reviewer"}
        return [(next(r for start, r in roles.items() if p.startswith(start)), p)
                for p in prompts]

    def test_every_role_carries_agents_body_and_none_runs_the_suite(self):
        (self.repo / "AGENTS.md").write_text(RULES)
        prompts = self.launch()
        self.assertEqual([role for role, _ in prompts],
                         ["executor", "reviewer", "fixer", "reviewer"])
        for role, prompt in prompts:
            with self.subTest(role=role):
                self.assertEqual(prompt.count("## Repository AGENTS.md"), 1)
                self.assertIn(SECTION, prompt)
                self.assertNotIn("users: none", prompt)
                self.assertNotIn("before you hand over", prompt)
        executor = prompts[0][1]
        self.assertIn("The loop runs these once, in the final check on the commit about to "
                      "ship; do not run them yourself:\n  $ echo acme-suite", executor)
        self.assertEqual(executor.count("echo acme-suite"), 1)
        # the base commit's file, never the checkout's: the work cannot rewrite its rules
        wt = Path(self.state["worktree"])
        (wt / "AGENTS.md").write_text("# rewritten on the branch\n")
        self.assertEqual(run.repo_rules(wt, self.state["base_sha"], print), "\n\n" + SECTION)

    def test_fixer_gets_findings_without_follow_ups(self):
        prompts = self.launch()
        fixer = next(prompt for role, prompt in prompts if role == "fixer")
        findings = fixer.split("## Reviewer findings to fix\n", 1)[1]
        self.assertIn(FINDING, findings)
        self.assertNotIn("Follow-ups", findings)
        self.assertNotIn(FOLLOWUP, fixer)

    def test_repository_without_agents_md_adds_nothing(self):
        for role, prompt in self.launch():
            with self.subTest(role=role):
                self.assertNotIn("## Repository AGENTS.md", prompt)


if __name__ == "__main__":
    unittest.main()
