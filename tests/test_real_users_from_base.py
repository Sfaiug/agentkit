"""A branch cannot switch its own reviewer's real-users rule on or off.

The `users:` line is read at the base the work is judged against, never the branch's
files: a branch that turns origin's `users: real` into `users: none` is still reviewed
with REAL_USERS, and one that turns `users: none` into `users: real` is not until it has
merged.  Offline: a throwaway repository and its bare origin, a fake adapter for every
harness, a temporary HOME.
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
from fixtures.hand_in import scripted, stateful
from agentkit import config, gc, gitcall, run, worker

TASK = "# Acme users\n\n## Goal\nTouch AGENTS.md.\n\n## Done when\n```bash\ntrue\n```\n"

# The executor commits the branch's AGENTS.md; the reviewer passes.  Every prompt is kept.
ADAPTER = '''import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["USERS_BASE_FIXTURE"])
if sys.argv[1] == "auth":
    print("fixture token")
    sys.exit(0)
cwd, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
with (root / "prompts.jsonl").open("a") as fh:
    fh.write(json.dumps(prompt) + "\\n")
if prompt.startswith("You are the reviewer"):
    text = "VERDICT: PASS\\n\\n## Findings\\n"
else:
    (cwd / "AGENTS.md").write_text((root / "branch.md").read_text())
    subprocess.run(["git", "-C", str(cwd), "commit", "-qam", "acme users"], check=True)
    text = "## Summary\\nChanged the users line."
(out / "final.md").write_text(text)
'''


class RealUsersFromBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-users-base-", dir=REPO)
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
            "PYTHONDONTWRITEBYTECODE": "1", "USERS_BASE_FIXTURE": str(self.root),
            config.ADAPTER_DIR_ENV: str(adapters)}))
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

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)

    def reviews(self, origin_users, branch_users):
        """Every reviewer prompt of one run whose branch changes origin's `users:` line."""
        (self.root / "prompts.jsonl").unlink(missing_ok=True)
        case = self.root / origin_users
        origin, repo = case / "origin.git", case / "acme"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        self.git(self.root, "clone", "-q", str(origin), str(repo))
        (repo / "AGENTS.md").write_text(f"---\nusers: {origin_users}\n---\n# acme\n")
        (self.root / "branch.md").write_text(f"---\nusers: {branch_users}\n---\n# acme\n")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "acme base")
        self.git(repo, "push", "-q", "origin", "main")
        self.git(repo, "remote", "set-head", "origin", "main")
        directory = config.RUNS / f"acme-{origin_users}"
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {repo}\nrounds: 1\n---\n{TASK}")
        opts = {"--rounds": None, "--exec": None, "--review": None,
                "--no-worktree": False, "--no-merge": True}
        logs = []
        state = run.loop(self.cfg, directory, task, opts, logs.append, None)
        self.assertEqual(state["state"], "pass", logs)
        self.assertIn(f"users: {branch_users}", gitcall.git(Path(state["worktree"]), "show",
                                                            "HEAD:AGENTS.md"))
        prompts = [json.loads(line) for line in
                   (self.root / "prompts.jsonl").read_text().splitlines()]
        reviews = [p for p in prompts if p.startswith("You are the reviewer")]
        self.assertTrue(reviews, prompts)
        return reviews

    def test_a_branch_turning_real_into_none_is_still_reviewed_as_real(self):
        for prompt in self.reviews("real", "none"):
            self.assertIn(f"{worker.GATE}\n{worker.REAL_USERS}", prompt)

    def test_a_branch_turning_none_into_real_is_not_until_it_merges(self):
        for prompt in self.reviews("none", "real"):
            self.assertIn(worker.GATE, prompt)
            self.assertNotIn(worker.REAL_USERS, prompt)


if __name__ == "__main__":
    unittest.main()
