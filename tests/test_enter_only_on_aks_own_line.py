"""ak presses Enter only while `composer_holds` reads a seat's composer as ak's line, whoever
types it: a character the owner adds once ak's text is in, before its Enter, gets no Enter and
stays there with the line; once it is gone, a line `finish_own_lines` knows is sent (12 Nov
2026).  Offline: fixtures.editor_seat; the owner types in the pause ak takes before the Enter.
"""

import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.editor_seat import EditorSeat
from fixtures.seats import NOW
from agentkit import watch

LINE = watch.ACCOUNT_LINE   # a fixed line finish_own_lines knows
OWNER = "x"                 # one character of the owner's


class TypedThroughTypeInto(EditorSeat):
    def setUp(self):
        super().setUp()
        self.owner = OWNER
        clock = Clock(self.pause)
        clock.time = lambda: NOW
        patcher = patch.object(watch, "time", clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def type_line(self):
        return watch.type_into(self.seat, LINE, lambda _: None)

    def pause(self, _seconds):
        """The owner's character joins ak's line once it is in, once."""
        if self.composer == LINE and self.owner:
            self.show(LINE + self.owner)
            self.owner = ""

    def test_no_enter_while_the_owner_s_character_joins_the_line(self):
        self.assertFalse(self.type_line())
        self.assertEqual((self.keys, self.sent, self.composer), ([], [], LINE + OWNER))
        self.show(LINE)
        watch.finish_own_lines(self.cfg, lambda _: None)
        self.assertEqual((self.keys, self.sent), (["Enter"], [LINE]))


class TypedThroughTypeAtPrompt(TypedThroughTypeInto):
    def type_line(self):
        return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)


if __name__ == "__main__":
    unittest.main()
