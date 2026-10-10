"""The stage the lease tests play on: a repository with one checkout per live run.

A throwaway HOME, a real repository, runs cut from its base with a worktree and a record
each (`run_on`, with a session record where it names a seat), a colliding pair of them
(`collide`), and edits to a checkout, committed or not (`edit`).  A run is past its
executor turn unless told otherwise, so the scan only writes it down; `step="executor"`
with `rounds=0` is one still building.  Offline.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
OLDER, YOUNGER = "20260101-0900-older", "20260101-1000-younger"
TASK = "---\nrepo: acme\n---\n# Change line 5\n\nChange it.\n\n## Done when\n```bash\ntrue\n```\n"
from agentkit import config, orch  # noqa: E402  - the suite puts the checkout on the path
from agentkit import record  # noqa: E402


class LiveRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-leases-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        # a stop ends a run's scope where the host has a manager; this stage has none
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git(self.repo, "init", "-qb", "main")
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "api.py").write_text("".join(f"line {n}\n" for n in range(1, 21)))
        (self.repo / "other.py").write_text("other\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Base")
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.logs = []

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def run_on(self, name, started, state="running", base=None, repo=None, artifacts=(),
               step="reviewer", rounds=1, session=None):
        """A live run of the repository with a checkout of its own, cut from `base`; `repo` is
        the checkout it was launched from, the main one unless given; `artifacts` what its
        checks generated, as it writes them down; `step` and `rounds` where its loop stands,
        past its first review unless told otherwise; `session` the seat it was launched from."""
        worktree = config.WT / name
        self.git(self.repo, "worktree", "add", "-q", "-b", f"ak/{name}", str(worktree), base or self.base)
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        record.save_state(directory, {
            "run_id": name, "state": state, "repo": str(repo or self.repo),
            "worktree": str(worktree), "branch": f"ak/{name}", "base_sha": base or self.base,
            "started_at": started, "artifacts": list(artifacts), "step": step,
            "round_summaries": [{"round": n, "verdict": "FAIL"} for n in range(1, rounds + 1)],
            "launched_session": session})
        if session and session not in config.session_records():
            config.save_session(config.load(), session, "opus", ["opus"], {"cwd": str(self.root)})
        return worktree

    def collide(self, step="executor", rounds=0, session=None):
        """An older run that changed line 5, and a younger one changing it too, uncommitted."""
        older = self.run_on(OLDER, 900, step="executor", rounds=0)
        younger = self.run_on(YOUNGER, 1000, step=step, rounds=rounds, session=session)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        return older, younger

    def state(self, name):
        return record.read_state(config.RUNS / name)

    def edit(self, worktree, path, line, text, commit=False):
        lines = (worktree / path).read_text().splitlines()
        lines[line - 1] = text
        (worktree / path).write_text("".join(f"{each}\n" for each in lines))
        if commit:
            self.git(worktree, "commit", "-qam", f"edit {path}:{line}")
