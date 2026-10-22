"""Every harness's editor keys, as its manifest names them, hand its composer to ak's editor, so
the owner's unsent text is set aside for ak's line and given back in every harness ak runs: a
seat sat with ak's line untyped while the owner's text held its composer, and the owner asked for
the fix in every harness and model (19 Oct 2026).  OpenCode 2.0.32 drops a ctrl+x typed alone
while it opens a new session, so its keys go in one write; Grok 1.0.46 opens the editor only from
its command palette, each key typed once the palette shows the one before it landed.  Offline:
fixtures.editor_seat, around the real agentkit/aside_editor.py, its clock and ak's the test's.
"""

import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.editor_seat import PANE, EditorSeat
from fixtures.seats import LINE, NOW, REPO
from agentkit import aside_editor, watch

DRAFT = "and add these posts"
# what Grok's command palette draws as each key lands (1.0.46)
PALETTE = {"C-p": "│   search: ", "edit prompt": "│   search: edit prompt   │"}


class EveryHarness(EditorSeat):
    def setUp(self):
        super().setUp()
        self.now, self.slow, self.menu, self.opens, self.opening = NOW, 0, "", True, False
        clock = Clock(self.wait)
        clock.time = lambda: self.now
        for target in (watch, aside_editor):
            patcher = patch.object(target, "time", clock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait(self, seconds):
        self.now += seconds

    def press(self, key, pane=PANE):
        self.wait(self.slow)                # each key lands, and what it opens draws, `slow` on
        self.menu = PALETTE.get(key, "") if self.opens else ""
        super().press(key, pane)

    def read(self, *args, **kwargs):
        return super().read(*args, **kwargs) + self.menu

    def tmux(self, *args, **kwargs):
        # opening a new session, it drops the first of its keys typed alone
        if self.opening and args[0] == "send-keys" and args[3:] == self.chord[:1]:
            return 0, ""
        return super().tmux(*args, **kwargs)

    def seat_of(self, harness):
        chrome = watch.screen(harness)
        self.chord, self.keys, self.buffers = chrome["editor"], [], {}
        self.show(DRAFT)
        return {"id": PANE, "tty": str(self.tty), "keys": self.chord, "shows": chrome["editor_shows"]}

    def aside_and_back(self, harness):
        where = self.seat_of(harness)
        self.assertEqual(watch._edit(self.seat, where, "line", LINE), "line")
        self.assertEqual(self.composer, LINE)
        self.show("")                       # its Enter sent the line
        self.assertEqual(watch._edit(self.seat, where, "back", LINE), "sent")
        given = aside_editor.pack(aside_editor.GIVEN, LINE.encode(), DRAFT.encode())
        self.assertEqual((self.composer, self.keys, self.buffers, self.ask, self.opened),
                         (DRAFT, [*self.chord] * 2, {aside_editor.kept(PANE): given}, None, []))

    def test_every_harness_s_keys_set_the_owners_text_aside_and_give_it_back(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            with self.subTest(manifest.stem):
                self.assertTrue(watch.screen(manifest.stem)["editor"])
                self.aside_and_back(manifest.stem)

    def test_a_harness_opening_a_new_session_takes_its_editor_keys_whole(self):
        self.opening = True
        self.aside_and_back("opencode")

    def test_a_palette_that_never_opens_gets_none_of_the_keys_meant_for_it(self):
        self.opens = False
        self.assertIsNone(watch._edit(self.seat, self.seat_of("grokbuild"), "line", LINE))
        # the rest would have gone into the owner's composer; no ask is left for their own edit
        self.assertEqual((self.keys, self.composer, self.ask, self.buffers),
                         (["C-p"], DRAFT, None, {}))

    def test_a_palette_slow_to_open_still_hands_the_composer_to_ak_s_editor(self):
        # each key and what it opens take most of a wait: ak's editor takes only an ask as fresh
        self.slow = watch.SENT_WAIT - 1
        self.assertGreater(self.slow * len(watch.screen("grokbuild")["editor"]), aside_editor.FRESH)
        self.aside_and_back("grokbuild")


if __name__ == "__main__":
    unittest.main()
