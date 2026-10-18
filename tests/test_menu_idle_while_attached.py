"""A menu reads nothing while its owner is in a seat it opened, and back, draws at once and reads
behind the draw.

Menus left open on seats kept reading every seat and every run within `STIR` of any run moving,
all the while they waited in `orch.attach`, for a screen nobody saw until the owner came back.
`menu.loop` in-process opens a seat by its number, as a new one (`n`) and from the past screen
(`p`), into a fake attach that moves a run every watcher period; the listing, the runs and the
draw are fakes counting what is read, and a look (`Live.look`) is taken as started and never
runs.  A seat still owed its first look when the owner leaves gets it from the pass that ends,
on the runs read with it and nothing read again, and a read going as the owner leaves holds up
no seat and lands nowhere.  Offline, in `Sandbox`'s temporary HOME: no tmux, no seat, no probe.
"""

from contextlib import redirect_stdout
import io
import sys
import threading
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox, menu_input
from agentkit import config, menu, orch

SEAT = "fix-api"
STIR = 0.02       # the watcher's period, short, so the attach outlasts several
PERIODS = 5


def moved():
    """Several watcher periods, a run moving in each: news to a menu that reads."""
    for _ in range(PERIODS):
        time.sleep(2 * STIR)
        config.runs_moved_path().touch()
    time.sleep(2 * STIR)


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
            moved()
            attached.append((len(listings) - before[0], len(runs) - before[1]))
            return 0

        def wait(*_args, **_kw):
            if not draws[1:]:
                return key
            deadline = time.monotonic() + 30
            while len(runs) < 2:                        # the read behind the draw back
                self.assertLess(time.monotonic(), deadline, "nothing read back from the seat")
                time.sleep(STIR / 4)
            return ""

        with patch.object(menu, "STIR", STIR), patch.object(sys, "stdin", io.StringIO()), \
                patch.object(orch, "listing", side_effect=listing), \
                patch.object(menu, "run_records", side_effect=run_records), \
                patch.object(orch, "file_projectless"), \
                patch.object(menu, "v5o_groups", return_value=([], [], 0, {})), \
                patch.object(menu.Live, "look", return_value=True), \
                patch.object(menu, "draw", side_effect=draw), \
                patch.object(menu, "moving", side_effect=wait), \
                patch.object(menu, "new_session", side_effect=opens), \
                patch.object(menu, "show_past", side_effect=opens), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "update_first"), \
                patch.object(orch, "attach", side_effect=attach), \
                menu_input(), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg), 0)
        return draws, attached

    def test_no_read_while_in_a_seat_and_none_before_the_draw_back(self):
        for key in ("1", "n", "p"):
            with self.subTest(key=key):
                draws, attached = self.menu(key)
                self.assertEqual(attached, [(0, 0)], "read while the owner was in the seat")
                self.assertEqual(draws, [(1, 1), (1, 1)], "the draw back waited on a read")

    def test_a_seat_owed_its_first_look_gets_it_and_then_nothing_is_read(self):
        """Listed while a pass was going, as the owner leaves for a seat: the pass that ends
        starts its own from the listing and the runs in hand, and nothing reads either."""
        found, listings, runs, looked = [{"name": "acme-docs"}], [], [], []
        release = threading.Event()
        self.addCleanup(release.set)

        def listing(**_kw):
            listings.append(len(found))
            return list(found)

        def run_records():
            runs.append(len(found))
            return [(None, {"read": len(runs)})]     # which read a pass looks from

        def groups(_cfg, seats, records=None, *_args, look=True, **_kw):
            if look:                            # without `records` the real one reads them
                looked.append(([seat["name"] for seat in seats], records))
                if len(looked) == 1:
                    release.wait(30)            # the first pass is going while the seat comes
            return [], [], 0, {}

        def until(what, done):
            deadline = time.monotonic() + 30
            while not done():
                self.assertLess(time.monotonic(), deadline, what)
                time.sleep(STIR / 4)

        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        with patch.object(menu, "STIR", STIR), \
                patch.object(orch, "listing", side_effect=listing), \
                patch.object(menu, "run_records", side_effect=run_records), \
                patch.object(orch, "file_projectless"), \
                patch.object(menu, "v5o_groups", side_effect=groups):
            live.watch([[], None])
            found.append({"name": SEAT})
            config.runs_moved_path().touch()
            until("the read finding the seat", lambda: len(listings) == 2)
            live.away()
            release.set()
            until("the seat's own pass", lambda: len(looked) == 2)
            live.looker.join(30)
            moved()
            self.assertEqual(looked, [(["acme-docs"], [(None, {"read": 1})]),
                                      (["acme-docs", SEAT], [(None, {"read": 2})])])
            self.assertEqual((listings, runs), ([1, 2], [1, 2]),
                             "read while the owner was in the seat")
            live.watch(live.last)
            self.assertEqual((listings, runs), ([1, 2, 2], [1, 2, 2]))
            live.close()

    def test_a_read_going_as_the_owner_leaves_holds_up_no_seat_and_lands_nowhere(self):
        """The seat opens at once, the read is let go when it ends, and the one back is read
        behind the draw."""
        listings, generation = [], [1]
        blocked, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def listing(**_kw):
            listings.append(generation[0])
            return [{"name": SEAT}]

        def groups(*_args, **_kw):
            if threading.current_thread() is live.watcher and not blocked.is_set():
                blocked.set()
                release.wait(30)            # the watcher's read, going as the owner leaves
                return "going"
            return generation[0]

        def until(what, done):
            deadline = time.monotonic() + 30
            while not done():
                self.assertLess(time.monotonic(), deadline, what)
                time.sleep(STIR / 4)

        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        with patch.object(menu, "STIR", STIR), \
                patch.object(orch, "listing", side_effect=listing), \
                patch.object(menu, "run_records", return_value=[]), \
                patch.object(orch, "file_projectless"), \
                patch.object(menu, "v5o_groups", side_effect=groups), \
                patch.object(menu.Live, "look", return_value=True):
            live.watch([[], None])
            live.ask()
            self.assertTrue(blocked.wait(30), "the watcher never read")
            leaving = threading.Thread(target=live.away)
            leaving.start()
            leaving.join(10 * STIR)
            self.assertFalse(leaving.is_alive(), "the seat waited on a read going")
            release.set()
            self.assertTrue(live.reading.acquire(timeout=30), "the read going never ended")
            live.reading.release()
            moved()
            self.assertEqual((listings, live.last[1]), ([1, 1], 1),
                             "the read going landed, or one was made in the seat")
            generation[0] = 2               # what the owner comes back to
            live.back()
            until("the read back", lambda: live.last[1] == 2)
            self.assertEqual(listings, [1, 1, 2])
            live.close()


if __name__ == "__main__":
    unittest.main()
