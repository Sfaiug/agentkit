"""A failed write to state/tmux.conf preserves the previous config and atomic replace invariants."""

import os
import stat
import sys
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home

sys.path.insert(0, str(REPO))
from agentkit import config, gc, orch, retention, watch

SCRIPT = """
import errno, resource, signal
from agentkit import config, orch

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (1, 1))
try:
    orch.tmux_conf()
except config.Error as exc:
    if getattr(exc.__cause__, "errno", None) == errno.EFBIG:
        raise SystemExit(32)
    raise
"""


class TmuxConfAtomicWriteTest(unittest.TestCase):
    def test_failed_write_preserves_previous_config_and_cleans_temp_file(self):
        old = "set -g remain-on-exit on\n"
        home = Home()
        self.addCleanup(home.close)
        path = home.write(".agentkit/state/tmux.conf", old)
        result = home.run(sys.executable, "-c", SCRIPT, cwd=REPO)
        self.assertEqual(result.code, 32, result)
        self.assertEqual(path.read_text(), old)
        self.assertEqual([item.name for item in path.parent.iterdir()], ["tmux.conf"])

    def test_interrupted_seat_file_temp_remains_collectible_by_gc(self):
        with tempfile.TemporaryDirectory() as state:
            with patch.object(config, "STATE", Path(state)), patch.object(
                    config, "RUNS", Path(state) / "runs"):
                for kind in ("input", "held", "change", "handover"):
                    pid = os.fork()
                    if pid == 0:
                        with patch.object(os, "replace", side_effect=lambda *args: os._exit(23)):
                            orch.replace_file(config.seat_file(kind, "acme"), b"seat state")
                        os._exit(24)
                    self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 23)
                pending = set(Path(state).iterdir())
                self.assertEqual(len(pending), 4)
                with patch.object(orch, "sessions", return_value=[]):
                    items = gc.stale_seat_files(time.time() + 2 * retention.EPHEMERAL_AGE)
                left = pending - {Path(item["path"]) for item in items}
                self.assertEqual(left, set())

    def test_replace_file_handles_long_filenames_near_name_max(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            runs = root / "runs"
            runs.mkdir()
            limit = os.pathconf(runs, "PC_NAME_MAX")
            for extra in (13, 4):
                repo = root / ("a" * (limit - extra - len(".live-.runs")))
                repo.mkdir(exist_ok=True)
                run = runs / "built-acme"
                run.mkdir(exist_ok=True)
                with patch.object(config, "RUNS", runs), patch.object(
                        watch.run_record, "read_state", return_value={"repo": str(repo)}):
                    with patch.object(watch.orch, "start_in_slice",
                                      side_effect=AssertionError("a follower already exists")):
                        with os.fdopen(watch.live_lock(repo, "follower")):
                            watch.start_live_probe(run)
                    path = watch.live_path(repo, "runs")
                    self.assertTrue(path.exists())
                    self.assertEqual(path.read_text(), "built-acme")

    def test_rewriting_tmux_conf_under_restrictive_umask_keeps_read_permission(self):
        with tempfile.TemporaryDirectory() as state:
            path = Path(state) / "tmux.conf"
            path.write_text("set -g remain-on-exit on\n")
            path.chmod(0o600)
            mask = os.umask(0o400)
            try:
                with patch.object(config, "STATE", Path(state)), patch.object(
                        config, "ensure_dirs"), patch.object(
                            orch, "server_conf", return_value="set -g remain-on-exit on\n"):
                    orch.tmux_conf()
            finally:
                os.umask(mask)
            self.assertTrue(path.read_text().startswith("# written by"))
            self.assertTrue(path.stat().st_mode & stat.S_IRUSR)


if __name__ == "__main__":
    unittest.main()
