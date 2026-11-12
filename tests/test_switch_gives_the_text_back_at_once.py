"""The owner's unsent text a switch lifts is back in the new harness's composer as soon as that
harness shows one empty, with no tick: whoever lifts it (`watch.carry_draft`) gives it back by the
tick's own rules (`watch.drafts_back`), in a process of its own (`watch.start_carried_back`), so
the switch returns as soon as it did and the popup it came from ends none of it by closing.
Offline: fixtures.editor_seat's seat, switched as tests/test_switch_carries_draft.py switches it
-- the text lifted and the harness respawned in one hold of the seat's lock -- and that process,
started for a seat no tmux of the test's holds.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fixtures.editor_seat import PANE, EditorSeat
from agentkit import aside_editor, notify, watch

DRAFT = "and add these posts\nto the list  \n\n"     # given back byte for byte


class SwitchGivesTheTextBackAtOnce(EditorSeat):
    def test_the_draft_is_back_once_the_new_harness_shows_its_composer_with_no_tick(self):
        self.untouched(0)                       # the owner was typing into it a moment ago
        self.show(DRAFT)
        with notify.session_lock(self.seat["name"]):
            self.assertTrue(watch.carry_draft(self.seat, "claude", self.pane, "claude", self.cfg))
            self.show("")
            self.pane = ""                      # the respawned harness, drawing nothing yet
            watch.time.sleep = lambda _seconds: self.show("")     # ... then its empty composer
        self.settle()
        self.assertEqual((self.composer, self.sent, self.typed), (DRAFT, [], []))
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): aside_editor.pack(
            aside_editor.GIVEN, b"", DRAFT.encode())})
        self.assertEqual(self.keys, ["C-g", "C-g"])     # once to lift, once to hand back


class TheHandBackIsAProcessOfItsOwn(unittest.TestCase):
    def test_it_starts_in_a_session_of_its_own_and_ends_where_the_seat_is_gone(self):
        with tempfile.TemporaryDirectory() as home, \
                patch.dict(os.environ, {"HOME": home, "TMUX_TMPDIR": home}):
            process = watch.start_carried_back("acme-docs")
            session = os.getsid(process.pid)
            self.assertEqual(process.wait(60), 0)
        self.assertNotEqual(session, os.getsid(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
