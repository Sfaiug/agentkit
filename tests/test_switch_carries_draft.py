"""Text the owner typed and had not sent goes on into the composer of the harness a switch opens.

The switch refused while a draft was up, even after the owner said yes.  Now ak's editor lifts
the composer whole into the pane's kept buffer, which a respawn keeps with the pane, and the next
tick hands it to the new harness byte for byte, once any line the new launch is owed has gone;
text it cannot keep refuses the switch, as the owner would lose it.  Offline: fixtures.editor_seat's seat;
`watch.carry_draft` before the respawn, the tick's `watch.drafts_back` after it.
"""

import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.sandbox import REPO
from agentkit import aside_editor, watch

DRAFT = "and add these posts\nto the list  \n\n"     # carried byte for byte


class SwitchCarriesDraft(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(0)               # the owner was typing into it a moment ago
        self.show(DRAFT)

    def switched(self, to="claude", harness="claude"):
        kept = watch.carry_draft(self.seat, harness, self.pane, to, self.cfg)
        if kept:
            self.show("")               # the respawned harness, its composer empty
        return kept

    def test_the_draft_goes_on_into_the_new_composer_after_any_line_it_is_owed(self):
        self.assertTrue(self.switched())
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): aside_editor.pack(
            aside_editor.ASIDE, b"", DRAFT.encode())})
        watch.seat_write(self.seat["name"], midturn={"line": watch.MIDTURN_LINE})
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, "")
        watch.seat_write(self.seat["name"], midturn=None)
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.sent, self.typed), (DRAFT, [], []))
        self.assertEqual(self.keys, ["C-g", "C-g"])     # once to lift, once to hand back

    def test_text_set_aside_for_ak_s_line_goes_on_though_the_line_was_never_sent(self):
        watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line", "ak notice")
        self.show(self.composer)                # ak's line, drawn
        self.assertTrue(self.switched())
        self.untouched(watch.DRAFT_STILL)       # as any text set aside for a line goes back
        watch.seat_write(self.seat["name"], midturn={"line": watch.MIDTURN_LINE})
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, "")     # never before the line the new launch is owed
        watch.seat_write(self.seat["name"], midturn=None)
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, DRAFT)

    def test_a_draft_taller_than_the_screen_goes_on_too(self):
        self.cfg["models"]["opus"]["harness"] = "codex"
        self.pane = (REPO / "tests/fixtures/codex-tall-line-pane.txt").read_text()
        self.assertIsNone(watch.composer_draft("codex", self.pane))    # its prompt row is above
        self.assertTrue(self.switched(harness="codex"))
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): aside_editor.pack(
            aside_editor.ASIDE, b"", DRAFT.encode())})

    def test_text_the_editor_cannot_keep_stays_in_the_composer(self):
        self.deaf = True                        # the key goes unanswered
        self.assertFalse(self.switched())
        self.deaf = False
        watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line", "ak notice")
        self.show("typed since")                # text set aside already, and more beside it
        self.assertFalse(self.switched())
        self.assertEqual((self.composer, self.sent), ("typed since", []))

    def test_a_paste_muse_took_after_the_switch_captured_its_pane_sends_no_key_and_refuses(self):
        self.on_muse()
        self.show("and add these posts")
        captured = self.pane            # read before the seat's lock, holding no paste
        self.show("and add these posts [Pasted Content 1190 chars]")
        self.assertFalse(watch.carry_draft(self.seat, "muse", captured, "muse", self.cfg))
        self.assertEqual((self.keys, self.buffers), ([], {}))

    def test_no_keys_go_to_a_question_or_for_a_harness_that_opens_no_editor_of_ak_s(self):
        with patch.object(watch, "asking", return_value=True):
            self.assertTrue(self.switched())
        self.show(DRAFT)
        self.assertTrue(self.switched(to="acme"))     # a harness with no manifest
        self.assertEqual((self.keys, self.buffers), ([], {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
