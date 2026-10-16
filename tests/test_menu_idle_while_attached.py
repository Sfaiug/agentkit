"""A menu reads nothing while its owner is in a seat it opened, and reads once, at once, back.

Menus left open on seats kept reading every seat and every run within `STIR` of any run moving,
all the while they waited in `orch.attach`, for a screen nobody saw until the owner came back.
`menu.loop` in-process opens a seat by its number, as a new one (`n`) and from the past screen
(`p`), into a fake attach that moves a run every watcher period; the listing, the runs and the
draw are fakes counting what is read.  No look is started (`Live.look`): it reads on a thread of
its own.  Offline, in `Sandbox`'s temporary HOME: no tmux, no seat, no probe.
"""

from contextlib import redirect_stdout
import io
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox, menu_input
from agentkit import config, menu, orch

SEAT = "fix-api"
STIR = 0.02       # the watcher's period, short, so the attach outlasts several
PERIODS = 5


class MenuIdleWhileAttached(Sandbox):
    def menu(self, key):
        """`menu.loop` pressing `key`, then leaving: (listings, run reads) as each draw found
        them, and those made while the owner was in the seat."""
        listings, runs, draws, attached = [], [], [], []

        def listing(**_kw):
            listings.append(SEAT)
            return [{"name": SEAT, "closed": True}]     # stopped too, so `p` is a key

        def run_records():
            runs.append(SEAT)
            return []

        def draw(*_args, **_kw):
            draws.append((len(listings), len(runs)))
            return 0, 1

        def opens(cfg, *_args, **_kw):                  # what `n` and `p` do once one is chosen
            menu.open_session(cfg, {"name": SEAT}, False)

        def attach(_name, **_kw):
            before = len(listings), len(runs)
            for _ in range(PERIODS):
                time.sleep(2 * STIR)                    # the watcher round once more at least,
                config.runs_moved_path().touch()        # and a run moves: news to a reader
            time.sleep(2 * STIR)
            attached.append((len(listings) - before[0], len(runs) - before[1]))
            return 0

        keys = iter([key, ""])
        with patch.object(menu, "STIR", STIR), patch.object(sys, "stdin", io.StringIO()), \
                patch.object(orch, "listing", side_effect=listing), \
                patch.object(menu, "run_records", side_effect=run_records), \
                patch.object(orch, "file_projectless"), \
                patch.object(menu, "v5o_groups", return_value=([], [], 0, {})), \
                patch.object(menu.Live, "look", return_value=False), \
                patch.object(menu, "draw", side_effect=draw), \
                patch.object(menu, "moving", side_effect=lambda *_a, **_kw: next(keys)), \
                patch.object(menu, "new_session", side_effect=opens), \
                patch.object(menu, "show_past", side_effect=opens), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "update_first"), \
                patch.object(orch, "attach", side_effect=attach), \
                menu_input(), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg), 0)
        return draws, attached

    def test_no_read_while_in_a_seat_and_exactly_one_before_the_draw_back(self):
        for key in ("1", "n", "p"):
            with self.subTest(key=key):
                draws, attached = self.menu(key)
                self.assertEqual(attached, [(0, 0)], "read while the owner was in the seat")
                self.assertEqual(draws, [(1, 1), (2, 2)],
                                 "not one read between the seat and the draw back")


if __name__ == "__main__":
    unittest.main()
