"""Filing a seat under a project lists what the project's other seats have in flight.

Offline, with invented checkouts, seat records, plans and runs under a temporary HOME; the
one going run has a real git worktree, so its changed files come from git: committed and
uncommitted tracked changes count, an untracked lock file does not.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, orch
from agentkit import record as run_record


def git(tree, *argv):
    return subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t",
                           *argv], check=True, capture_output=True, text=True).stdout.strip()


class ProjectView(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "fix-api"}))
        self.acme = config.CODE / "acme"
        (self.acme / ".git").mkdir(parents=True)
        (config.CODE / "bramble" / ".git").mkdir(parents=True)
        for seat, repo in (("fix-api", None), ("design", self.acme), ("builder", self.acme),
                           ("idle", self.acme), ("elsewhere", config.CODE / "bramble")):
            config.save_session(self.cfg, seat, "fable", ["opus"],
                                {"cwd": str(config.CODE), "repo": str(repo) if repo else None})

    def plan(self, seat, text):
        config.plan_path(seat).write_text(text)

    def add_run(self, name, seat, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        run_record.save_state(directory, {"run_id": name, "launched_session": seat,
                                          "repo": str(self.acme), **state})

    def worktree(self):
        tree = self.root / "wt-builder"
        tree.mkdir()
        git(tree, "init", "-q")
        (tree / "app.py").write_text("one\n")
        (tree / "kept.py").write_text("same\n")
        git(tree, "add", ".")
        git(tree, "commit", "-qm", "base")
        base = git(tree, "rev-parse", "HEAD")
        (tree / "added.py").write_text("new\n")
        git(tree, "add", "added.py")
        git(tree, "commit", "-qm", "work")
        (tree / "app.py").write_text("two\n")
        (tree / "recovery.lock").write_text("")
        return tree, base

    def file(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", "acme"]), 0)
        return out.getvalue()

    def test_lists_other_seats_open_plan_lines_and_changed_files(self):
        self.plan("design", "- [x] vision merged\n- [ ] scoreboard (job 1)\n  - [ ] nested step\n")
        self.plan("fix-api", "- [ ] my own line\n")
        self.plan("elsewhere", "- [ ] another project's line\n")
        self.plan("idle", "- [x] all done\n")
        tree, base = self.worktree()
        self.add_run("r1", "builder", state="running", worktree=str(tree), base_sha=base)
        self.add_run("r2", "builder", state="pass", worktree=str(tree), base_sha=base,
                     finished_at=1)
        task = self.root / "t.md"
        task.write_text("---\nfiles: docs/guide.md, menu.py\n---\n# t\n")
        self.add_run("r3", "design", state="queued", task_file=str(task))
        out = self.file()
        self.assertEqual(out.splitlines(), [
            "filed fix-api under acme",
            "in flight on acme, plan around it:",
            "  builder",
            "    changing: added.py, app.py",
            "  design",
            "    plan: scoreboard (job 1)",
            "    plan: nested step",
            "    changing: docs/guide.md, menu.py",
        ])

    def test_nothing_in_flight_says_so(self):
        self.plan("idle", "- [x] all done\n")
        self.assertEqual(self.file().splitlines(),
                         ["filed fix-api under acme", "nothing else in flight on acme"])


if __name__ == "__main__":
    unittest.main()
