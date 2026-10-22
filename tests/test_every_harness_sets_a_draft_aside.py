"""Each harness's editor keys, as its manifest names them, hand its composer to ak's editor, so
the owner's unsent text is set aside for ak's line and given back, Muse and OpenCode as Claude
Code, Codex and Antigravity: a seat sat with ak's line untyped while the owner's text held its
composer, and the owner asked for the fix in every harness and model (19 Oct 2026).  Offline:
fixtures.editor_seat, around the real agentkit/aside_editor.py.
"""

import unittest

from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE
from agentkit import aside_editor, watch

DRAFT = "and add these posts"


class EveryHarness(EditorSeat):
    def test_each_harness_s_keys_set_the_owners_text_aside_and_give_it_back(self):
        for harness in ("claude", "codex", "muse", "antigravity", "opencode"):
            with self.subTest(harness):
                self.chord = watch.screen(harness)["editor"]
                where = {"id": PANE, "tty": str(self.tty), "keys": self.chord}
                self.keys, self.buffers = [], {}
                self.show(DRAFT)
                self.assertEqual(watch._edit(self.seat, where, "line", LINE), "line")
                self.assertEqual(self.composer, LINE)
                self.show("")               # its Enter sent the line
                self.assertEqual(watch._edit(self.seat, where, "back", LINE), "sent")
                given = aside_editor.pack(aside_editor.GIVEN, LINE.encode(), DRAFT.encode())
                self.assertEqual((self.composer, self.keys, self.buffers, self.ask, self.opened),
                                 (DRAFT, [*self.chord] * 2, {aside_editor.kept(PANE): given},
                                  None, []))


if __name__ == "__main__":
    unittest.main()
