"""Text the owner typed and had not sent goes on into the composer of the harness a switch opens.

The switch refused while a draft was up, even after the owner said yes.  Now ak's editor lifts
the composer whole into the pane's kept buffer, which a respawn keeps with the pane, and it goes
back to the new harness byte for byte, once any line the new launch is owed has gone -- by the
tick's `watch.drafts_back` where it could not go back at once; text it cannot keep refuses the
switch, as the owner would lose it.  Offline: fixtures.editor_seat's seat; `watch.carry_draft`,
the respawn and the line marked in one hold of the seat's lock, as `orch.switch_orchestrator`
holds it.
"""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.sandbox import REPO
from agentkit import aside_editor, config, notify, watch

DRAFT = "and add these posts\nto the list  \n\n"     # carried byte for byte


class SwitchCarriesDraft(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(0)               # the owner was typing into it a moment ago
        self.show(DRAFT)

    @contextmanager
    def switching(self, to="claude", harness="claude"):
        """A switch, yielding whether it kept the text, inside its hold of the seat's lock; what
        it started behind has ended once it is over."""
        with notify.session_lock(self.seat["name"]):
            kept = watch.carry_draft(self.seat, harness, self.pane, to, self.cfg)
            if kept:
                self.show("")           # the respawned harness, its composer empty
            yield kept
        self.settle()

    def switched(self, to="claude", harness="claude"):
        with self.switching(to, harness) as kept:
            return kept

    def owed(self):
        """The new launch owed a line (`watch.relaunched`)."""
        watch.seat_write(self.seat["name"], midturn={"line": watch.MIDTURN_LINE})

    def test_the_draft_goes_on_into_the_new_composer_after_any_line_it_is_owed(self):
        with self.switching() as kept:
            self.assertTrue(kept)
            self.assertEqual(self.buffers, {aside_editor.kept(PANE): aside_editor.pack(
                aside_editor.ASIDE, b"", DRAFT.encode())})
            self.owed()
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, "")
        watch.seat_write(self.seat["name"], midturn=None)
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.sent, self.typed), (DRAFT, [], []))
        self.assertEqual(self.keys, ["C-g", "C-g"])     # once to lift, once to hand back

    def test_text_set_aside_for_ak_s_line_goes_on_though_the_line_was_never_sent(self):
        watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line", "ak notice")
        self.show(self.composer)                # ak's line, drawn
        with self.switching() as kept:
            self.assertTrue(kept)
            self.owed()
        self.untouched(watch.DRAFT_STILL)       # as any text set aside for a line goes back
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, "")     # never before the line the new launch is owed
        watch.seat_write(self.seat["name"], midturn=None)
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, DRAFT)

    def test_a_draft_taller_than_the_screen_goes_on_too(self):
        self.cfg["models"]["opus"]["harness"] = "codex"
        self.pane = (REPO / "tests/fixtures/codex-tall-line-pane.txt").read_text()
        self.assertIsNone(watch.composer_draft("codex", self.pane))    # its prompt row is above
        with self.switching(harness="codex") as kept:
            self.assertTrue(kept)
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
        captured = self.pane            # read before the seat's lock, its composer empty
        self.show("and add these posts [Pasted Content 1190 chars]")
        self.assertFalse(watch.carry_draft(self.seat, "muse", captured, "muse", self.cfg))
        self.assertEqual((self.keys, self.buffers), ([], {}))

    def test_a_picker_opened_or_input_unread_after_the_capture_sends_no_key_and_refuses(self):
        for harness, picker in (("muse", True), ("codex", True), ("muse", False)):
            with self.subTest(harness=harness, picker=picker):
                self.cfg["models"]["opus"]["harness"] = harness
                config.save(self.cfg)
                self.base = (REPO / f"tests/fixtures/{harness}-draft-pane.txt").read_text()
                self.show(DRAFT)
                captured = self.pane
                if picker:              # Muse draws its composer empty above the picker
                    self.pane = (REPO / f"tests/fixtures/{harness}-model-picker-pane.txt").read_text()
                self.unread = not picker
                self.assertFalse(watch.carry_draft(self.seat, harness, captured, harness, self.cfg))
                self.assertEqual((self.keys, self.buffers), ([], {}))

    def test_no_keys_go_to_a_question_or_for_a_harness_that_opens_no_editor_of_ak_s(self):
        with patch.object(watch, "asking", return_value=True):
            self.assertFalse(self.switched())   # the text stays with the harness asking
            self.show("")
            self.assertTrue(self.switched())    # a composer read empty under it keeps nothing
        self.show(DRAFT)
        self.assertFalse(self.switched(to="acme"))    # a harness with no manifest: refused
        self.assertEqual((self.keys, self.buffers), ([], {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
