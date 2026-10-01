"""`ak` draws its main screen at once and Esc leaves at once, however slow what is behind it.

`menu.main` in-process on a keyboard it has taken, maintenance and every seat's look each a fake
taking two seconds: the first frame is out within 100 ms of starting and maintenance's notice
lands after it, and Esc leaves within 100 ms with a 600 ms read of the seats still going.
Offline, in a throwaway HOME: the update, the Mac bridge and the boot resume do nothing, the
probe is never started, and every thread the menu leaves behind is waited for before the fakes
go.
"""

from contextlib import redirect_stdout
import io
import os
import select
import threading
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox, menu_input
from agentkit import config, macbridge, menu, orch, terminal, watch

SLOW = 2.0        # what maintenance and each seat's look take
READ = 0.6        # what a read of the seats takes once the first is drawn
FRAME = 0.1       # what the first frame and Esc may take
REAPED = "agentkit: reaped a loop whose process was gone"
Key = terminal.Key


class Keyboard:
    """A terminal the menu has taken, so keys are `terminal.Key`s and the screen is written over."""

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class OpensAtOnce(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.seats = [{"name": name, "repo": str(repo), "path": str(repo), "created": 0}
                      for name in ("fix-api", "tidy-docs", "web-portal")]
        self.gone = threading.Event()         # the test is over: every fake returns at once
        self.reads, self.said = [], []
        self.threads = set(threading.enumerate())

        def listing(*args, **kwargs):
            self.reads.append(time.monotonic())
            if len(self.reads) > 1:           # the first read is the records as they stand
                self.gone.wait(READ)
            return [dict(seat) for seat in self.seats]

        def row_state(cfg, session, look=True, **facts):
            if look:
                self.gone.wait(SLOW)          # the seat's pane captured and its hooks read
            return {"word": "working", "reason": "", "since": None}

        def maintenance(log=print):
            self.gone.wait(SLOW)
            log(REAPED)

        for target, name, fake in (
                (orch, "listing", listing),
                (menu, "run_records", list),
                (menu, "seat_row_state", row_state),
                (menu.history, "estimate_seconds", lambda repo: 600),
                (menu, "seat_progress", lambda name: (1, 3)),
                (orch, "job_notices", lambda: []),
                (orch, "maintenance", maintenance),
                (menu, "show_notices", lambda messages: messages and self.said.append(
                    (time.monotonic(), messages))),
                (menu.Live, "probe", lambda self, now=None: False),
                (menu, "update_first", lambda live=None, **_kw: None),
                (macbridge, "start_background", lambda: None),
                (watch, "resume_after_boot", lambda *args, **kwargs: None),
                (config, "server_alias", lambda: None),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),
                (terminal, "width", lambda *args: 90)):
            self.stack.enter_context(patch.object(target, name, fake))
        self.stack.enter_context(patch.dict(menu._ESTIMATES, clear=True))
        self.addCleanup(self.settle)   # before the fakes go: every thread left behind has ended

    def settle(self):
        """Every thread the menu left behind ended."""
        self.gone.set()
        for thread in set(threading.enumerate()) - self.threads:
            thread.join(15)
            self.assertFalse(thread.is_alive(), thread)

    def menu(self, answer):
        """`ak`, each wait answered by `answer()`, or waited out on the wake pipe for a twentieth
        of a second when it answers None; what main answered, and when it started (`began`)."""
        def wait_key(prompt, timeout=None, wake=None):
            key = answer()
            if key is None:
                select.select([wake] if wake is not None else [], [], [], 0.05)
            return key

        self.began = time.monotonic()
        self.live = menu.Live(self.cfg)
        with menu_input(wait=wait_key, return_value=""), \
                patch.object(menu, "Live", return_value=self.live), \
                redirect_stdout(io.StringIO()):
            return menu.main([])

    def test_the_first_frame_comes_at_once_and_maintenance_s_notice_after_it(self):
        waits = []

        def answer():
            waits.append(time.monotonic())
            return Key("esc") if self.said and self.live.tidied.is_set() else None

        self.assertEqual(self.menu(answer), 0)
        self.assertLess(waits[0] - self.began, FRAME, "the first frame")
        (said_at, said), = self.said
        self.assertEqual(said, [REAPED])
        self.assertGreater(said_at, waits[0])
        self.assertGreater(len(waits), 10)      # the screen answered all along

    def test_a_maintenance_notice_does_not_mean_its_effects_have_finished(self):
        finish, effects = threading.Event(), []
        self.addCleanup(finish.set)

        def maintenance(log=print):
            log(REAPED)
            if finish.wait(10):
                effects.append("finished")

        def answer():
            if self.said:
                if not finish.is_set():
                    self.assertFalse(self.live.tidied.is_set())
                    finish.set()
                if self.live.tidied.is_set():
                    self.assertEqual(effects, ["finished"])
                    return Key("esc")
            return None

        with patch.object(orch, "maintenance", side_effect=maintenance):
            self.assertEqual(self.menu(answer), 0)
        self.assertEqual([messages for _, messages in self.said], [[REAPED]])

    def test_esc_leaves_at_once_with_a_read_going(self):
        pressed = []

        def answer():
            if not pressed:
                pressed.append(None)        # the wait runs out: a read is asked
                return None
            until = time.monotonic() + 1
            while len(self.reads) < 2 and time.monotonic() < until:
                time.sleep(0.005)
            pressed.append(time.monotonic())
            return Key("esc")

        self.assertEqual(self.menu(answer), 0)
        left = time.monotonic()
        self.assertLess(left - pressed[-1], FRAME, "Esc")
        self.assertEqual(len(self.reads), 2)
        self.assertLess(left - self.reads[1], READ, "the read is still going as the menu leaves")
        self.assertEqual(self.said, [])         # maintenance, too

    def test_a_mocked_live_cannot_request_a_restart(self):
        # Login and config tests stub Live without supplying any update messages.
        with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                         "return_value.asking.return_value": None}), \
                patch.object(menu, "wait_key", return_value=Key("esc")) as keys, \
                patch.object(menu.os, "execve") as restart, redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        restart.assert_not_called()
        self.assertEqual(keys.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
