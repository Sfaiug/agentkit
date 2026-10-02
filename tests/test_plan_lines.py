"""`ak plan add` writes an outcome with the check that proves it, only when that check fails on
the project's default branch; `--eye` lines are ticked on the owner's word, check lines never by
hand.

Offline: a throwaway HOME, a local origin and checkout, and the check run there.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, plan, terminal


class PlanLines(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "fix-api", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(plan.os, "killpg"))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.commit("base")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(self.origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("checkout", "-q", "-b", "work")
        (self.repo / "feature.txt").write_text("done\n")
        self.commit("the work, not on main")
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)

    def ak(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(plan.main(list(args)), 0)
        return out.getvalue()

    def plan_lines(self):
        return config.plan_path("fix-api").read_text().splitlines()

    def test_a_check_failing_on_main_is_written_and_listed(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        self.assertRegex(line, r"^- \[ \] the feature exists · check: `test -f feature.txt` · "
                               r"acme · written \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(self.plan_lines(), [line])
        with patch.object(terminal, "width", return_value=200):
            self.assertEqual(self.ak().strip(), f"1  {line}")
        self.assertTrue(plan.LINE.match(line))
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_the_checkout_has_no_dirty_or_untracked_seat_files(self):
        (self.repo / "base.txt").write_text("dirty\n")
        (self.repo / "untracked.txt").write_text("seat only\n")
        with self.assertRaisesRegex(config.Error, "already passes"):
            self.ak("add", "clean base", "--check",
                    'test "$(cat base.txt)" = base && test ! -e untracked.txt && '
                    'test ! -e feature.txt')
        self.assertEqual((self.repo / "base.txt").read_text(), "dirty\n")
        self.assertTrue((self.repo / "untracked.txt").exists())

    def test_the_default_branch_is_refreshed_and_is_not_assumed_to_be_main(self):
        self.git("push", "-q", "origin", "work:trunk")
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/trunk"],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(config.Error, "already passes"):
            self.ak("add", "already on trunk", "--check", "test -f feature.txt")

    def test_no_default_branch_or_failed_fetch_refuses_to_write(self):
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/missing"],
                       check=True, capture_output=True)
        with self.assertRaises(config.Error):
            self.ak("add", "unknown default", "--check", "false")
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/main"],
                       check=True, capture_output=True)
        self.git("remote", "set-url", "origin", str(self.root / "no-repo"))
        with self.assertRaises(config.Error):
            self.ak("add", "unreadable default", "--check", "false")
        self.assertFalse(config.plan_path("fix-api").exists())

    def test_a_check_passing_on_main_proves_nothing_and_is_refused(self):
        with self.assertRaisesRegex(config.Error, "already passes on acme's default branch"):
            plan.main(["add", "the base exists", "--check", "test -f base.txt"])
        self.assertFalse(config.plan_path("fix-api").exists())
        with self.assertRaisesRegex(config.Error, "without backticks"):
            plan.main(["add", "quoted", "--check", "test `true`"])

    def test_the_check_runs_without_the_seats_variables(self):
        names = {config.SESSION_ENV, "AK_PARENT_RUN", "IDLE_COMPACT_STATE",
                 *config.seat_env_names()}
        with patch.dict(os.environ, {name: "fix-api" for name in names}):
            for name in sorted(names):
                with self.subTest(name=name):
                    self.ak("add", "only a seat would see it", "--check", f'test -n "${name}"')
        self.assertEqual(len(self.plan_lines()), len(names))

    def test_shell_startup_cannot_restore_seat_variables(self):
        startup = self.root / "startup.sh"
        startup.write_text("AGENTKIT_SESSION=fix-api\n")
        with patch.dict(os.environ, {"BASH_ENV": str(startup)}):
            self.ak("add", "only a seat would see it", "--check", 'test -n "$AGENTKIT_SESSION"')

    def test_git_variables_cannot_redirect_the_check_to_the_seats_checkout(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.repo / ".git"),
                                     "GIT_WORK_TREE": str(self.repo)}):
            with self.assertRaisesRegex(config.Error, "already passes"):
                self.ak("add", "clean branch", "--check", "git diff --quiet main HEAD")

    def test_a_check_is_not_rewritten_or_accepted_when_it_never_finishes(self):
        with self.assertRaisesRegex(config.Error, "one shell command"):
            self.ak("add", "multiple commands", "--check", "test -f feature.txt\ntrue")
        real_popen = subprocess.Popen
        with patch.object(plan.subprocess, "Popen") as popen, \
                patch.object(plan.os, "killpg") as kill:
            proc = popen.return_value
            popen.side_effect = lambda args, **kw: (proc if args[0] == "bash"
                                                   else real_popen(args, **kw))
            proc.pid = 123456789
            proc.wait.side_effect = [subprocess.TimeoutExpired("check", 600), 0]
            with self.assertRaisesRegex(config.Error, "did not finish"):
                self.ak("add", "an unfinished check proves nothing", "--check", "false")
            kill.assert_called_once_with(proc.pid, signal.SIGKILL)
        self.assertFalse(config.plan_path("fix-api").exists())
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_sigterm_cleans_the_checkout_and_check_before_ending_the_command(self):
        previous = signal.getsignal(signal.SIGTERM)
        real_popen, real_run = subprocess.Popen, subprocess.run
        for stage in ("checkout", "check"):
            with self.subTest(stage=stage), patch.object(plan.subprocess, "Popen") as popen, \
                    patch.object(plan.subprocess, "run") as run, \
                    patch.object(plan.os, "killpg") as kill:
                proc = popen.return_value
                proc.pid = 123456789
                popen.side_effect = lambda args, **kw: (proc if args[0] == "bash"
                                                       else real_popen(args, **kw))

                def terminate():
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

                def git(args, **kw):
                    result = real_run(args, **kw)
                    if stage == "checkout" and "add" in args:
                        terminate()
                    if "remove" in args:
                        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)
                    return result

                def wait(timeout=None, **_kw):
                    if timeout is not None:
                        terminate()
                    return 0

                run.side_effect, proc.wait.side_effect = git, wait
                with self.assertRaises(SystemExit) as ended:
                    self.ak("add", "an interrupted check proves nothing", "--check", "false")
                self.assertEqual(ended.exception.code, 128 + signal.SIGTERM)
                if stage == "check":
                    kill.assert_called_once_with(proc.pid, signal.SIGKILL)
                    self.assertEqual(proc.wait.call_count, 2)
                self.assertFalse(config.plan_path("fix-api").exists())
                self.assertEqual(list(config.TMP.glob("plan-*")), [])
                self.assertEqual(len(self.git("worktree", "list", "--porcelain")
                                     .split("worktree ")) - 1, 1)
                self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_an_eye_line_is_ticked_on_the_owners_word_and_a_check_line_never_by_hand(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        eye = self.ak("add", "the hero looks calm", "--eye").strip()
        self.assertIn(" · your eye · acme · written ", eye)
        with self.assertRaisesRegex(config.Error, "only a --eye line"):
            plan.main(["tick", "1"])
        ticked = self.ak("tick", "2").strip()
        self.assertRegex(ticked, r"^- \[x\] the hero looks calm · your eye · acme · written .+"
                                 r" · done your yes \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(plan.LINE.match(ticked)["done"][:8], "your yes")
        with self.assertRaisesRegex(config.Error, "already done"):
            plan.main(["tick", "2"])
        with self.assertRaisesRegex(config.Error, "no plan line 3"):
            plan.main(["tick", "3"])

    def test_a_malformed_line_cannot_bypass_the_check_lines_tick_refusal(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        for text in (line + " · unexpected", "- [ ] old unchecked outcome"):
            with self.subTest(text=text):
                config.plan_path("fix-api").write_text(text + "\n")
                with self.assertRaisesRegex(config.Error, "only a --eye line"):
                    self.ak("tick", "1")
                self.assertEqual(self.plan_lines(), [text])

    def test_numbered_lines_wrap_to_the_terminal_width(self):
        self.ak("add", "a calm hero", "--eye")
        self.ak("add", "a clear footer", "--eye")
        with patch.object(terminal, "width", return_value=40):
            listing = self.ak().splitlines()
        self.assertTrue(all(terminal.cells(line) <= 40 for line in listing), listing)
        self.assertIn("your eye", " ".join(listing))
        self.assertEqual([line.split()[0] for line in listing if line.lstrip()[:1].isdigit()],
                         ["1", "2"])

    def test_outside_a_seat_or_without_a_project_it_is_refused(self):
        with patch.dict(os.environ, {config.SESSION_ENV: ""}), \
                self.assertRaisesRegex(config.Error, "belongs to a session"):
            plan.main([])
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        with self.assertRaisesRegex(config.Error, "filed under no project"):
            plan.main(["add", "anything", "--eye"])
        with self.assertRaisesRegex(config.Error, "usage: ak plan"):
            plan.main(["add", "anything"])


if __name__ == "__main__":
    unittest.main()
