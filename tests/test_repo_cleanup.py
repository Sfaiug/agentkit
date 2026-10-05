"""A repository's `cleanup:` line runs once in the checkout before any removal takes it."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config, run, worktrees  # noqa: E402


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

    def marked(self):
        """A `sleep` only this test starts: its argument is the marker its processes carry."""
        marker = f"{30 + int.from_bytes(os.urandom(3), 'big') / 1e7:.7f}"
        self.addCleanup(self.end_marked, marker)
        return marker

    @staticmethod
    def running(marker):
        """The processes still running whose command line names the marker."""
        found = []
        for entry in os.listdir("/proc"):
            try:
                if entry.isdigit() and marker.encode() in Path(
                        f"/proc/{entry}/cmdline").read_bytes():
                    found.append(int(entry))
            except OSError:
                pass
        return found

    def end_marked(self, marker):
        for pid in self.running(marker):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def assert_none_left(self, marker):
        deadline = time.monotonic() + 2
        while self.running(marker) and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.running(marker), [], "cleanup work outlived its line")

    @unittest.skipUnless(sys.platform == "linux", "reads /proc")
    def test_a_timed_out_cleanup_leaves_nothing_of_its_line_running(self):
        # a child of the line's shell, one that ignores TERM, and one its TERM handler would
        # start: all in the line's own process group, which goes whole on a KILL
        for name, line in (
                ("cleanup-child", "sleep {m} & wait"),
                ("cleanup-deaf", "trap '' TERM; sleep {m} & wait"),
                ("cleanup-handler", "trap 'sleep {m} & exit' TERM; sleep {m} & wait")):
            with self.subTest(line=line):
                marker = self.marked()
                wt, run_dir, state = self.make_run(
                    name, f"---\ncleanup: {line.format(m=marker)}\n---\n# acme\n")
                with patch.object(worktrees, "CLEANUP_LIMIT", 1):
                    worktrees.run_repo_cleanup(wt, run_dir)
                self.assert_none_left(marker)
                self.assertTrue(worktrees.stop_checkout(state, lambda message: None))
                self.assertFalse(wt.exists())
                [line] = self.cleanup_lines(run_dir)
                self.assertIn("timed out", line)

    @unittest.skipUnless(sys.platform == "linux", "reads /proc")
    def test_a_ctrl_c_mid_cleanup_leaves_nothing_of_its_line_running(self):
        # `ak run stop` or `ak run clean` stopped with Ctrl+C while the line runs: the
        # terminal signals its whole foreground group, here a caller in a group of its own
        marker = self.marked()
        wt, run_dir, _state = self.make_run(
            "cleanup-interrupted", f"---\ncleanup: sleep {marker} & wait\n---\n# acme\n")
        caller = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
             "from agentkit import worktrees\n"
             f"worktrees.run_repo_cleanup({str(wt)!r}, {str(run_dir)!r})\n"],
            start_new_session=True, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while len(self.running(marker)) < 2 and time.monotonic() < deadline:
            time.sleep(.02)
        os.killpg(caller.pid, signal.SIGINT)
        self.assertNotEqual(caller.wait(timeout=30), 0)    # the interrupt went on up
        self.assert_none_left(marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
