"""The new-session questions a line at a time, and the project a session is filed under.

After the name, a terminal shows one screen of selectors (tests/test_new_session_screen.py);
a pipe asks the orchestrator and workers a line at a time. Enter leaves naming to the seat.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox, menu_input
from agentkit import config, gc, menu, notify, orch, run, terminal, usage
from agentkit import record as run_record

COLLECT, SESSIONS = usage.collect, orch.sessions    # the real ones, for the dry run


class NewSession(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "fresh_command", return_value=(["fake"], None)))
        self.stack.enter_context(patch.object(orch, "launch"))
        self.stack.enter_context(patch.object(menu, "open_session"))

    def answers(self, values):
        sequence = iter(values)
        def typed(prompt=""):
            print(prompt, end="")
            return next(sequence, None)
        return patch.object(terminal, "readline", side_effect=typed)

    def new(self, values):
        with self.answers(values), redirect_stdout(io.StringIO()):
            return menu.new_session(self.cfg, False)

    def test_enter_three_times_creates_defaults(self):
        self.assertEqual(self.new(["", "", ""]), "new")
        record = config.load_session(self.cfg, "new")
        self.assertEqual(record["orchestrator"], "opus")
        self.assertEqual(record["workers"], self.cfg["defaults"]["workers"])
        self.assertIsNone(record["repo"])

    def test_a_taken_name_repeats_with_its_refusal_above_the_keys(self):
        keys = [*[terminal.Key("char", char) for char in "fix-api"],
                terminal.Key("enter"), terminal.Key("esc")]
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "layout_width", return_value=40), \
                patch.object(terminal, "read_key", side_effect=keys), \
                redirect_stdout(io.StringIO()) as out:
            self.assertIs(orch.ask_name({"fix-api"}, auto=True, screen="new session"), orch.BACK)
        last = out.getvalue().split("\x1b[H")[-1].split("\x1b[J")[0]
        lines = [terminal.ANSI.sub("", line) for line in last.splitlines()]
        self.assertEqual(lines[2], "  Name: auto")
        self.assertIn("a session named fix-api is already there; pick another name",
                      " ".join(line.strip() for line in lines[3:-2]))
        self.assertEqual(lines[-2:], ["", "  esc back"])
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))

    def test_workers_by_numbers(self):
        for raw, expected in (("2", ["opus"]), ("2, 4", ["opus", "spark"])):
            with self.subTest(raw=raw):
                name = self.new(["", "", raw])
                self.assertEqual(config.load_session(self.cfg, name)["workers"], expected)

    def test_workers_by_names(self):
        for raw, expected in (("opus", ["opus"]), ("astra fable", ["astra", "fable"])):
            with self.subTest(raw=raw):
                name = self.new(["", "", raw])
                self.assertEqual(config.load_session(self.cfg, name)["workers"], expected)

    def test_workers_all(self):
        self.assertEqual(self.new(["", "", "all"]), "new")
        self.assertEqual(config.load_session(self.cfg, "new")["workers"], config.offered(self.cfg))

    def test_empty_worker_set_is_refused(self):
        with self.answers(["", "", ",", "all"]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.new_session(self.cfg, True), "new")
        self.assertIn("not a choice: ','", out.getvalue())

    def test_esc_at_last_prompt_creates_nothing(self):
        self.assertIsNone(self.new(["", "", "\x1b"]))
        self.assertEqual(list(config.STATE.glob("session-*.json")), [])

    def test_login_error_keeps_the_menu_open(self):
        with self.answers(["", "", ""]), menu_input(side_effect=["n", ""]) as keys, \
                patch.object(menu, "Live", **{"return_value.heard.return_value": []}), \
                patch.object(terminal.Keyboard, "take", return_value=False), \
                patch.object(orch, "create", side_effect=config.Error("no working seat login")), \
                patch.object(menu, "pause") as pause, redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg), 0)
        pause.assert_called_once_with("new session: no working seat login")
        self.assertEqual(keys.call_count, 2)
        menu.open_session.assert_not_called()
        self.assertEqual(list(config.STATE.glob("session-*.json")), [])

    def test_unique_name_keeps_its_number_inside_the_cap(self):
        long = "m" * orch.NAME_CAP
        self.assertEqual(orch.unique_name(long, {long}), "m" * (orch.NAME_CAP - 2) + "-2")
        taken = {long, "m" * (orch.NAME_CAP - 2) + "-2"}
        name = orch.unique_name(long + "-longer", taken)
        self.assertEqual(name, "m" * (orch.NAME_CAP - 2) + "-3")
        self.assertEqual(orch.session_name(name), name)       # what `create` will call it

    def test_a_dry_run_says_what_it_would_start_and_creates_no_session(self):
        # the real listing and usage reading, over a `tmux` that writes down each call, no
        # adapters, and a usage cache every provider was asked for just now
        calls, tmux = self.root / "tmux-calls", self.root / "bin" / "tmux"
        tmux.parent.mkdir()
        tmux.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 1\n')
        tmux.chmod(0o755)
        now = time.time()
        for name in self.cfg["providers"]:
            (config.STATE / f"{name}-probe.lock").write_text(repr(now))
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": now, "providers": {
            name: {"meters": [], "resets": 0} for name in self.cfg["providers"]}}))
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{tmux.parent}:{os.environ['PATH']}", config.ADAPTER_DIR_ENV: str(tmux.parent)}))
        self.stack.enter_context(patch.object(usage, "collect", COLLECT))
        self.stack.enter_context(patch.object(orch, "sessions", SESSIONS))
        with self.answers(["", "3", ""]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.new_session(self.cfg, True), "new")
        self.assertIn("would start new: astra, workers opus astra", out.getvalue())
        self.assertEqual(list(config.STATE.glob("session-*.json")), [])
        self.assertTrue(calls.read_text())          # the real listing asked, and only listed
        self.assertEqual([call for call in calls.read_text().splitlines()
                          if "list-sessions" not in call.split()], [])

    def checkout(self, name, root=None):
        checkout = (root or config.CODE) / name
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m", "fixture"],
                       check=True)
        return checkout

    def run_repo(self, repo, expected, name, task_file=None):
        directory = config.RUNS / name
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {repo or 'none'}\n---\n# First project\n"
                        "\n## Done when\n```bash\ntrue\n```\n")
        with patch.dict(os.environ, {config.SESSION_ENV: "seat", "AK_MAX_RUNS": "0"}), \
                patch.object(run, "redress_seat"):
            run.capture_launch(directory, {}, task_file=task_file)
        worktree = self.root / name
        worktree.mkdir()
        opts = {"--rounds": "1", "--no-worktree": False, "--no-merge": True,
                "--exec": None, "--review": None}

        def rounds(lp):
            self.assertEqual(lp.state["launched_session"], "seat")
            self.assertEqual(lp.state["repo"], str(repo) if repo else None)
            self.assertEqual(config.load_session(self.cfg, "seat").get("repo"), expected)

        # The receipt owns the run even when the current process belongs to another seat.
        with patch.dict(os.environ, {config.SESSION_ENV: "other"}), \
                patch.object(gc, "disk_pressure", return_value=False), \
                patch.object(run, "make_worktree", return_value=(worktree, "ak/fixture")), \
                patch.object(run, "exclude_junk"), \
                patch.object(run, "pick_models", return_value=("opus", "astra")), \
                patch.object(run, "rounds", side_effect=rounds) as started, \
                patch.object(run, "write_result"), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            run.loop(self.cfg, directory, task, opts, lambda _: None)
        started.assert_called_once()

    def test_first_run_from_projectless_session_sets_checkout(self):
        checkout = self.checkout("one")
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE)})
        self.run_repo(checkout, str(checkout), "first")
        self.assertEqual(config.load_session(self.cfg, "seat")["repo"], str(checkout))

    def test_most_runs_decide_the_project_at_each_launch(self):
        first, second = self.checkout("one"), self.checkout("two")
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE)})
        self.run_repo(first, str(first), "first")
        # One run each is a tie, and a tie keeps the project the session has.
        with patch.object(config, "update_session", wraps=config.update_session) as update:
            self.run_repo(second, str(first), "second")
        update.assert_not_called()
        self.run_repo(second, str(second), "third")
        self.assertEqual(config.load_session(self.cfg, "seat")["repo"], str(second))

    def test_scratch_run_counts_for_its_task_folder(self):
        # agentkit's own checkout is ~/agentkit, beside ~/code, and a project all the same.
        own = self.checkout("agentkit", Path.home())
        tasks = config.HOME / "tasks"
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE), "repo": None})
        # A folder no checkout is named for gives a scratch run no vote.
        self.run_repo(None, None, "notes", tasks / "notes" / "check.md")
        self.run_repo(None, str(own), "scratch", tasks / "agentkit" / "check.md")

    def test_a_worktree_beside_a_checkout_is_that_checkout(self):
        # Seats add worktrees under ~/code for their own work: none is a project of its own,
        # and a PR review takes the checkout, never a seat's worktree that sorts before it.
        main = self.checkout("acme")
        subprocess.run(["git", "-C", str(main), "remote", "add", "origin",
                        "git@github.com:me/acme.git"], check=True)
        linked = config.CODE / ".acme-fix"
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "fix", str(linked)],
                       check=True)
        self.assertIn(main, orch.checkouts())
        self.assertNotIn(linked, orch.checkouts())
        self.assertEqual(orch.checkout_of(str(linked)), main)
        (linked / "app").mkdir()
        self.assertEqual(orch.cwd_project(linked / "app"), main)
        self.assertEqual(run.checkout_for("me/acme", print), main)

    def test_a_worktree_is_its_checkout_whatever_the_git_layout(self):
        # A checkout keeping its git directory elsewhere, and a worktree whose `.git` names
        # its git directory by a relative path: git reads both, and so does the menu.
        elsewhere = self.root / "elsewhere.git"
        main = config.CODE / "acme"
        subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir", str(elsewhere),
                        str(main)], check=True)
        subprocess.run(["git", "-C", str(main), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m", "x"],
                       check=True)
        added, relative, linked_dir = (config.CODE / name for name in
                                       (".acme-fix", ".acme-relative", ".acme-linked-dir"))
        for linked, branch in ((added, "fix"), (relative, "relative"), (linked_dir, "dir")):
            subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", branch,
                            str(linked)], check=True)
        absolute = (relative / ".git").read_text().strip().removeprefix("gitdir: ")
        (relative / ".git").write_text("gitdir: " + os.path.relpath(absolute, relative) + "\n")
        # A `.git` link to the worktree's own git directory: a directory, with its commondir.
        absolute = (linked_dir / ".git").read_text().strip().removeprefix("gitdir: ")
        (linked_dir / ".git").unlink()
        (linked_dir / ".git").symlink_to(absolute)
        for linked in (relative, linked_dir):
            subprocess.run(["git", "-C", str(linked), "status", "-s"], check=True)
        self.assertIn(main, orch.checkouts())
        for linked in (added, relative, linked_dir):
            self.assertNotIn(linked, orch.checkouts())
            self.assertEqual(orch.checkout_of(str(linked)), main)

    def test_a_worktree_of_a_second_agentkit_clone_is_agentkit(self):
        own = self.checkout("agentkit", Path.home())
        for layout in ([], ["--separate-git-dir", str(self.root / "clone.git")]):
            with self.subTest(layout=layout):
                clone = config.CODE / "agentkit"
                subprocess.run(["git", "init", "-q", "-b", "main", *layout, str(clone)], check=True)
                subprocess.run(["git", "-C", str(clone), "-c", "user.name=Fixture", "-c",
                                "user.email=fixture@localhost", "commit", "-q", "--allow-empty",
                                "-m", "x"], check=True)
                linked = config.CODE / ".agentkit-fix"
                subprocess.run(["git", "-C", str(clone), "worktree", "add", "-q", "-b", "fix",
                                str(linked)], check=True)
                self.assertEqual(orch.checkouts().count(own), 1)
                self.assertNotIn(linked, orch.checkouts())
                self.assertEqual(orch.checkout_of(str(linked)), own)
                self.assertEqual(orch.cwd_project(linked), own)
                for path in (clone, linked, self.root / "clone.git"):
                    shutil.rmtree(path, ignore_errors=True)

    def test_scratch_run_keeps_session_projectless(self):
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE), "repo": None})
        before = config.session_path("seat").read_bytes()
        self.run_repo(None, None, "scratch")
        self.assertEqual(config.session_path("seat").read_bytes(), before)

    def test_a_pr_review_launch_votes_too(self):
        checkout = self.checkout("one")
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE), "repo": None})
        directory = config.RUNS / "review"
        directory.mkdir()
        with patch.dict(os.environ, {config.SESSION_ENV: "seat", "AK_MAX_RUNS": "0"}), \
                patch.object(run, "redress_seat"):
            run.capture_launch(directory, {})
        info = {"state": "OPEN", "headRefOid": "f" * 40, "baseRefName": "main", "title": "Fix",
                "author": "someone", "body": ""}

        class Picked(Exception):
            pass

        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=checkout), \
                patch.object(gc, "disk_pressure", return_value=False), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "git", return_value="f" * 40), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "make_worktree", return_value=(self.root / "review", "ak/pr-7")), \
                patch.object(run, "exclude_junk"), \
                patch.object(run, "collect_usage", side_effect=Picked), \
                self.assertRaises(Picked):
            run.review_pr(self.cfg, directory, "https://github.com/owner/one/pull/7", {},
                          lambda _: None)
        self.assertEqual(config.load_session(self.cfg, "seat")["repo"], str(checkout))

    def test_a_count_waits_for_the_one_before_it(self):
        # A launch counts only once the session is its alone, so a count taken before later
        # runs reached the disk can never be written after theirs.
        alpha, beta = self.checkout("alpha"), self.checkout("beta")
        config.save_session(self.cfg, "seat", "fable", ["opus"], {"cwd": str(config.CODE), "repo": None})

        def ran(name, repo):
            (config.RUNS / name).mkdir()
            run_record.save_state(config.RUNS / name, {"launched_session": "seat", "repo": str(repo)})

        for name, repo in (("a1", alpha), ("b1", beta), ("b2", beta)):
            ran(name, repo)
        with notify.session_lock("seat"):
            late = threading.Thread(target=run.join_session_project, args=("seat",))
            late.start()
            late.join(1)
            self.assertTrue(late.is_alive())
            ran("a2", alpha)
            ran("a3", alpha)
        late.join(10)
        self.assertFalse(late.is_alive())
        self.assertEqual(config.load_session(self.cfg, "seat")["repo"], str(alpha))

    def test_named_orch_accepts_one_worker(self):
        for raw in ("2", "opus"):
            name = f"single-{raw}"
            with self.subTest(raw=raw), self.answers(["", raw]), \
                    redirect_stdout(io.StringIO()) as out:
                self.assertEqual(orch.main([name, "--dry-run"]), 0)
            self.assertIn("\nworkers opus\n", out.getvalue())

    def test_picker_uses_the_saved_worker_set(self):
        self.assertEqual(self.new(["", "astra", "2,4"]), "new")
        with patch.dict(os.environ, {config.SESSION_ENV: "new"}), redirect_stderr(io.StringIO()):
            for role in ("executor", "reviewer"):
                self.assertEqual(usage.pick_order(self.cfg, {}, role=role), ["opus", "spark"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
