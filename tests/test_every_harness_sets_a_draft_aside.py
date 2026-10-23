"""Text the owner leaves unsent in a seat's composer holds ak's line back in no harness whose
manifest names the keys that hand its composer to ak's editor (`[screen] editor`): those keys set
the text aside for the line and give it back (19 Oct 2026).  Offline: fixtures.editor_seat's
seat, on each harness `config.manifests()` ships, its pane that harness's prompt capture.
"""

import unittest

from fixtures.editor_seat import EditorSeat
from fixtures.seats import REPO
from agentkit import config, watch

DRAFT = "and add these posts"
LINE = "ak notice"


class EveryHarness(EditorSeat):
    def on(self, harness):
        """The seat, its model on that harness, showing that harness's prompt holding DRAFT."""
        self.cfg["models"]["opus"]["harness"] = harness
        config.save(self.cfg)
        self.base = (REPO / f"tests/fixtures/{harness}-prompt-pane.txt").read_text(encoding="utf-8")
        self.keys, self.sent, self.buffers = [], [], {}
        self.show(DRAFT)
        return watch.screen(harness)["editor"]

    def passes(self, keys):
        """The line in through the editor in DRAFT's place, its Enter, and DRAFT given back."""
        where = watch.seat_editor(self.seat, self.cfg)
        self.assertEqual(watch._edit(self.seat, where, "line", LINE), "line")
        self.assertEqual(self.composer, LINE)
        self.press("Enter")
        self.assertEqual(watch._edit(self.seat, where, "back", LINE), "sent")
        self.assertEqual((self.keys, self.sent, self.composer),
                         ([*keys, "Enter", *keys], [LINE], DRAFT))

    def test_each_harness_naming_editor_keys_sets_the_owners_text_aside_and_gives_it_back(self):
        named = [harness for harness, _ in config.manifests() if watch.screen(harness)["editor"]]
        self.assertTrue(named)
        for harness in named:
            with self.subTest(harness=harness):
                self.passes(self.on(harness))

    def test_opencode_opening_a_new_session_still_takes_its_keys(self):
        keys = self.on("opencode")
        self.opening = True             # it drops a first key typed alone
        self.passes(keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
