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
from fixtures.sandbox import Sandbox
from agentkit import config, orch, terminal
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
        if source := state.get("task_file"):
            (directory / "task.md").write_text(Path(source).read_text())
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
        task = self.root / "t.md"
        task.write_text("---\nfiles: docs/guide.md, menu.py\n---\n# t\n")
        self.add_run("r2", "builder", state="pass", task_file=str(task), finished_at=1)
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

    def test_queued_run_uses_its_saved_task_after_original_is_reused_or_removed(self):
        original = self.root / "t.md"
        original.write_text("---\nfiles: menu.py\n---\n# fix the menu\n")
        self.add_run("r1", "design", state="queued", task_file=str(original))
        expected = [("design", [], {"menu.py"})]
        original.write_text("---\nfiles: billing.py\n---\n# the next task\n")
        self.assertEqual(orch.in_flight("fix-api", self.acme), expected)
        original.unlink()
        self.assertEqual(orch.in_flight("fix-api", self.acme), expected)

    def test_renamed_seat_uses_its_latest_plan_and_owns_its_old_runs(self):
        config.rename_session("design", "design-api")
        config.rename_session("design-api", "design-ui")
        for seat, text, at in (("design-ui", "- [ ] stale line\n", 100),
                               ("design", "- [x] done\n- [ ] current line\n", 200)):
            self.plan(seat, text)
            os.utime(config.plan_path(seat), (at, at))
        task = self.root / "t.md"
        task.write_text("---\nfiles: docs/guide.md\n---\n# t\n")
        self.add_run("r1", "design", state="queued", task_file=str(task))
        self.assertEqual(orch.in_flight("fix-api", self.acme),
                         [("design-ui", ["current line"], {"docs/guide.md"})])
        self.plan("design-ui", "- [ ] new line\n")
        self.assertEqual(orch.in_flight("fix-api", self.acme)[0][1], ["new line"])

    def test_tracks_both_rename_paths_and_preserves_unusual_names(self):
        tree, base = self.worktree()
        git(tree, "mv", "kept.py", "moved.py")
        git(tree, "commit", "-qm", "rename")
        names = ["résumé.py", 'a"b.py', "line\nbreak.py"]
        for name in names:
            (tree / name).write_text("new\n")
        git(tree, "add", *names)
        self.add_run("r1", "builder", state="running", worktree=str(tree), base_sha=base)
        self.assertEqual(orch.in_flight("fix-api", self.acme),
                         [("builder", [], {"added.py", "app.py", "kept.py", "moved.py", *names})])

    def test_view_leaves_seat_records_plans_and_runs_unchanged(self):
        self.plan("design", "- [ ] current line\n")
        tree, base = self.worktree()
        self.add_run("r1", "builder", state="running", worktree=str(tree), base_sha=base)
        task = self.root / "t.md"
        task.write_text("---\nfiles: docs/guide.md\n---\n# t\n")
        self.add_run("r2", "design", state="queued", task_file=str(task))

        def snapshot():
            return {path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for root in (config.STATE, config.RUNS) for path in root.rglob("*")
                    if path.is_file()}

        before = snapshot()
        self.assertEqual(len(orch.in_flight("fix-api", self.acme)), 2)
        self.assertEqual(snapshot(), before)

    def test_long_plan_and_file_lines_wrap_through_terminal(self):
        line = "update the project view so every other session can see the open plan"
        self.plan("design", f"- [ ] {line}\n")
        task = self.root / "t.md"
        task.write_text("---\nfiles: docs/guide.md, agentkit/menu.py, README.md\n---\n# t\n")
        self.add_run("r1", "design", state="queued", task_file=str(task))
        with patch.object(terminal, "layout_width", return_value=40):
            lines = self.file().splitlines()
        content = [text for text in lines if text.startswith("    ")]
        self.assertTrue(all(terminal.cells(text) <= 40 for text in content))
        self.assertEqual(" ".join(text.strip() for text in content),
                         f"plan: {line} changing: README.md, agentkit/menu.py, docs/guide.md")

    def test_nothing_in_flight_says_so(self):
        self.plan("idle", "- [x] all done\n")
        self.assertEqual(self.file().splitlines(),
                         ["filed fix-api under acme", "nothing else in flight on acme"])


if __name__ == "__main__":
    unittest.main()
