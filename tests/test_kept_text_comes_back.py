"""Text ak's editor set aside from a seat's composer for a line comes back on the tick, however
the line's own pass ended, once that composer is empty and the owner has left the seat alone:
the editor hands it back only into an empty composer, and a line still there is the mark's pass
to send first.  Every read and key of it goes to the pane the text came from, whichever pane the
owner selects.  Offline: fixtures.editor_seat; the tick's pass is `watch.drafts_back`.
"""

import unittest

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE, REPO
from agentkit import aside_editor, watch

DRAFT = "and add these posts"


def kept(state, pane=PANE):
    """The buffers holding DRAFT, set aside for LINE (`aside_editor.ASIDE`) or given back."""
    return {aside_editor.kept(pane): aside_editor.pack(state, LINE.encode(), DRAFT.encode())}


class KeptTextComesBack(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(watch.DRAFT_STILL)
        self.buffers.update(kept(aside_editor.ASIDE))

    def tick(self):
        watch.drafts_back(self.cfg)

    def test_text_set_aside_comes_back_into_the_empty_composer_once(self):
        self.tick()
        self.assertEqual((self.keys, self.composer, self.buffers),
                         (["C-g"], DRAFT, kept(aside_editor.GIVEN)))
        self.show("")                   # the owner sent it: never asked back again
        self.tick()
        self.assertEqual((self.keys, self.composer), (["C-g"], ""))

    def test_text_comes_back_to_its_own_pane_while_the_owner_has_another_selected(self):
        self.panes.append("%8")
        self.buffers = kept(aside_editor.ASIDE, "%8")
        self.tick()
        self.assertEqual((self.keys, self.composer, self.buffers),
                         (["C-g"], DRAFT, kept(aside_editor.GIVEN, "%8")))

    def test_text_waits_for_an_empty_composer_the_owner_left_alone(self):
        self.untouched(watch.DRAFT_STILL - 10)
        self.tick()
        self.untouched(watch.DRAFT_STILL)
        self.unread = True
        self.tick()
        self.unread = False
        self.pane = (REPO / "tests/fixtures/claude-question-pane.txt").read_text()
        self.tick()
        for composer in (LINE, "typed since"):      # ak's line, or the owner's own text
            self.show(composer)
            self.tick()
        self.assertEqual((self.keys, self.composer), ([], "typed since"))
        self.show("")
        self.tick()
        self.assertEqual((self.keys, self.composer), (["C-g"], DRAFT))


if __name__ == "__main__":
    unittest.main()
