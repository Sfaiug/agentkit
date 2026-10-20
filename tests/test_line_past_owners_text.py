"""Text the owner left standing in a seat never keeps ak's line out of it: ak's editor sets it
aside, puts the line in its place for its Enter to send alone and gives the text back into the
composer that Enter emptied, on its own read of a composer the screen draws late (19 Oct 2026).
Offline: fixtures.editor_seat; the tick is the set-aside pass, then the wait pass."""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE, REPO
from agentkit import aside_editor, watch

DRAFT = "and add these posts"
DOCS = "The docs finished."


def kept(state, held=DRAFT, line=LINE):
    """The buffers holding the record ak's editor keeps for that line."""
    return {aside_editor.kept(PANE): aside_editor.pack(state, line.encode(), held.encode())}


class LinePastOwnersText(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(watch.DRAFT_STILL)
        self.show(DRAFT)

    def tick(self):
        watch.drafts_back(self.cfg)
        super().tick()

    def typed_line(self, text=DOCS):
        return watch.type_at_prompt(self.seat, text, lambda _: None, cfg=self.cfg)

    def losing(self, word):
        """ak's editor, whose answer `word` never reaches its pane."""
        answer = self.editor_tmux
        return patch.object(aside_editor, "_tmux", side_effect=lambda *args, data=None: None if (
            args[0] == "set-option" and args[-1].endswith(f" {word}")) else answer(*args, data=data))

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.deaf = True
        self.tick()
        # an editor that never answers gets no Enter, and leaves no line written as typed
        self.assertEqual((self.keys, self.composer, self.receipts(), self.told()),
                         (["C-g"], DRAFT, [], False))
        self.deaf = False
        self.tick()
        self.assertEqual((self.keys[1:], self.typed, self.sent, self.composer, self.opened),
                         (["C-g", "Enter", "C-g"], [], [LINE], DRAFT, []))
        self.assertEqual((self.buffers, len(self.receipts()), self.told()),
                         (kept(aside_editor.GIVEN), 1, True))
        # text given back, drawn late, is the editor's to read for the next line too
        self.late = 99
        self.assertTrue(self.typed_line())
        self.assertEqual((self.typed, self.sent, self.composer), ([], [LINE, DOCS], DRAFT))

    def test_a_line_its_enter_left_unsent_goes_first_and_its_text_comes_back_after(self):
        self.wait_line()
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()
        self.assertEqual((self.sent, self.composer, self.buffers, self.told()),
                         ([], LINE, kept(aside_editor.ASIDE), False))
        # never set aside as the owner's for another line of ak's
        self.assertFalse(self.typed_line())
        self.assertEqual((self.composer, self.buffers), (LINE, kept(aside_editor.ASIDE)))
        self.panes.append("%8")
        self.selected = "%8"            # each key still into the pane the line is in
        self.tick()                     # the mark's pass: its Enter
        self.tick()                     # the text back into the composer it emptied
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))
        self.assertEqual(set(self.pressed_in), {PANE})

    def test_a_line_is_read_in_its_own_pane_never_by_an_older_record_of_it(self):
        self.wait_line()
        self.panes.append("%8")
        self.selected = "%8"
        self.buffers = kept(aside_editor.GIVEN, held="older notes")     # once before, in %7
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()
        self.tick()                     # the mark's pass: its Enter into %8
        self.assertEqual((self.sent, self.told()), ([LINE], False))
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))

    def test_a_question_up_after_its_enter_gets_no_editor_key_and_its_text_comes_back_after(self):
        self.wait_line()
        question, press = (REPO / "tests/fixtures/claude-question-pane.txt").read_text(), self.press

        def asked(key, pane=PANE):
            press(key, pane)
            if key == "Enter":          # the turn the line began asks at once
                self.pane, self.late = question, 999
        with patch.object(self, "press", side_effect=asked):
            self.tick()
        self.assertEqual((self.keys, self.sent, self.buffers, self.told()),
                         (["C-g", "Enter"], [LINE], kept(aside_editor.ASIDE), False))
        self.show("")                   # answered, and another line goes in through it first
        self.assertTrue(self.typed_line())
        self.show(self.composer)        # the text it gave back, drawn
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE, DOCS], DRAFT, True))

    def test_a_line_drawn_late_is_not_delivered_on_a_composer_drawn_empty(self):
        self.wait_line()
        self.buffers = kept(aside_editor.GIVEN, line=DOCS)
        self.draw("")                   # the text given back, not drawn yet
        with patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw: self.pane):
            self.tick()
            self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([], LINE, False))
        self.draw(LINE)                 # drawn at last
        self.tick()
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))

    def test_a_line_whose_answers_went_missing_is_ak_s_never_sent_with_the_owner_s_text(self):
        with self.losing("line"):       # put, its answer lost: the next pass's own line
            self.assertFalse(self.typed_line())
        self.assertTrue(self.typed_line())
        self.assertEqual((self.sent, self.composer, self.buffers), ([DOCS], DRAFT, kept(
            aside_editor.GIVEN, line=DOCS)))
        self.wait_line()
        with self.losing("sent"):       # given back, its word lost, the line still drawn
            self.tick()
            self.draw(LINE)
            self.late = 99
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([DOCS, LINE], DRAFT, True))

    def test_text_too_tall_to_read_goes_aside_too(self):
        tall = "\n".join(f"pasted row {n} of a long paste" for n in range(1, 61))
        self.show(tall)
        self.assertIsNone(watch.composer_draft("claude", self.pane))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.sent, self.composer), ([DOCS], tall))

    def test_text_typed_lately_mid_turn_under_a_question_a_picker_or_before_the_editor_stays(self):
        self.untouched(watch.DRAFT_STILL - 10)
        self.assertFalse(self.typed_line())
        self.untouched(watch.DRAFT_STILL)
        for pane in ("claude-draft-while-working-pane.txt", "claude-question-pane.txt",
                     "claude-dialog-pane.txt"):
            self.pane = (REPO / "tests/fixtures" / pane).read_text()
            self.assertFalse(self.typed_line())
        for harness, pane in (("codex", "codex-model-picker-pane.txt"),
                              ("antigravity", "antigravity-chooser-pane.txt")):
            self.pane = (REPO / "tests/fixtures" / pane).read_text()
            with patch.object(watch, "seat_model", return_value=(harness, "acme")):
                self.assertFalse(self.typed_line())
                # nor by the last read before any key of its editor's, the tick's way back's too
                self.assertIsNone(watch._editor_read(dict(self.seat, pane=PANE), watch.seat_editor(
                    self.seat, self.cfg), self.cfg))
        self.show(DRAFT)
        self.unread = True
        self.assertFalse(self.typed_line())
        self.unread, self.launched = False, False
        self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))


if __name__ == "__main__":
    unittest.main()
