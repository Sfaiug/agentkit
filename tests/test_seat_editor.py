"""A seat launched with ak's editor, of a harness naming the keys that open it, is found by its
pane, and asked a step of that editor (`watch._edit`) that ak takes only the screen's word on,
the ask taken back after for the owner's own edit never to find (19 Oct 2026).  Offline:
fixtures.editor_seat."""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from agentkit import aside_editor, watch

DRAFT = "and add these posts"


class SeatEditor(EditorSeat):
    def holds(self, text):
        return watch.composer_holds(self.seat["name"], self.seat, text, self.cfg)

    def test_a_seat_launched_with_ak_s_editor_is_found_by_its_pane_and_keys(self):
        self.assertEqual(watch.seat_editor(self.seat, self.cfg),
                         {"id": PANE, "tty": str(self.tty), "keys": ("C-g",)})
        self.launched = False
        self.assertIsNone(watch.seat_editor(self.seat, self.cfg))
        self.launched = True
        with patch.object(watch, "screen", return_value={"editor": ()}):
            self.assertIsNone(watch.seat_editor(self.seat, self.cfg))

    def test_a_step_is_taken_on_the_screen_s_word_and_its_ask_taken_back(self):
        where = watch.seat_editor(self.seat, self.cfg)
        self.show(DRAFT)
        for deaf, done in ((True, False), (False, True)):
            self.deaf = deaf
            self.assertEqual(watch._edit(self.seat, where, "line",
                                         settled=lambda: self.holds("") == "empty"), done)
            self.assertIsNone(self.ask)
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): DRAFT.encode()})
        self.assertTrue(watch._edit(self.seat, where, "back",
                                    settled=lambda: self.holds(DRAFT) == "line"))
        self.assertEqual((self.keys, self.composer, self.buffers, self.ask),
                         (["C-g"] * 3, DRAFT, {}, None))


if __name__ == "__main__":
    unittest.main()
