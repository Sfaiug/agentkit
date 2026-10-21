"""A seat's stop ends the seat before its runs: the stop mark is written and its tmux session gone
by the time its runs stop (`stop.release_session`), each up to STALL_KILL_WAIT, so every menu has
the seat stopped while they go.  A stop from inside the seat outlives its pane, and says nothing into the dead terminal,
where a print would end it halfway.  Offline: fake HOME, fake tmux, no real seat.
"""

import errno
import io
import os
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import browser, config, notify, orch, stop, watch

SEAT = "acme-ui"


class Pane(io.TextIOBase):
    """A seat's terminal: it takes lines until its session is killed."""
    dead = False

    def write(self, text):
        if self.dead:
            raise OSError(errno.EIO, "Input/output error")
        return len(text)


class StopEndsSeatFirst(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop(config.SESSION_ENV, None)      # the owner, who may stop any seat
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        seat = {"name": SEAT, "path": str(self.root), "created": 100, "attached": False,
                "exited": False, "legacy": False}
        self.stack.enter_context(patch.object(orch, "find", side_effect=lambda name:
                                              seat if name == SEAT else None))
        self.stack.enter_context(patch.object(orch, "records", side_effect=lambda **_kw:
                                              config.session_records()))
        self.stack.enter_context(patch.object(browser, "close_owned"))
        self.card = self.stack.enter_context(patch.object(notify, "forget_card"))
        self.pane, self.killed = Pane(), []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        if args[0] == "kill-session":
            self.killed.append(args[-1])
            self.pane.dead = True
        return 0, ""

    def test_the_seat_is_stopped_before_its_runs_are(self):
        seen = []
        with patch.object(stop, "stop_owned_runs", side_effect=lambda name: seen.append(
                (name, watch.seat_read(SEAT).get("closed_by_owner"), list(self.killed)))):
            self.assertEqual(orch.cmd_stop([SEAT]), 0)
        self.assertEqual(seen, [(SEAT, True, [f"={SEAT}"])])
        self.card.assert_called_with(SEAT)

    def test_a_stop_from_inside_the_seat_goes_on_past_its_dead_pane(self):
        runs = []

        def stop_runs(name):
            runs.append(name)
            print(f"stopped a run of {name}")         # what a run's stop says

        with patch.dict(os.environ, {config.SESSION_ENV: SEAT}), \
                patch.object(stop, "stop_owned_runs", side_effect=stop_runs), \
                patch.object(sys, "stdout", self.pane), patch.object(sys, "stderr", self.pane):
            self.assertEqual(orch.cmd_stop([SEAT]), 0)
        self.assertEqual((runs, self.killed), ([SEAT], [f"={SEAT}"]))
        self.card.assert_called_with(SEAT)


if __name__ == "__main__":
    unittest.main()
