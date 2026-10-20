"""Text the owner left standing in a seat is set aside by ak's editor, ak's line goes in as keys
like any other, and the text comes back once the composer reads empty, each step taken on the
screen's word alone (19 Oct 2026).  Offline: fixtures.editor_seat, unread input and the clock
the test's to set; the tick is its set-aside pass, then its wait pass.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.editor_seat import EditorSeat
from fixtures.seats import LINE, NOW, REPO, SEAT
from agentkit import aside_editor, config, orch, watch

DRAFT = "and add these posts"
DOCS = "The docs finished."


class DraftSetAside(EditorSeat):
    def setUp(self):
        super().setUp()
        self.unread, self.now = False, NOW
        watch.time.time = self.clock     # the fixture's clock, moving: a mark's `at` is a moment
        patcher = patch.object(watch, "pane_unread", side_effect=lambda _session: self.unread)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.untouched(watch.DRAFT_STILL)
        self.show(DRAFT)

    def clock(self):
        self.now += 0.01
        return self.now

    def untouched(self, seconds):
        os.utime(self.tty, (NOW - seconds, NOW - seconds))

    def tick(self):
        watch.drafts_back(self.cfg, lambda _: None)
        super().tick()

    def test_text_left_standing_is_set_aside_for_the_line_and_comes_back(self):
        self.wait_line()
        self.deaf = True
        self.tick()
        # an edit never shown done leaves no ask for the owner's own Ctrl-G, nor a receipt
        self.assertEqual((self.composer, self.ask, self.receipts(), self.told()),
                         (DRAFT, None, [], False))
        self.deaf = False
        self.tick()
        self.tick()
        self.assertEqual((self.keys, self.typed, self.sent, self.composer, self.buffers),
                         (["C-g", "C-g", "Enter", "C-g"], [LINE], [LINE], DRAFT, {}))
        self.assertTrue(self.told())

    def test_text_the_line_ends_with_or_its_paste_fold_is_set_aside_never_sent(self):
        long = "run acme finished FAIL: " + "a finding in detail " * 50
        # text ending the way this line or the one sent before does, or a paste fold: the owner's
        for own, line, row in (("Decide the next\n  step.", LINE, None),
                               ("Decide the next\n  step.", DOCS, None),
                               ("Private notes. " * 60, long, "❯ [Pasted text #1]\n"),
                               ("Private notes. " * 60, DOCS, "❯ [Pasted text #1]\n")):
            with self.subTest(own=own[:15]):
                self.show(own)
                if row:
                    self.pane = self.base.replace(self.empty, row)
                self.assertTrue(watch.type_at_prompt(self.seat, line, lambda _: None,
                                                     cfg=self.cfg))
                watch.drafts_back(self.cfg, lambda _: None)
                self.assertEqual((self.sent[-1:], self.composer, self.buffers), ([line], own, {}))

    def test_a_line_sent_before_is_never_the_text_where_no_prompt_hook_marks_it_sent(self):
        # Muse's screen, and Antigravity's, whose footer drops its key hint over text typed
        for model, name, mark, hint in (("spark", "muse", "❯", None),
                                        ("gemini", "antigravity", ">", "? for shortcuts")):
            with self.subTest(harness=name):
                config.save_session(self.cfg, SEAT, model, ["astra"],
                                    {"cwd": str(self.root), "conversation": "thread"})
                base = (REPO / f"tests/fixtures/{name}-prompt-pane.txt").read_text()

                def show(text, base=base, mark=mark, hint=hint):
                    self.composer, self.free = text, not text
                    self.pane = base.replace(f"{mark}\n", f"{mark} {text}\n") if text else base
                    if text and hint:
                        self.pane = self.pane.replace(hint, " " * len(hint))

                self.show = show
                show("")
                self.assertTrue(watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg))
                show("Decide the next\n  step.")       # ends the way that line does
                self.assertTrue(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg))
                self.assertEqual((self.sent[-2:], self.composer), ([LINE, DOCS], ""))

    def test_text_comes_back_past_a_failed_enter_an_ignored_key_and_unread_input(self):
        self.wait_line()
        with patch.object(watch, "_send_enter", return_value=False):
            self.tick()                 # the line's Enter fails: it stands in the composer
        # a line of ak's whose Enter is owed is never set aside as the owner's text
        self.assertFalse(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg))
        self.assertEqual((self.composer, list(self.buffers.values())), (LINE, [DRAFT.encode()]))
        self.deaf = True
        self.tick()                     # its Enter, from its mark
        self.tick()                     # the editor never opens to bring the text back
        self.deaf, self.unread = False, True
        self.tick()                     # input the seat has not read yet
        self.assertEqual((self.sent, self.composer, self.ask, self.told()),
                         ([LINE], "", None, True))
        self.unread = False
        self.tick()
        self.assertEqual((self.sent, self.composer, self.buffers), ([LINE], DRAFT, {}))

    def test_text_kept_waits_for_an_empty_composer_and_its_way_back_takes_no_line(self):
        press, tmux = self.press, orch.tmux_out.side_effect

        def drawn_late(key):
            press(key)
            self.late = -1              # past SENT_WAIT: drawn when this test says

        def unreadable(*args, **kwargs):
            return (1, "server timed out") if args[0] == "save-buffer" else tmux(*args, **kwargs)

        with patch.object(self, "press", side_effect=drawn_late):
            self.assertFalse(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg))
            watch.drafts_back(self.cfg, lambda _: None)     # the text still drawn: still kept
            self.assertEqual(list(self.buffers.values()), [DRAFT.encode()])
            self.show(self.handed)
            watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.composer, self.buffers), ("", {}))
        # on its way back, the text would be drawn over a line typed now
        with patch.object(orch, "tmux_out", side_effect=unreadable):
            self.assertFalse(watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg))
        self.show(self.handed)
        self.assertTrue(watch.type_at_prompt(self.seat, DOCS, lambda _: None, cfg=self.cfg))
        watch.drafts_back(self.cfg, lambda _: None)
        self.assertEqual((self.typed, self.sent, self.composer, self.buffers),
                         ([DOCS], [DOCS], DRAFT, {}))

    def test_text_back_before_a_line_s_delivery_was_read_is_never_sent_for_it(self):
        own = "Decide the next\n  step."      # ends the way the line does
        self.show(own)
        self.wait_line()
        enter = self.press

        def unread_after(key):
            enter(key)
            self.unread = self.unread or key == "Enter"

        with patch.object(self, "press", side_effect=unread_after):
            self.tick()                 # sent, its delivery not read yet: unread input
        self.unread = False
        put = watch._seat_put

        def disk_full(name, data, fields):
            if "emptied" in fields:
                raise OSError(28, "No space left on device")
            return put(name, data, fields)

        with patch.object(watch, "_seat_put", side_effect=disk_full):
            watch.drafts_back(self.cfg, lambda _: None)     # that read unkept: the text stays
        self.assertEqual((self.composer, list(self.buffers.values())), ("", [own.encode()]))
        self.tick()                     # the text back first, then the line's mark
        self.tick()
        self.assertEqual((self.sent, self.composer, self.keys.count("Enter"), self.told()),
                         ([LINE], own, 1, True))

    def test_a_composer_the_editor_fails_to_write_keeps_its_text_and_takes_no_line(self):
        self.wait_line()
        with patch.object(aside_editor, "_publish", return_value=False):
            self.tick()
        self.assertEqual((self.composer, self.typed, self.buffers, self.told()),
                         (DRAFT, [], {}, False))

    def test_a_composer_holding_nothing_takes_the_line_as_keys(self):
        self.show("")
        self.wait_line()
        self.tick()
        self.assertEqual((self.keys, self.typed, self.buffers, self.told()),
                         (["Enter"], [LINE], {}, True))

    def test_text_typed_lately_mid_turn_under_a_question_or_before_the_editor_stays(self):
        def typed():
            return watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)

        self.untouched(watch.DRAFT_STILL - 10)
        self.assertFalse(typed())
        self.untouched(watch.DRAFT_STILL)
        for pane in ("claude-draft-while-working-pane.txt", "claude-question-pane.txt",
                     "claude-dialog-pane.txt"):
            self.pane = (REPO / "tests/fixtures" / pane).read_text()
            self.assertFalse(typed())
        self.show(DRAFT)
        self.launched = False
        self.assertFalse(typed())
        self.assertEqual((self.keys, self.typed), ([], []))


if __name__ == "__main__":
    unittest.main()
