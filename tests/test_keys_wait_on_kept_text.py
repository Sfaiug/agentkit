"""Text ak's editor keeps of a seat's composer, set aside for a line or given back, keeps every
line of ak's from going in as keys: the composer can draw that text late, reading empty while it
holds it, and keys typed there would join it.  So does a seat tmux cannot say is one launched
with that editor, or what that editor keeps.  Offline: fixtures.editor_seat.
"""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE
from agentkit import aside_editor, orch, watch


class KeysWaitOnKeptText(EditorSeat):
    def typed_line(self):
        return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)

    def test_text_the_editor_keeps_holds_back_a_line_its_empty_screen_would_take(self):
        for state in (aside_editor.ASIDE, aside_editor.GIVEN):
            with self.subTest(state=state):
                self.buffers = {aside_editor.kept(PANE): aside_editor.pack(
                    state, b"an earlier line", b"and add these posts")}
                self.assertFalse(self.typed_line())
        self.buffers.clear()
        tmux = orch.tmux_out
        for ask in ("#{pane_id}", "#{buffer_name}"):         # the seat's pane, or what is kept
            with self.subTest(ask=ask), patch.object(
                    orch, "tmux_out", side_effect=lambda *args, **kw: (1, "no server") if (
                        args[-1].startswith(ask)) else tmux(*args, **kw)):
                self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.keys, self.typed, self.sent), (["Enter"], [LINE], [LINE]))


if __name__ == "__main__":
    unittest.main()
