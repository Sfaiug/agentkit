"""A menu's watcher outlives a round that raises: the menu goes on showing what its seats say.

Every open menu's rows come from one thread, `Live._watch`, and a round of it that raised
anything but the five kinds its read was caught for ended it: that menu showed its last good read
until it was closed. A real `Live` in `Sandbox`'s temporary HOME, a fake listing and no tmux.
"""

import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, watch

SEAT = "fix-api"


class WatcherOutlivesARoundThatRaises(Sandbox):
    def live(self):
        config.save_session(self.cfg, SEAT, "astra", ["opus"],
                            {"cwd": str(self.root), "created": 10000})
        found = [{"name": SEAT, "path": str(self.root), "repo": None, "created": 10000,
                  "attached": False, "exited": False, "legacy": False, "resumable": False}]
        for patched in (patch.object(orch, "listing", side_effect=lambda **_kw: list(found)),
                        patch.object(orch, "tmux_out", return_value=(0, ""))):
            patched.start()
            self.addCleanup(patched.stop)
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        live.watch([[], None])
        live.looker.join()       # the first look's word is in before the one this test writes
        return live

    def word(self, live):
        return {row["name"]: row for row in live.last[1][1]}[SEAT]["word"]

    def survives(self, step):
        """`step` of a live menu's round raising once, then the seat's record changing."""
        live = self.live()
        stepping, raised = getattr(live, step), []

        def once(*args, **kw):
            if not raised:
                raised.append(step)
                raise subprocess.TimeoutExpired(["git", "status"], 5)
            return stepping(*args, **kw)

        with patch.object(live, step, side_effect=once):
            live.ask()
            for _ in range(3000):
                if raised:
                    break
                time.sleep(0.01)
            self.assertTrue(raised, f"no round reached {step}")
            word = "done" if self.word(live) != "done" else "needs you"
            watch.seat_write(SEAT, word=word, reason="", word_since=None)
            for _ in range(3000):
                if self.word(live) == word or not live.watcher.is_alive():
                    break
                time.sleep(0.01)
            self.assertTrue(live.watcher.is_alive(), f"the watcher ended on {step} raising")
            self.assertEqual(self.word(live), word)

    def test_a_read_that_times_out_once_leaves_the_rows_live(self):
        self.survives("read")

    def test_a_look_at_the_records_that_times_out_once_leaves_the_rows_live(self):
        self.survives("recorded")

    def rounds(self, step, error, asking):
        """When each round began, `step` raising `error` in every one and an ask pending at every
        wait, the main loop's again each round with `asking`: an event already set ends its wait
        at once, one not set waits its whole timeout."""
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        clock, began = [0.0], []

        def waits(event):
            def wait(timeout=None):
                if event.is_set():
                    return True
                clock[0] += timeout
                if clock[0] >= 10 * menu.STIR:
                    live.done.set()
                return False
            return wait

        def raising(*_args, **_kw):
            began.append(clock[0])
            if asking:
                live.ask()          # the main loop's, every TICK
            if len(began) > 100:
                live.done.set()     # spinning: end it, for the count to say so
            raise error

        live.ask()
        with patch.object(live.asked, "wait", waits(live.asked)), \
                patch.object(live.done, "wait", waits(live.done)), \
                patch.object(live, step, side_effect=raising):
            live._watch()
        self.assertTrue(live.asked.is_set(), "the ask is no longer pending")
        self.assertFalse(live.drain(), f"a round {step} dropped woke a draw")
        return began

    def test_a_round_that_always_raises_goes_round_once_a_stir_an_ask_pending(self):
        # a look at the records raises before its round takes the ask, so the first stays
        # pending; a read raises after, as any read takes it, so the main loop's next is
        for step, error, asking in (
                ("recorded", subprocess.TimeoutExpired(["git", "status"], 5), False),
                ("read", OSError("unreadable row"), True)):
            with self.subTest(step=step):
                self.assertEqual(self.rounds(step, error, asking),
                                 [n * menu.STIR for n in range(10)])


if __name__ == "__main__":
    unittest.main()
