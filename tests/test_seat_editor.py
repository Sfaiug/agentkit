"""A seat launched with ak's editor, of a harness naming the keys that open it, is found by its
pane, and asked a step of that editor (`watch._edit`) whose answer is the only word ak takes on
it, the ask taken back after for the owner's own edit never to find (19 Oct 2026).  Offline:
fixtures.editor_seat."""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE
from agentkit import aside_editor, watch

DRAFT = "and add these posts"


class SeatEditor(EditorSeat):
    def test_a_seat_launched_with_ak_s_editor_is_found_by_its_pane_and_keys(self):
        self.assertEqual(watch.seat_editor(self.seat, self.cfg),
                         {"id": PANE, "tty": str(self.tty), "keys": ("C-g",), "shows": ()})
        self.launched = False
        self.assertIsNone(watch.seat_editor(self.seat, self.cfg))
        self.launched = True
        with patch.object(watch, "screen", return_value={"editor": ()}):
            self.assertIsNone(watch.seat_editor(self.seat, self.cfg))

    def test_a_step_is_taken_on_its_editor_s_answer_and_its_ask_taken_back(self):
        where = watch.seat_editor(self.seat, self.cfg)
        self.show(DRAFT)
        self.deaf = True
        self.assertIsNone(watch._edit(self.seat, where, "line", LINE))
        # given up on: an edit its keys open late leaves the composer as it is
        self.deaf = False
        self.press("C-g")
        self.assertEqual((self.composer, self.buffers, self.ask, self.opened),
                         (DRAFT, {}, None, []))
        self.assertEqual(watch._edit(self.seat, where, "line", LINE), "line")
        kept = aside_editor.pack(aside_editor.ASIDE, LINE.encode(), DRAFT.encode())
        self.assertEqual((self.composer, self.buffers, self.ask),
                         (LINE, {aside_editor.kept(PANE): kept}, None))
        self.assertEqual(watch._edit(self.seat, where, "back", LINE), "unsent")
        self.press("Enter")
        self.assertEqual(watch._edit(self.seat, where, "back", LINE), "sent")
        self.assertEqual((self.keys, self.composer, self.ask),
                         (["C-g"] * 4 + ["Enter", "C-g"], DRAFT, None))


if __name__ == "__main__":
    unittest.main()
