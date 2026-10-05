"""A repository's `cleanup:` line runs once in the checkout before any removal takes it."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config, host, run, watch, worktrees  # noqa: E402


class RepoCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-repo-cleanup-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            config.SESSION_ENV: "", config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Cleanup test")
        self.git("config", "user.email", "cleanup@localhost")
        (self.repo / "tracked").write_text("base\n")
        self.git("add", "tracked")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def make_run(self, name, agents):
        (self.repo / "AGENTS.md").write_text(agents)
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", name)
        wt = config.WT / name
        branch = f"ak/{name}"
        self.git("worktree", "add", str(wt), "-b", branch)
        run_dir = config.RUNS / name
        run_dir.mkdir()
        state = {"run_id": name, "repo": str(self.repo), "worktree": str(wt),
                 "branch": branch, "state": "stopped", "verdict": "STOPPED",
                 "pid": os.getpid()}
        (run_dir / "run.json").write_text(json.dumps(state))
        (run_dir / "log.txt").write_text("")
        return wt, run_dir, state

    def cleanup_lines(self, run_dir):
        return [line for line in (run_dir / "log.txt").read_text().splitlines()
                if "repo cleanup:" in line]

    def test_declared_cleanup_runs_once_before_removal(self):
        counter = self.root / "counter"
        wt, run_dir, state = self.make_run(
            "cleanup-once",
            f"---\ncleanup: pwd && echo cleaned >> {counter}\n---\n# acme\n")
        worktrees.run_repo_cleanup(wt, run_dir)
        worktrees.run_repo_cleanup(wt, run_dir)
        self.assertTrue(worktrees.stop_checkout(state, lambda message: None))
        self.assertFalse(wt.exists())
        self.assertEqual(counter.read_text().splitlines(), ["cleaned"])
        self.assertIn(str(wt), (run_dir / "cleanup.log").read_text())
        [line] = self.cleanup_lines(run_dir)
        self.assertIn("exited 0", line)

    def test_failing_cleanup_still_removes_and_keeps_result(self):
        for name, cmd in (("cleanup-fails", "exit 3"),
                          ("cleanup-missing", "ak-missing-cleanup-tool-99 --drop")):
            with self.subTest(cmd=cmd):
                wt, run_dir, _ = self.make_run(
                    name, f"---\ncleanup: {cmd}\n---\n# acme\n")
                before = (run_dir / "run.json").read_bytes()
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(run.cmd_clean([name]), 0)
                self.assertFalse(wt.exists())
                self.assertEqual((run_dir / "run.json").read_bytes(), before)
                self.assertTrue((run_dir / "cleanup.log").exists())
                [line] = self.cleanup_lines(run_dir)
                self.assertNotIn("exited 0", line)

    def test_without_cleanup_nothing_runs(self):
        wt, run_dir, state = self.make_run(
            "no-cleanup", "---\nusers: none\n---\n# acme\n")
        self.assertTrue(worktrees.stop_checkout(state, lambda message: None))
        self.assertFalse(wt.exists())
        self.assertFalse((run_dir / "cleanup.log").exists())
        self.assertEqual(self.cleanup_lines(run_dir), [])
        self.assertEqual((run_dir / "log.txt").read_text(), "")

    def test_timed_out_cleanup_still_removes(self):
        wt, run_dir, state = self.make_run(
            "cleanup-slow", "---\ncleanup: sleep 30\n---\n# acme\n")
        with patch.object(worktrees, "CLEANUP_LIMIT", 1):
            self.assertTrue(worktrees.stop_checkout(state, lambda message: None))
        self.assertFalse(wt.exists())
        [line] = self.cleanup_lines(run_dir)
        self.assertIn("timed out", line)

    @unittest.skipUnless(sys.platform == "linux", "orphan reaping needs Linux's subreaper")
    def test_timed_out_cleanup_kills_children_before_removal(self):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        self.addCleanup(libc.prctl, 36, previous.value, 0, 0, 0)
        child_file = self.root / "child.pid"
        start = f"sleep 30 & echo $! > {shlex.quote(str(child_file))}; wait"
        # a child of the line's own shell, and one under `timeout`, which makes its own
        # process group
        for name, line in (("cleanup-child", f"trap '' TERM; {start}"),
                           ("cleanup-wrapped", f"timeout 30 bash -c {shlex.quote(start)}; :")):
            with self.subTest(line=line):
                child_file.unlink(missing_ok=True)
                wt, run_dir, state = self.make_run(name, f"---\ncleanup: {line}\n---\n# acme\n")
                child = None
                try:
                    # the first line's child ignores TERM as its shell does: only KILL ends it
                    with patch.object(worktrees, "CLEANUP_LIMIT", 1), \
                            patch.object(watch, "STALL_KILL_WAIT", 1):
                        worktrees.run_repo_cleanup(wt, run_dir)
                    child = int(child_file.read_text())
                    deadline = time.monotonic() + .5
                    while not self.gone(child) and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(self.gone(child),
                                    "cleanup timed out but its child was left running")
                    self.assertTrue(worktrees.stop_checkout(state, lambda message: None))
                    self.assertFalse(wt.exists())
                    [line] = self.cleanup_lines(run_dir)
                    self.assertIn("timed out", line)
                finally:
                    # Adopt and reap only this fixture's orphan, even when the old code leaks it.
                    if child is None and child_file.exists():
                        child = int(child_file.read_text())
                    if child is not None and not self.gone(child):
                        os.kill(child, signal.SIGKILL)
                        while not self.gone(child):
                            time.sleep(.02)

    def test_an_interrupted_cleanup_takes_its_children_with_it(self):
        # `ak run stop` or `ak run clean` interrupted while the line runs: the line's tree
        # goes before the interrupt goes on up, as subprocess.run's kill on any exception did
        child_file = self.root / "child.pid"
        wt, run_dir, _state = self.make_run(
            "cleanup-interrupted", "---\ncleanup: "
            f"sleep 30 & echo $! > {shlex.quote(str(child_file))}; wait\n---\n# acme\n")

        def interrupt():
            deadline = time.monotonic() + 10
            while not child_file.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=interrupt, daemon=True).start()
        child = None
        try:
            with self.assertRaises(KeyboardInterrupt):
                worktrees.run_repo_cleanup(wt, run_dir)
            child = int(child_file.read_text())
            deadline = time.monotonic() + 2
            while not self.gone(child) and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(self.gone(child), "an interrupted cleanup left its child running")
        finally:
            if child is None and child_file.exists():
                child = int(child_file.read_text())
            if child is not None and not self.gone(child):
                os.kill(child, signal.SIGKILL)

    @staticmethod
    def gone(pid):
        """Ended: reaped here as this test's orphan, or by its own parent, or a zombie."""
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return True
        except ChildProcessError:
            pass
        stat = host.proc_stat(pid)
        return stat is None or stat.exited


if __name__ == "__main__":
    unittest.main(verbosity=2)
