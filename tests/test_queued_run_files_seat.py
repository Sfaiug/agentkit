"""A seat is filed under its project while its runs still wait for a slot.

A run votes for the seat that launched it from the moment it is queued: for the checkout its
task's `repo:` names, else for the one its task folder is named for, and for that same one once
it starts.  A seat whose record says no project is filed at the next menu draw or `ak watch`
tick once one of its runs votes, from the run records that pass has read anyway.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
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
        self.acme = config.CODE / "acme"
        self.acme.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.acme)], check=True)
        subprocess.run(["git", "-C", str(self.acme), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m",
                        "fixture"], check=True)
        config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                            {"cwd": str(config.CODE), "repo": None})
        self.seat = {"name": "fix-api", "path": str(config.CODE), "created": 9000,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))

    def task(self, name, repo):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(f"---\nrepo: {repo}\n---\n# Fix the API\n\n"
                                           "## Done when\n```bash\ntrue\n```\n")
        return directory

    def launch(self, name, repo, task_file=None):
        """`ak run` from the seat: the receipt waits for a slot, as the three seats' did."""
        directory = self.task(name, repo)
        with patch.dict(os.environ, {config.SESSION_ENV: "fix-api", "AK_RUN_DEPTH": "0",
                                     "AK_MAX_RUNS": "4"}), \
                patch.object(run, "refresh_seat_tally"):
            run.capture_launch(directory, {}, task_file=task_file)
        self.assertEqual(run.read_state(directory)["state"], "queued")
        return directory

    def waiting(self, name, repo):
        """A receipt queued before a queued run had a vote: nothing filed its seat."""
        directory = self.task(name, repo)
        run.save_state(directory, {"run_id": name, "state": "queued", "slot_waiting": True,
                                   "launched_session": "fix-api", "started_at": 9000,
                                   "queued_at": 9000, **run.process_owner()})
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

    def test_a_projectless_seat_whose_queued_runs_name_one_checkout_is_filed_at_the_next_tick(self):
        self.waiting("q1", self.acme)
        watch.revive_seats(self.cfg, lambda _: None)
        self.assertEqual(self.repo(), str(self.acme))

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
        for name, repo, task_file in (("named", self.acme, None),
                                      ("scratch", "none", tasks / "check.md")):
            with self.subTest(name):
                config.update_session("fix-api", repo=None)
                directory = self.launch(name, repo, task_file)
                self.assertEqual(run.run_project(run.read_state(directory)), self.acme)
                self.assertEqual(self.repo(), str(self.acme))
                worktree = self.root / f"wt-{name}"
                worktree.mkdir()
                seen = []

                def rounds(lp):
                    seen.append((lp.state["repo"], run.run_project(lp.state), self.repo()))

                with patch.dict(os.environ, {config.SESSION_ENV: "other", "AK_RUN_DEPTH": "0",
                                             "AK_MAX_RUNS": "0"}), \
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
                started = str(self.acme) if repo != "none" else None
                self.assertEqual(seen, [(started, self.acme, str(self.acme))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
