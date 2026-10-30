"""A run's process with no room to start a thread or process ends for the tick, never in error.

`tests/test_key_a_run_survives_the_process_limit.py` starves a whole run; this pins what it
cannot reach: which failures are a full task table, what the record reads once the process
ends, and a resume that finds no room in its own start, its box's refusal included.
"""

from contextlib import redirect_stdout
import errno
import io
import os
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, run
from agentkit import record as run_record

FULL = BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")   # as a fork raises it
REFUSED = config.Error("worker box cannot start: bwrap: Creating new namespace failed")


class StarvedRun(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0"}))
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.run_dir = config.RUNS / "fix-api"
        self.run_dir.mkdir()

    def saved(self, state):
        run_record.save_state(self.run_dir, {"run_id": "fix-api", "state": state})

    def ended(self, call, lone=True):
        """The exit code `call` ended this process with, or None where it returned."""
        with patch.object(run, "lone_run", return_value=lone), \
                patch.object(run.os, "_exit", side_effect=SystemExit) as ended, \
                redirect_stdout(io.StringIO()):
            try:
                call()
            except SystemExit:
                pass
        return ended.call_args.args[0] if ended.called else None

    def test_only_a_full_task_table_is_starved(self):
        self.assertTrue(run.starved(FULL))
        self.assertTrue(run.starved(RuntimeError("can't start new thread")))
        for other in (RuntimeError("dictionary changed size during iteration"),
                      OSError(errno.ENOMEM, "Cannot allocate memory"), config.Error("no room")):
            self.assertFalse(run.starved(other), other)

    def test_an_ending_the_record_saved_reads_running_and_a_stop_stays(self):
        for before, after in (("pass", "running"), ("fail", "running"), ("running", "running"),
                              ("queued", "queued"), ("stopped", "stopped")):
            self.saved(before)
            code = self.ended(lambda: run.end_starved(FULL, print, self.run_dir))
            self.assertEqual((code, run_record.read_state(self.run_dir)["state"]),
                             (os.EX_TEMPFAIL, after))

    def test_a_process_shared_with_others_ends_as_before(self):
        self.saved("pass")
        self.assertIsNone(self.ended(lambda: run.end_starved(FULL, print, self.run_dir),
                                     lone=False))
        self.assertEqual(run_record.read_state(self.run_dir)["state"], "pass")

    def test_a_resume_with_no_room_in_its_own_start_leaves_what_its_launch_wrote(self):
        launch = {"run_id": "fix-api", "state": "queued", "slot_waiting": True,
                  "resume_from": "running", "pid": os.getpid()}
        for failure in (FULL, RuntimeError("can't start new thread"), REFUSED):
            run_record.save_state(self.run_dir, launch)
            with self.subTest(failure=failure), \
                    patch.dict(os.environ, {config.RUN_DIR_ENV: str(self.run_dir)}), \
                    patch.object(run.box, "check", side_effect=failure):
                self.assertEqual(self.ended(lambda: run.cmd_resume(["fix-api"])), os.EX_TEMPFAIL)
                self.assertEqual(run_record.read_state(self.run_dir), launch)
        self.assertIn("worker box cannot start", (self.run_dir / "log.txt").read_text())


if __name__ == "__main__":
    unittest.main()
