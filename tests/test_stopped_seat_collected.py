"""The sweep removes a stopped seat, its record and files, a week after it was stopped.

The week runs from the stop, not from the seat's last sighting in tmux: a seat long gone from
tmux that the owner stops today keeps its row and its number the whole week, and `orch.sweep`
takes it the day the week is out, the way a second stop does -- the record, every state file
but the locks, the stop mark alone written back -- so the name is free again.  The mark is in
place before the tmux session is killed, so a hand-back meeting the session gone reads it.

Offline: a throwaway HOME, tmux faked, the clock injected, no runs and no real seat.
"""

from contextlib import redirect_stdout
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.sandbox import Sandbox
from agentkit import browser, config, orch, statusbar, watch

SEAT = "acme"
NOW = 2_000_000                     # the stop; the seat was last in tmux eight days before
KINDS = ("plan", "hook", "notify")


class StoppedSeatCollected(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop(config.SESSION_ENV, None)      # the owner, who may stop any seat
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": ""}))
        self.stack.enter_context(patch.object(      # tmux holds nothing by the name
            orch, "tmux_out", return_value=(1, f"can't find session: {SEAT}")))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(browser, "close_tab"))
        self.clock = self.stack.enter_context(patch.object(orch.time, "time", return_value=NOW))
        config.save_session(self.cfg, SEAT, self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"],
                            {"cwd": str(self.root), "created": 100, "seen": NOW - 8 * 86400,
                             "conversation": "conv-1", "id_source": "launcher"})
        for kind in KINDS:
            config.seat_file(kind, SEAT).write_text("{}\n")
        self.lock = config.notify_path(SEAT).with_suffix(".lock")
        self.lock.write_text("")
        self.swept = []

    def stop(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop([SEAT]), 0)

    def sweep(self, at):
        self.clock.return_value = at
        orch.sweep(self.swept.append)

    def test_the_week_runs_from_the_stop_and_the_sweep_takes_the_seat_when_it_is_out(self):
        self.stop()
        self.assertEqual(watch.seat_stopped_at(SEAT), NOW)
        watch.seat_write(SEAT, wait={"on": "https://github.com/acme/acme/pull/7", "kind": "pr"})
        # stopped today: the sweep that runs next leaves it, and so does the one the day before
        # the week is out, its row and its number with it
        for at in (NOW, NOW + config.SESSION_STALE - 86400):
            self.sweep(at)
            self.assertEqual(self.swept, [])
            self.assertEqual([(row["name"], row["closed"]) for row in orch.listing(reconcile=False)],
                             [(SEAT, NOW)])
            self.assertIn(SEAT, orch.taken_names())
        # the week is out: the record and the files go, the locks stay, the stop mark alone
        # comes back for a hand-back to read, and the name is free
        self.sweep(NOW + config.SESSION_STALE)
        self.assertEqual(self.swept, [f"forgot the session {SEAT}, gone for 7d"])
        self.assertFalse(config.session_path(SEAT).exists())
        for kind in KINDS:
            self.assertFalse(config.seat_file(kind, SEAT).exists(), kind)
        self.assertTrue(self.lock.exists())
        self.assertEqual(watch.seat_read(SEAT), {"session": SEAT, "stopped_at": NOW,
                                                 "closed_by_owner": True})
        self.assertEqual(orch.listing(reconcile=False), [])
        self.assertNotIn(SEAT, orch.taken_names())

    def test_the_stop_mark_is_in_place_before_the_session_is_killed(self):
        # a hand-back that meets the session gone finds the seat closed, never a ghost to reopen
        marked = []
        session = {"name": SEAT, "path": str(self.root), "created": 100,
                   "attached": False, "exited": False, "legacy": False}

        def tmux(*args, **_kw):
            if args[0] == "kill-session":
                marked.append(watch.seat_closed_by_owner(SEAT))
            return 0, ""

        with patch.object(orch, "sessions", return_value=[session]), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(statusbar, "retell"):
            self.stop()
        self.assertEqual(marked, [True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
