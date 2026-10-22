"""Text the owner left standing in a seat never keeps ak's line out of it: ak's editor sets the
text aside and puts the line in its place, the line's Enter sends it alone, and the editor gives
the text back into the composer that Enter emptied (19 Oct 2026).  Whatever of that went missing
is the line's mark's pass, read off the editor, which reads the composer itself: the screen draws
what the editor put there late.  Offline: fixtures.editor_seat; the tick is the give-back pass,
then the wait pass.
"""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE, REPO
from agentkit import aside_editor, watch

DRAFT = "and add these posts"
DOCS = "The docs finished."
FIXTURES = REPO / "tests/fixtures"


def kept(state, held=DRAFT, line=LINE):
    """The buffers holding the record ak's editor keeps for that line."""
    return {aside_editor.kept(PANE): aside_editor.pack(state, line.encode(), held.encode())}


class LinePastOwnersText(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(watch.DRAFT_STILL)
        self.show(DRAFT)
        self.wait_line()

    def tick(self):
        watch.drafts_back(self.cfg)
        super().tick()

    def typed_line(self, text=DOCS):
        return watch.type_at_prompt(self.seat, text, lambda _: None, cfg=self.cfg)

    def undrawn(self):
        """A seat whose screen draws what ak's editor hands its composer only long after."""
        press = self.press

        def late(key, pane=PANE):
            press(key, pane)
            if key == "C-g":
                self.late = 99
        return patch.object(self, "press", side_effect=late)

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
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

    def test_text_comes_back_at_once_though_the_line_s_enter_was_the_last_key_its_terminal_took(self):
        press = self.press

        def taken(key, pane=PANE):      # a terminal marks the keys it takes, ak's as the owner's
            press(key, pane)
            self.untouched(0)
        with patch.object(self, "press", side_effect=taken):
            self.tick()
        self.assertEqual((self.keys, self.sent, self.composer, self.told()),
                         (["C-g", "Enter", "C-g"], [LINE], DRAFT, True))

    def test_text_comes_back_on_a_later_pass_once_a_slow_screen_draws_the_emptied_composer(self):
        press = self.press

        def taken(key, pane=PANE):
            press(key, pane)
            self.untouched(0)
            if key == "Enter":          # its screen still shows the line it sent
                self.draw(LINE)
                self.late = 99
        with patch.object(self, "press", side_effect=taken):
            self.tick()
            self.assertEqual((self.sent, self.composer, self.told()), ([LINE], "", False))
            self.show("")
            self.tick()
        self.assertEqual((self.composer, self.told()), (DRAFT, True))

    def test_a_line_its_enter_left_unsent_goes_first_and_its_text_comes_back_after(self):
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()
        self.assertEqual((self.sent, self.composer, self.buffers, self.told()),
                         ([], LINE, kept(aside_editor.ASIDE), False))
        # never set aside as the owner's for another line of ak's
        self.assertFalse(self.typed_line())
        self.assertEqual((self.composer, self.buffers), (LINE, kept(aside_editor.ASIDE)))
        self.tick()                     # the mark's pass: its Enter
        self.assertEqual((self.sent, self.told()), ([LINE], False))
        self.tick()                     # the text back into the composer it emptied
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))

    def test_a_line_the_screen_never_drew_is_told_by_its_editor_never_by_that_screen(self):
        self.buffers.update(kept(aside_editor.GIVEN))   # given back, its screen still empty
        self.show("")
        self.composer, self.late = DRAFT, 99
        with self.undrawn():
            self.tick()
            self.assertEqual((self.keys, self.sent, self.told()), (["C-g"], [], False))
            self.tick()                 # the editor finds the line still there: its Enter
        self.assertEqual((self.keys.count("Enter"), self.sent, self.told()), (1, [LINE], False))
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))

    def test_text_never_comes_back_into_a_question_the_line_s_turn_put_up(self):
        question = (FIXTURES / "claude-question-pane.txt").read_text()
        enter = watch._send_enter

        def asked(session, log):
            sent = enter(session, log)
            self.pane = question
            return sent
        with patch.object(watch, "_send_enter", side_effect=asked):
            self.tick()
            self.tick()
        self.assertEqual((self.keys, self.sent, self.composer, self.told()),
                         (["C-g", "Enter"], [LINE], "", False))
        self.show("")                   # answered, and its turn on
        self.tick()
        self.assertEqual((self.composer, self.told()), (DRAFT, True))

    def test_a_line_the_owner_edited_is_theirs_and_no_other_line_sets_it_aside(self):
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()
        edited = f"{LINE} and the docs"
        self.show(edited)
        self.assertFalse(self.typed_line())
        self.tick()
        self.assertEqual((self.composer, self.buffers, self.sent, self.told()),
                         (edited, kept(aside_editor.ASIDE), [], False))
        self.press("Enter")             # the owner sends it
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([edited], DRAFT, True))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.sent, self.composer), ([edited, DOCS], DRAFT))

    def test_text_given_back_waits_for_input_the_line_s_enter_left_unread(self):
        press = self.press

        def typing(key, pane=PANE):
            press(key, pane)
            self.unread = self.unread or key == "Enter"
        with patch.object(self, "press", side_effect=typing):
            self.tick()
        self.assertEqual((self.keys, self.sent, self.composer, self.told()),
                         (["C-g", "Enter"], [LINE], "", False))
        self.unread = False
        self.tick()
        self.assertEqual((self.composer, self.told()), (DRAFT, True))

    def test_text_too_tall_to_read_or_typed_mid_turn_stays(self):
        tall = "\n".join(f"pasted row {n} of a long paste" for n in range(1, 61))
        self.show(tall)
        self.assertIsNone(watch.composer_draft("claude", self.pane))
        self.assertFalse(self.typed_line())
        # a composer scrolled past its rows shows only the end of what it holds
        self.pane = (FIXTURES / "antigravity-tall-line-pane.txt").read_text()
        with patch.object(watch, "seat_model", return_value=("antigravity", "acme")):
            self.assertFalse(self.typed_line())
        self.pane = (FIXTURES / "claude-draft-while-working-pane.txt").read_text()
        self.assertFalse(self.typed_line())
        # a turn that starts as the step reads its screen
        self.show(DRAFT)
        step = watch._editor_read

        def started(*args, **kwargs):
            self.pane = (FIXTURES / "claude-draft-while-working-pane.txt").read_text()
            return step(*args, **kwargs)
        with patch.object(watch, "_editor_read", side_effect=started):
            self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))

    def test_a_draft_holding_a_paste_its_editor_would_lose_stays(self):
        # Muse's editor sends a paste's placeholder alone, the paste gone -- pasted too once a
        # line went in through that editor, before its mark's pass, or above the rows read
        self.buffers.update(kept(aside_editor.ASIDE))
        mark = {"line": LINE, "seat": self.seat["created"], "pane": PANE}
        loses = dict(watch.screen("claude"), editor_refuses=watch.screen("muse")["editor_refuses"])
        tall = "\n".join(f"pasted row {n} of a long paste" for n in range(1, 61))
        with patch.object(watch, "screen", return_value=loses):
            for draft in (f"{DRAFT} [Pasted Content 1190 chars]",
                          f"[Pasted Content 1190 chars]\n{tall}"):
                self.show(draft)
                self.assertFalse(self.typed_line())
                self.assertFalse(watch.type_at_prompt(self.seat, LINE, lambda _: None,
                                                      cfg=self.cfg, typed=mark))
        self.assertEqual((self.keys, self.typed), ([], []))

    def test_a_picker_the_owner_opens_over_their_text_as_the_step_reads_it_takes_no_step(self):
        # Enter under it picks a row, a key moves its highlight, and it reads as typed text or as
        # a composer left empty, which text kept goes past too
        self.buffers.update(kept(aside_editor.GIVEN))
        step = watch._editor_read
        for harness, picker in (("codex", "codex-model-picker-pane.txt"),
                                ("antigravity", "antigravity-chooser-pane.txt"),
                                ("muse", "muse-model-picker-pane.txt")):
            draft = (FIXTURES / f"{harness}-draft-pane.txt").read_text()

            def opened(*args, **kwargs):
                self.pane = (FIXTURES / picker).read_text()
                try:
                    return step(*args, **kwargs)
                finally:
                    self.pane = draft
            self.pane = draft
            with self.subTest(harness=harness), patch.object(
                    watch, "seat_model", return_value=(harness, "acme")), patch.object(
                    watch, "_editor_read", side_effect=opened):
                self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))


if __name__ == "__main__":
    unittest.main()
