"""An rsync that exits after a timed wait, while `standby._rsync` reads `host.work_ticks` or
before `Popen.terminate` sends SIGTERM, keeps its own exit code instead of failing as idle.
Where `host.work_ticks` returns None (no /proc), the transfer is never ended, and a process
that does not exit even after SIGKILL is waited for `worker.KILL_GRACE` seconds and left, not
waited on without end.
"""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import host, move, standby, worker


class StandbyRsyncWatch(unittest.TestCase):
    def _exit_on(self, code, when):
        """Run `standby._rsync` on a child that exits `code` when `when` ('ticks' or 'terminate')
        fires on the second sample, before SIGTERM is sent."""
        reader, writer = os.pipe()
        proc = None
        released = False

        def release():
            nonlocal released
            if not released:
                os.write(writer, b"x")
                released = True

        real_popen = subprocess.Popen

        def popen(cmd, **kwargs):
            nonlocal proc
            words = [sys.executable, "-c",
                     "import os, sys; os.read(int(sys.argv[1]), 1); sys.exit(int(sys.argv[2]))",
                     str(reader), str(code)]
            proc = real_popen(words, pass_fds=(reader,), **kwargs)
            if when == "terminate":
                real_terminate = proc.terminate

                def terminate():
                    release()
                    os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
                    return real_terminate()

                proc.terminate = terminate
            return proc

        samples = 0

        def ticks(pid):
            nonlocal samples
            samples += 1
            if when == "ticks" and samples == 2:
                release()
                os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
            return 10

        try:
            with (patch.object(standby, "TIMEOUT", 1),
                  patch.object(subprocess, "Popen", popen),
                  patch.object(host, "work_ticks", ticks)):
                return standby._rsync(["rsync"], None)
        finally:
            if proc is not None:
                release()
                proc.wait(timeout=5)
            os.close(reader)
            os.close(writer)

    def test_exit_during_last_work_ticks_keeps_exit_code(self):
        for code, expected in ((0, None), (move.VANISHED, None), (23, "rsync exited 23")):
            with self.subTest(code=code):
                self.assertEqual(self._exit_on(code, "ticks"), expected)

    def test_exit_before_terminate_keeps_exit_code(self):
        for code, expected in ((0, None), (move.VANISHED, None), (23, "rsync exited 23")):
            with self.subTest(code=code):
                self.assertEqual(self._exit_on(code, "terminate"), expected)

    def test_none_work_ticks_never_ends_transfer(self):
        class FakeProc:
            pid = 1
            returncode = None
            waits = 0

            def wait(self, timeout=None):
                self.waits += 1
                if self.waits <= 3:
                    raise subprocess.TimeoutExpired(["rsync"], timeout)
                self.returncode = 0
                return 0

            def poll(self):
                return self.returncode

            def terminate(self):
                raise AssertionError("terminate must not be called when work_ticks is None")

        with (patch.object(standby, "TIMEOUT", 1),
              patch.object(subprocess, "Popen", return_value=FakeProc()),
              patch.object(host, "work_ticks", return_value=None)):
            self.assertIsNone(standby._rsync(["rsync"], None))

    def test_unreapable_process_does_not_wait_without_end(self):
        events = []

        class StuckProc:
            pid = 1
            returncode = None

            def wait(self, timeout=None):
                events.append(("wait", timeout))
                raise subprocess.TimeoutExpired(["rsync"], timeout)

            def poll(self):
                return None

            def terminate(self):
                events.append(("terminate",))

            def kill(self):
                events.append(("kill",))

        with (patch.object(standby, "TIMEOUT", 1),
              patch.object(worker, "KILL_GRACE", 5),
              patch.object(subprocess, "Popen", return_value=StuckProc()),
              patch.object(host, "work_ticks", return_value=10)):
            why = standby._rsync(["rsync"], None)
        self.assertEqual(why, "rsync did nothing for 1 seconds")
        self.assertEqual(events, [
            ("wait", 1), ("wait", 1), ("terminate",), ("wait", 5), ("kill",), ("wait", 5),
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
