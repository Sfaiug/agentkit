"""ak presses Enter only while a seat's composer holds ak's line alone, whoever types the line:
a key the owner adds once ak's text is in, before its Enter, is never sent joined to it, and
the line goes once that key is gone again (12 Nov 2026).  Offline: fixtures.editor_seat; the
owner types in the pauses ak takes before the Enter.
"""

import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.editor_seat import EditorSeat
from fixtures.seats import LINE, NOW
from agentkit import watch

OWNER = "x"     # one key of the owner's


class TypedThroughTypeInto(EditorSeat):
    def setUp(self):
        super().setUp()
        self.joined, self.unpressed, self.kept = 0, None, 3
        clock = Clock(self.pause)
        clock.time = lambda: NOW
        patcher = patch.object(watch, "time", clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def type_line(self):
        return watch.type_into(self.seat, LINE, lambda _: None)

    def pause(self, _seconds):
        """The owner's key joins ak's line once it is in, and goes again after `kept` pauses."""
        if self.composer == LINE and not self.joined:
            self.show(LINE + OWNER)
        elif self.composer == LINE + OWNER:
            self.joined += 1
            if self.joined == self.kept:
                self.unpressed = list(self.keys)
                self.show(LINE)

    def test_the_owner_s_key_holds_the_enter_back_until_it_is_gone(self):
        self.assertTrue(self.type_line())
        self.assertEqual((self.unpressed, self.keys, self.sent), ([], ["Enter"], [LINE]))

    def test_a_key_the_owner_leaves_there_is_never_sent(self):
        self.kept = None
        self.assertFalse(self.type_line())
        self.assertEqual((self.keys, self.sent, self.composer), ([], [], LINE + OWNER))


class TypedThroughTypeAtPrompt(TypedThroughTypeInto):
    def type_line(self):
        return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)


if __name__ == "__main__":
    unittest.main()
