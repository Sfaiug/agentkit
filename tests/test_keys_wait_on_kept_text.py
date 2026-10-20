"""Text ak's editor keeps of any pane of a seat's, or of the pane a line's keys go to wherever
it has moved, set aside for a line or given back, keeps every line of ak's from going in as
keys: a composer can draw that text late, reading empty while it holds it, and keys typed there
would join it, whichever pane the owner selects.  So does a seat tmux cannot say that of.
Offline: fixtures.editor_seat.
"""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE
from agentkit import aside_editor, orch, watch


def kept(pane, state=aside_editor.ASIDE):
    return {aside_editor.kept(pane): aside_editor.pack(state, b"an earlier line", b"my notes")}


class KeysWaitOnKeptText(EditorSeat):
    def typed_line(self):
        return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)

    def test_text_the_editor_keeps_of_any_pane_of_the_seat_holds_back_a_line_as_keys(self):
        self.panes.append("%8")         # one the owner split off, and may select meanwhile
        for pane, state in ((PANE, aside_editor.ASIDE), ("%8", aside_editor.GIVEN)):
            with self.subTest(pane=pane):
                self.buffers = kept(pane, state)
                self.assertFalse(self.typed_line())
        self.buffers = kept("%9")       # another seat's
        tmux = orch.tmux_out
        for ask in ("list-buffers", "list-panes"):
            with self.subTest(ask=ask), patch.object(
                    orch, "tmux_out", side_effect=lambda *args, **kw: (1, "no server") if (
                        args[0] == ask) else tmux(*args, **kw)):
                self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.keys, self.typed, self.sent), (["Enter"], [LINE], [LINE]))

    def test_text_kept_of_the_pane_keys_go_to_holds_them_back_once_it_left_the_seat(self):
        # swapped into another session after the pass named it: keys still go to it by id
        self.panes, self.buffers = ["%9"], kept(PANE, aside_editor.GIVEN)
        self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))


if __name__ == "__main__":
    unittest.main()
