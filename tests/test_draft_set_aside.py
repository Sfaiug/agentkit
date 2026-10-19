"""Text the owner left standing in a seat's composer never keeps ak's line out of it.

A seat ended its turn on `ak wait`; the run merged, and its end could not be typed in while the
owner's unsent text held the composer, so the seat sat and the owner was paged (19 Oct 2026).
Once that text has stood unchanged a while, ak sets it aside with the harness's own keys, types
its line, and brings the text back.  Offline: fixtures.seats' throwaway seats, its tmux faked
as a composer with Claude Code's prompt history.
"""

import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, SEAT, Seats
from agentkit import watch

DRAFT = "and add these posts"


class DraftSetAside(Seats):
    def setUp(self):
        super().setUp()
        self.composer, self.history, self.up, self.keys = DRAFT, [], 0, []
        self.show()

    def show(self):
        self.pane = (self.base.replace(self.empty, f"❯ {self.composer}\n") if self.composer
                     else self.base)
        self.free = not self.composer

    def tmux(self, *args, **kwargs):
        if args[0] != "send-keys":
            return super().tmux(*args, **kwargs)
        key = args[-1]
        self.keys.append("text" if "-l" in args else key)
        if "-l" in args:
            self.typed.append(key)
            self.composer += key
        elif key in ("Enter", "C-c"):
            # what Ctrl-C empties is filed in the history beside what Enter sends
            self.history.append(self.composer)
            self.composer, self.up = "", 0
        elif key == "Up":
            self.up += 1
            self.composer = self.history[-self.up]
        self.show()
        return 0, ""

    def later(self, seconds):
        watch.time.time = lambda: NOW + seconds

    def test_a_draft_that_stood_still_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.tick()
        self.assertEqual(self.keys, [])
        self.later(watch.DRAFT_STILL)
        self.tick()
        self.assertEqual(self.keys, ["C-c", "text", "Enter", "Up", "Up"])
        self.assertEqual(self.typed, [LINE])
        self.assertEqual(self.composer, DRAFT)
        self.assertTrue(self.told())
        self.assertIsNone(watch.seat_read(SEAT).get("aside"))

    def test_a_draft_still_changing_is_left_alone(self):
        self.wait_line()
        for step in range(3):
            self.composer += " more"
            self.show()
            self.later(step * watch.DRAFT_STILL)
            self.tick()
        self.assertEqual(self.keys, [])
        self.assertFalse(self.told())

    def test_a_line_that_could_not_go_in_puts_the_draft_back_untouched(self):
        self.wait_line()
        self.tick()
        self.later(watch.DRAFT_STILL)
        # the owner's next key arrives right after the draft is set aside
        unread = iter([False, False, True])
        with patch.object(watch, "pane_unread", side_effect=lambda _seat: next(unread, False)):
            self.tick()
        self.assertEqual(self.keys, ["C-c", "Up"])
        self.assertEqual(self.typed, [])
        self.assertEqual(self.composer, DRAFT)
        self.assertFalse(self.told())


if __name__ == "__main__":
    unittest.main()
