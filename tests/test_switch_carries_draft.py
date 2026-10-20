"""Text the owner typed and had not sent goes on into the composer of the harness a switch opens.

The switch refused while a draft was up, even after the owner said yes.  Now it lifts the text
into the pane's kept buffer, which a respawn keeps with the pane, and the next tick hands it to
the new harness byte for byte, with any set aside for a line of ak's the switch ends: through
ak's editor, or as a paste where the new one opens none.  Offline:
fixtures.editor_seat's seat; `watch.carry_draft` before the respawn, the tick's
`watch.drafts_back` after it.
"""

import unittest

from fixtures.editor_seat import PANE, EditorSeat
from agentkit import aside_editor, watch

DRAFT = "and add these posts"


class SwitchCarriesDraft(EditorSeat):
    def setUp(self):
        super().setUp()
        self.untouched(0)               # the owner was typing into it a moment ago
        self.show(DRAFT)

    def switched(self):
        watch.carry_draft(self.seat, "claude", self.pane, self.cfg)
        self.show("")                   # the respawned harness, its composer empty

    def carried(self):
        return {aside_editor.kept(PANE): aside_editor.pack(aside_editor.ASIDE, b"", DRAFT.encode())}

    def test_the_draft_goes_on_into_the_new_composer_at_once_through_the_editor(self):
        self.switched()
        self.assertEqual(self.buffers, self.carried())
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.sent, self.typed), (DRAFT, [], []))
        watch.drafts_back(self.cfg)
        self.assertEqual(self.keys, ["C-g", "C-g"])     # once to lift, once to hand back

    def test_a_line_the_new_launch_is_owed_goes_first(self):
        self.switched()
        watch.seat_write(self.seat["name"], midturn={"line": watch.MIDTURN_LINE})
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, "")
        watch.seat_write(self.seat["name"], midturn=None)
        watch.drafts_back(self.cfg)
        self.assertEqual(self.composer, DRAFT)

    def test_a_harness_without_ak_s_editor_has_it_read_off_its_screen_and_pasted_back(self):
        self.launched = False
        self.switched()
        self.assertEqual(self.buffers, self.carried())
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.pasted, self.buffers, self.keys),
                         (DRAFT, [DRAFT], {}, []))

    def test_a_draft_lifted_through_the_editor_is_pasted_back_byte_for_byte(self):
        self.show("first line\nlast line  \n\n")
        self.switched()
        self.launched = False           # the new harness opens no editor of ak's
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.buffers), ("first line\nlast line  \n\n", {}))

    def test_a_draft_already_set_aside_for_ak_s_line_goes_on_too(self):
        watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line", "ak notice")
        self.show("ak notice")          # ak's line, not yet sent when the switch ends it
        self.switched()
        self.assertEqual(self.buffers, self.carried())
        self.launched = False
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.buffers), (DRAFT, {}))

    def test_text_typed_after_text_set_aside_follows_it_whole(self):
        watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line", "ak notice")
        self.show("and add  these posts\n\n")      # typed once ak's line was sent
        self.switched()
        self.launched = False
        watch.drafts_back(self.cfg)
        self.assertEqual((self.composer, self.buffers),
                         (f"{DRAFT}\nand add  these posts\n\n", {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
