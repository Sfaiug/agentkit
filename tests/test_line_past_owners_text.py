"""Text the owner left standing in a seat never keeps ak's line out of it: ak's editor sets the
text aside and puts the line in its place, the line's Enter sends it alone, and the editor gives
the text back over what that Enter left, each step on the editor's own word of the composer,
which the screen draws late (19 Oct 2026).  Offline: fixtures.editor_seat, unread input the
test's to set; the tick is the set-aside pass, then the wait pass.
"""

import contextlib
import os
import re
import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE, NOW, REPO
from agentkit import aside_editor, orch, watch

DRAFT = "and add these posts"
DOCS = "The docs finished."
KEPT = aside_editor.kept(PANE)


class LinePastOwnersText(EditorSeat):
    def setUp(self):
        super().setUp()
        self.unread = False
        patcher = patch.object(watch, "pane_unread", side_effect=lambda _session: self.unread)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.untouched(watch.DRAFT_STILL)
        self.show(DRAFT)

    def untouched(self, seconds):
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def tick(self):
        watch.drafts_back(self.cfg, lambda _: None)
        super().tick()

    def typed_line(self, text=DOCS):
        return watch.type_at_prompt(self.seat, text, lambda _: None, cfg=self.cfg)

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
        self.assertEqual((self.buffers, self.told()),
                         ({KEPT: f"{aside_editor.GIVEN}{DRAFT}".encode()}, True))
        self.show("")                   # the owner sent it: given back once, never asked again
        self.tick()
        self.assertEqual(len(self.keys), 4)

    def test_a_restore_drawn_late_is_never_sent_with_the_next_line(self):
        self.assertTrue(self.typed_line(LINE))
        self.late = 99                  # drawn long after
        self.assertEqual((self.composer, self.pane), (DRAFT, self.base))
        # typed as keys, the next line would join the text the screen does not show
        self.untouched(watch.DRAFT_STILL - 10)
        self.assertFalse(self.typed_line())
        self.untouched(watch.DRAFT_STILL)
        # nor where tmux cannot say which pane is the seat's
        with patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: (
                (1, "no server") if args[-1].startswith("#{pane_id}") else self.tmux(*args, **kw))):
            self.assertFalse(self.typed_line())
        self.assertTrue(self.typed_line())
        self.assertEqual((self.typed, self.sent, self.composer), ([], [LINE, DOCS], DRAFT))

    def test_text_comes_back_over_a_line_its_enter_never_sent_and_the_line_goes_next(self):
        self.wait_line()
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([], DRAFT, False))
        self.tick()
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], DRAFT, True))

    def test_a_line_whose_enter_and_answer_back_were_lost_goes_in_again_on_its_mark(self):
        marks, tmux = [], self.editor_tmux

        def answer_lost(*args, data=None):       # the text given back over the line
            return None if args[-1].endswith(" unsent") else tmux(*args, data=data)

        with patch.object(watch, "_send_enter", return_value=False), \
                patch.object(aside_editor, "_tmux", side_effect=answer_lost):
            self.assertFalse(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg,
                                                  receipt=marks.append))
        # never an Enter on a screen that still draws the line over the text given back
        self.assertTrue(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg,
                                             typed=marks[-1]))
        self.assertEqual((self.sent, self.composer, self.buffers),
                         ([DOCS], DRAFT, {KEPT: f"{aside_editor.GIVEN}{DRAFT}".encode()}))

    def test_text_whose_way_back_went_unanswered_comes_back_on_a_later_tick(self):
        self.wait_line()
        enter = self.press

        def deaf_after(key):
            enter(key)
            self.deaf = self.deaf or key == "Enter"

        with patch.object(self, "press", side_effect=deaf_after):
            self.tick()
        # sent on the screen's word: never typed twice
        self.assertEqual((self.sent, self.composer, self.told()), ([LINE], "", True))
        self.deaf, self.unread = False, True
        self.tick()                     # input the seat has not read yet
        self.unread = False
        self.show("typed since")        # the owner's own composer
        self.tick()
        self.assertEqual((self.composer, self.keys.count("C-g")), ("typed since", 2))
        self.show("")
        self.tick()
        self.assertEqual((self.sent, self.composer, self.keys.count("C-g")), ([LINE], DRAFT, 3))

    def test_keys_another_line_put_in_while_this_one_waited_on_the_seat_stop_it(self):
        held = watch.seat_held

        @contextlib.contextmanager
        def after_other_keys(name):
            self.untouched(0)
            with held(name) as now:
                yield now

        with patch.object(watch, "seat_held", side_effect=after_other_keys):
            self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.composer), ([], DRAFT))

    def test_text_the_line_is_ends_with_or_its_paste_fold_is_set_aside_never_sent(self):
        long = "run acme finished FAIL: " + "a finding in detail " * 50
        for own, line, row in ((LINE, LINE, None), ("Decide the next\n  step.", LINE, None),
                               ("Private notes. " * 60, long, "❯ [Pasted text #1]\n")):
            with self.subTest(own=own[:15]):
                self.show(own)
                if row:
                    self.pane = self.base.replace(self.empty, row)
                self.assertTrue(self.typed_line(line))
                self.assertEqual((self.sent[-1:], self.composer), ([line], own))

    def test_text_too_tall_to_read_goes_aside_and_text_its_editor_would_lose_stays(self):
        tall = "\n".join(f"pasted row {n} of a long paste" for n in range(1, 61))
        self.show(tall)
        self.assertIsNone(watch.composer_draft("claude", self.pane))
        self.assertTrue(self.typed_line())
        self.assertEqual((self.sent, self.composer), ([DOCS], tall))
        self.buffers.clear()
        # a harness whose editor sends a paste's placeholder alone, the paste gone
        loses = dict(watch.screen("claude"), editor_refuses=re.compile(r"\[Pastedtext#\d+"))
        with patch.object(watch, "screen", return_value=loses):
            for draft in ("[Pasted text #1 +39 lines]", tall):     # or nothing says it is not
                self.show(draft)
                self.assertFalse(self.typed_line())
        self.assertEqual((self.keys.count("C-g"), self.sent), (2, [DOCS]))

    def test_a_muse_draft_holding_a_paste_is_one_its_editor_would_lose(self):
        pane = (REPO / "tests/fixtures/muse-draft-pane.txt").read_text()
        for draft, loses in (("Fix the login redirect", False),
                             ("[Pasted Content 1190 chars]", True)):
            text = watch.composer_draft("muse", pane.replace("Fix the login redirect", draft))
            self.assertEqual(bool(watch.screen("muse")["editor_refuses"].search(text)), loses)

    def test_a_composer_the_editor_fails_to_write_keeps_its_text_and_takes_no_line(self):
        self.wait_line()
        with patch.object(aside_editor, "_publish", return_value=False):
            self.tick()
        self.assertEqual((self.composer, self.typed, self.sent, self.buffers, self.told()),
                         (DRAFT, [], [], {}, False))

    def test_a_composer_holding_nothing_takes_the_line_as_keys(self):
        self.show("")
        self.wait_line()
        self.tick()
        self.assertEqual((self.keys, self.typed, self.buffers, self.told()),
                         (["Enter"], [LINE], {}, True))

    def test_text_typed_lately_mid_turn_under_a_question_or_before_the_editor_stays(self):
        self.untouched(watch.DRAFT_STILL - 10)
        self.assertFalse(self.typed_line())
        self.untouched(watch.DRAFT_STILL)
        for pane in ("claude-draft-while-working-pane.txt", "claude-question-pane.txt",
                     "claude-dialog-pane.txt"):
            self.pane = (REPO / "tests/fixtures" / pane).read_text()
            self.assertFalse(self.typed_line())
        self.show(DRAFT)
        self.unread = True
        self.assertFalse(self.typed_line())
        self.unread, self.launched = False, False
        self.assertFalse(self.typed_line())
        self.assertEqual((self.keys, self.typed), ([], []))


if __name__ == "__main__":
    unittest.main()
