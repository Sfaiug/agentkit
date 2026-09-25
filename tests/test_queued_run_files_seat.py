"""A seat is filed under its project while its runs still wait for a slot.

A run votes for the seat that launched it from the moment it is queued: for the checkout its
task's `repo:` names, else for the one its task folder is named for, never for one it merely
inherits, and for the same one once it starts.  A seat whose record says no project is filed at the next menu draw or
`ak watch` tick once one of its runs votes, from the run records that pass has read anyway.
"""

from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, menu, orch, run, terminal, watch


class QueuedRunFilesSeat(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)     # Sandbox's patch.dict puts them back
        self.acme, self.beta = self.checkout("acme"), self.checkout("beta")
        config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                            {"cwd": str(config.CODE), "repo": None})
        self.seat = {"name": "fix-api", "path": str(config.CODE), "created": 9000,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))

    def checkout(self, name):
        checkout = config.CODE / name
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m",
                        "fixture"], check=True)
        return checkout

    def task(self, name, repo):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        front = f"---\nrepo: {repo}\n---\n" if repo is not None else ""
        (directory / "task.md").write_text(f"{front}# Fix the API\n\n"
                                           "## Done when\n```bash\ntrue\n```\n")
        return directory

    def launch(self, name, repo, task_file=None, where=REPO):
        """`ak run` from the seat, standing in `where`: the receipt waits for a slot."""
        directory = self.task(name, repo)
        opts = {"--no-merge": False, "--no-worktree": False, "--anyway": False, "--bg": False}
        with chdir(where), patch.dict(os.environ, {config.SESSION_ENV: "fix-api",
                                                   "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "4"}), \
                patch.object(run, "refresh_seat_tally"), redirect_stdout(io.StringIO()):
            run.prepare(directory, opts, lambda _: None, task_file=task_file)
        self.assertEqual(run.read_state(directory)["state"], "queued")
        return directory

    def waiting(self, name, repo, **extra):
        """A receipt from before a queued run had a vote: nothing filed its seat."""
        directory = self.task(name, repo)
        run.save_state(directory, {"run_id": name, "state": "queued", "slot_waiting": True,
                                   "launched_session": "fix-api", "started_at": 9000,
                                   "queued_at": 9000, **run.process_owner(), **extra})
        return directory

    def repo(self):
        return config.load_session(self.cfg, "fix-api")["repo"]

    def test_a_seat_whose_only_run_is_queued_is_filed_at_launch(self):
        directory = self.launch("q1", self.acme)
        self.assertNotIn("repo", run.read_state(directory))
        self.assertEqual(run.run_project(run.read_state(directory)), self.acme)
        self.assertEqual(self.repo(), str(self.acme))

    def test_a_projectless_seat_whose_queued_runs_name_one_checkout_is_filed_at_the_next_draw(self):
        self.waiting("q1", self.acme)
        self.waiting("q2", self.acme)
        self.assertIsNone(self.repo())
        # Filed from the records the draw reads anyway: no run.json twice.
        with patch.object(run, "read_state", wraps=run.read_state) as read, \
                patch.object(menu, "wait_key", return_value="q"), \
                patch.object(menu, "read", return_value="q"), \
                patch.object(menu.Live, "look"), \
                patch.object(menu.Live, "probe", return_value=False), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(terminal, "width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertEqual(sorted(call.args[0].name for call in read.call_args_list), ["q1", "q2"])
        self.assertEqual(self.repo(), str(self.acme))
        lines = [line.strip() for line in out.getvalue().splitlines()]
        self.assertIn("acme", lines)
        self.assertNotIn("no project", lines)
        self.assertLess(lines.index("acme"),
                        next(at for at, line in enumerate(lines) if "fix-api" in line))

    def test_a_projectless_seat_is_filed_at_the_next_tick_with_no_run_going(self):
        # Its queued run ended before it ever started: nothing is going, and it still votes.
        self.waiting("q1", self.acme, state="error")
        watch.revive_seats(self.cfg, lambda _: None)
        self.assertEqual(self.repo(), str(self.acme))

    def test_a_draw_read_before_a_launch_never_overwrites_its_count(self):
        self.waiting("q1", self.acme)
        found, runs = orch.listing(), [state for _, state in menu.run_records()]
        config.update_session("fix-api", repo=str(self.beta))   # a launch counted meanwhile
        orch.file_projectless(found, runs)
        self.assertEqual(self.repo(), str(self.beta))

    def test_a_seat_with_no_voting_runs_stays_no_project(self):
        # A task naming no repository, filed under no folder or one no checkout is named for.
        self.launch("loose", "none", self.root / "notes" / "check.md")
        self.launch("notes", "none", config.HOME / "tasks" / "notes" / "check.md")
        self.assertIsNone(self.repo())
        before = config.session_path("fix-api").read_bytes()
        runs = [state for _, state in menu.run_records()]
        self.assertEqual(len(runs), 2)
        found = orch.listing()
        orch.file_projectless(found, runs)
        self.assertEqual([seat["repo"] for seat in found], [None])
        watch.revive_seats(self.cfg, lambda _: None)
        self.assertEqual(config.session_path("fix-api").read_bytes(), before)
        with redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, found, look=False)
        self.assertIn("no project", [line.strip() for line in out.getvalue().splitlines()])

    def test_a_started_run_still_votes_for_the_same_project(self):
        tasks = config.HOME / "tasks" / "acme"
        # (run, task's repo:, task file, where it is launched, the project it votes for)
        for name, repo, task_file, where, project in (
                ("named", self.acme, None, REPO, self.acme),
                ("scratch", "none", tasks / "check.md", REPO, self.acme),
                ("relative", ".", None, self.acme, self.acme),
                ("inherited", None, tasks / "check.md", self.beta, self.acme)):
            with self.subTest(name):
                shutil.rmtree(config.RUNS)                # this run the seat's only one
                config.update_session("fix-api", repo=None)
                directory = self.launch(name, repo, task_file, where)
                # read from anywhere, by a draw, a tick or a later launch: the same vote
                with chdir(self.beta if where != self.beta else self.acme):
                    self.assertEqual(run.run_project(run.read_state(directory)), project)
                self.assertEqual(self.repo(), str(project))
                worktree = self.root / f"wt-{name}"
                worktree.mkdir()
                seen = []

                def rounds(lp):
                    seen.append((run.run_project(lp.state), self.repo()))

                with chdir(where), patch.dict(os.environ, {
                            config.SESSION_ENV: "other", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}), \
                        patch.object(run, "disk_pressure", return_value=False), \
                        patch.object(run, "make_worktree", return_value=(worktree, "ak/fixture")), \
                        patch.object(run, "exclude_junk"), \
                        patch.object(run, "pick_models", return_value=("opus", "astra")), \
                        patch.object(run, "rounds", side_effect=rounds), \
                        patch.object(run, "write_result"), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    run.loop(self.cfg, directory, directory / "task.md",
                             {"--rounds": "1", "--no-worktree": False, "--no-merge": True,
                              "--exec": None, "--review": None}, lambda _: None)
                self.assertEqual(seen, [(project, str(project))])
        # A receipt from before the field: the same vote queued and once it works in `beta`.
        legacy = run.read_state(self.waiting("legacy", None, task_file=str(tasks / "check.md")))
        for state in (legacy, {**legacy, "repo": str(self.beta), "scratch": False}):
            self.assertEqual(run.run_project(state), self.acme)

    def test_legacy_runs_with_a_relative_repo_keep_the_checkout_they_worked_in(self):
        # Two runs from before `project`, whose task says `repo: .`, worked in `acme`: they vote
        # for the checkout their record names, and one new `beta` run does not refile their seat.
        # Before such a run starts nobody else knows what `.` meant, and it has no vote.
        self.assertIsNone(run.run_project(run.read_state(self.waiting("q1", "."))))
        for name in ("l1", "l2"):
            directory = self.waiting(name, ".", state="pass", slot_waiting=False)
            run.save_state(directory, {**run.read_state(directory), "repo": str(self.acme)})
        self.launch("b1", self.beta)
        self.assertEqual(self.repo(), str(self.acme))


if __name__ == "__main__":
    unittest.main(verbosity=2)
