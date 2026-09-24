"""Merged agentkit goes live on its own, even while sessions work.

`ak update` and the three-minute tick fast-forward agentkit whatever the sessions are doing;
the tick does it within one tick of origin/main moving.  A checkout that is dirty, not on main
or cannot fast-forward is left as it is, and that -- or a failed install.sh -- is said once per
origin commit, by `ak update` and in the tick's log alike.  A fetch that fails is silent, and the
next tick fetches again.

Offline throughout: origin is a throwaway bare repository, ~/agentkit is its clone under a
temporary HOME, install.sh is a fake committed there, and every other pass of the tick is a
stub.  The real ~/agentkit, its origin and the crontab are never read or written here.
"""

from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import browser, config, notify, orch, run, update, usage, watch

INSTALL = '#!/bin/sh\necho installed >>"$(dirname "$0")/../installs"\n'


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


class LiveUpdate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-live-update-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        config.ensure_dirs()
        self.cfg = config.load()   # off this checkout's defaults, before REPO is the clone's
        # the tick moves only the checkout it runs from; here that is the throwaway clone
        self.origin, self.seed, self.clone = (self.root / "origin.git", self.root / "seed",
                                              self.root / "agentkit")
        self.stack.enter_context(patch.object(config, "REPO", self.clone))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
                       check=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.seed)],
                       check=True, capture_output=True, timeout=60)
        git(self.seed, "symbolic-ref", "HEAD", "refs/heads/main")
        self.merge("first", install=INSTALL)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)],
                       check=True, capture_output=True, timeout=60)
        # sessions are working the whole time, and that holds nothing back
        self.stack.enter_context(patch.object(update, "working_sessions",
                                              return_value=["atoll", "hermes"]))

    def merge(self, text, install=None):
        """One merge to origin's main; its commit."""
        (self.seed / "notes").write_text(text + "\n")
        if install is not None:
            (self.seed / "install.sh").write_text(install)
            (self.seed / "install.sh").chmod(0o755)
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", text)
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def installs(self):
        path = self.root / "installs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def update(self):
        """One `ak update` of agentkit itself: its exit code and what it said."""
        out = io.StringIO()
        with redirect_stdout(out):
            code = update.update_self()
        return code, out.getvalue()

    def tick(self):
        """One `ak watch` with every other pass stubbed: what it said about agentkit."""
        with ExitStack() as stack:
            for where, name in ((notify, "retry_pending"), (notify, "tick_cards"),
                                (watch, "resume_after_boot"), (watch, "health"),
                                (watch, "resume_dead_loops"), (watch, "recover_runs"),
                                (watch, "resume_exhausted"), (watch, "resume_waiting_login"),
                                (watch, "resume_errored"), (watch, "resume_waiting"),
                                (watch, "sweep_preexisting"), (watch, "revive_seats"),
                                (run, "deliver_job_handbacks"), (run, "schedule_gc"),
                                (orch, "stamp"), (orch, "sweep"), (usage, "collect"),
                                (browser, "tidy"), (watch, "incoming"), (watch, "outgoing")):
                stack.enter_context(patch.object(where, name))
            stack.enter_context(patch.object(run, "run_dirs", return_value=[]))
            stack.enter_context(patch.object(config, "load", return_value=self.cfg))
            stack.enter_context(patch.object(watch, "gh_json",
                                             return_value=(None, "offline fixture")))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(watch.main([]), 0)
        return [line for line in out.getvalue().splitlines()
                if "agentkit" in line or line.startswith("  ")]

    # --- 1: live on its own, working sessions or not --------------------------

    def test_ak_update_moves_agentkit_while_sessions_work(self):
        new = self.merge("second")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(update.update_self(), 0)
        self.assertEqual(self.head(), new)
        self.assertEqual(self.installs(), 1)
        self.assertNotIn("skipped", out.getvalue())

    def test_a_tick_moves_agentkit_within_one_tick_while_sessions_work(self):
        self.assertEqual(self.tick(), [])       # nothing merged, nothing to move or say
        new = self.merge("second")
        self.assertEqual(self.tick(), [f"agentkit is live at {new[:12]}"])
        self.assertEqual(self.head(), new)
        self.assertEqual(self.installs(), 1)
        self.assertEqual(self.tick(), [])       # live already: no second pull, no reinstall
        self.assertEqual(self.installs(), 1)

    def test_a_tick_from_another_checkout_never_moves_this_one(self):
        # a worktree's tick -- a test's -- must never pull the live checkout under it
        before = self.head()
        self.merge("second")
        with patch.object(config, "REPO", REPO), \
                patch.object(update, "_git", wraps=update._git) as called:
            self.assertEqual(self.tick(), [])
        called.assert_not_called()
        self.assertEqual(self.head(), before)

    def test_an_offline_fetch_is_silent_bounded_and_retried_next_tick(self):
        before = self.head()
        new = self.merge("second")
        git(self.clone, "remote", "set-url", "origin", str(self.root / "gone.git"))
        with patch.object(update, "_git", wraps=update._git) as called:
            self.assertEqual(self.tick(), [])
        fetch = [call for call in called.call_args_list if call.args[:1] == ("fetch",)]
        self.assertEqual(len(fetch), 1)
        self.assertEqual(fetch[0].kwargs.get("timeout"), update.FETCH_CAP)
        self.assertEqual(self.head(), before)
        git(self.clone, "remote", "set-url", "origin", str(self.origin))
        self.assertEqual(self.tick(), [f"agentkit is live at {new[:12]}"])

    # --- 2: a checkout somebody is working in is left, and said once per commit -------

    def assert_left_and_said_once(self, why):
        before = self.head()
        for text in ("second", "third"):        # each new origin commit is said once
            self.merge(text)
            code, said = self.update()          # by `ak update`, with no tick to fetch for it
            self.assertNotEqual(code, 0)
            self.assertIn(why, said)
            self.assertEqual(self.update(), (code, ""))
        for text in ("fourth", "fifth"):        # ... and in the tick's log
            new = self.merge(text)
            said = self.tick()
            self.assertEqual(said[0], f"WARN agentkit did not go live at {new[:12]}:")
            self.assertTrue(any(why in line for line in said[1:]), said)
            self.assertEqual(self.tick(), [])   # the same origin commit is not said again
        self.assertEqual(self.head(), before)
        self.assertEqual(self.installs(), 0)

    def test_a_dirty_checkout_is_left_as_it_is(self):
        (self.clone / "notes").write_text("somebody's edit\n")
        self.assert_left_and_said_once(f"update: agentkit: left as it is: {self.clone} is dirty")
        self.assertEqual((self.clone / "notes").read_text(), "somebody's edit\n")

    def test_an_untracked_file_makes_the_checkout_dirty_too(self):
        git(self.clone, "config", "status.showUntrackedFiles", "no")    # whatever git is told
        (self.clone / "scratch").write_text("somebody's new file\n")
        self.assert_left_and_said_once(f"update: agentkit: left as it is: {self.clone} is dirty")
        self.assertEqual((self.clone / "scratch").read_text(), "somebody's new file\n")

    def test_a_checkout_not_on_main_is_left_as_it_is(self):
        git(self.clone, "checkout", "-q", "-b", "mine")
        self.assert_left_and_said_once(f"{self.clone} is on mine, not main")
        self.assertEqual(git(self.clone, "symbolic-ref", "--short", "HEAD"), "mine")

    def test_a_checkout_that_cannot_fast_forward_is_left_as_it_is(self):
        (self.clone / "own").write_text("a commit of its own\n")
        git(self.clone, "add", "own")
        git(self.clone, "commit", "-q", "-m", "own")
        self.assert_left_and_said_once("pull --ff-only exited")

    def test_a_failed_install_is_said_once(self):
        new = self.merge("second", install="#!/bin/sh\necho broken\nexit 3\n")
        said = self.tick()
        self.assertEqual(said[0], f"WARN agentkit did not go live at {new[:12]}:")
        self.assertIn("  broken", said)
        self.assertTrue(any("install.sh exited 3" in line for line in said), said)
        self.assertEqual(self.tick(), [])
        code, said = self.update()              # `ak update` retries it, and says it once
        self.assertEqual(code, 3)
        self.assertIn("install.sh exited 3", said)
        self.assertEqual(self.update(), (3, ""))


if __name__ == "__main__":
    unittest.main()
