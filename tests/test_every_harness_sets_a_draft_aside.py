"""Text the owner leaves unsent in a seat's composer holds ak's line back in no harness ak ships:
each manifest names the keys that hand its composer to ak's editor (`[screen] editor`), and those
keys set the text aside for the line and give it back (19 Oct 2026).  Grok 1.0.46 opens that
editor only from its command palette, each key typed once the palette shows what the key before
it drew (`[screen] editor_shows`).  Offline: fixtures.editor_seat's seat, on each harness
`config.manifests()` ships, its pane that harness's prompt capture or Grok's palette's, ak's clock
and its editor's the test's.
"""

import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.editor_seat import EditorSeat
from fixtures.seats import NOW, REPO
from agentkit import aside_editor, config, watch

DRAFT = "and add these posts"
LINE = "ak notice"
# what Grok's command palette draws over a draft as each key lands: 1.0.46, `capture-pane -p -e`
# at 120x40 on a private tmux socket and a throwaway HOME, kept whole, its path invented
PALETTE = {key: (REPO / f"tests/fixtures/grokbuild-{name}-pane.txt").read_text(encoding="utf-8")
           for key, name in (("C-p", "palette"), ("edit prompt", "palette-edit-prompt"))}


class EveryHarness(EditorSeat):
    def setUp(self):
        super().setUp()
        self.now, self.slow, self.menu, self.opens = NOW, 0, "", True
        clock = Clock(self.wait)
        clock.time = lambda: self.now
        for target in (watch, aside_editor):
            patcher = patch.object(target, "time", clock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait(self, seconds):
        self.now += seconds

    def press(self, key, pane=None):
        self.wait(self.slow)                # each key lands, and what it opens draws, `slow` on
        self.menu = PALETTE.get(key, "") if self.opens else ""
        super().press(key, *(pane,) if pane else ())

    def read(self, *args, **kwargs):
        return super().read(*args, **kwargs) if not self.menu else self.menu

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
        self.assertEqual((self.keys, self.sent, self.composer, self.ask),
                         ([*keys, "Enter", *keys], [LINE], DRAFT, None))

    def test_every_harness_ak_ships_sets_the_owners_text_aside_and_gives_it_back(self):
        for harness, _ in config.manifests():
            with self.subTest(harness=harness):
                keys = self.on(harness)
                self.assertTrue(keys)
                self.passes(keys)

    def test_opencode_opening_a_new_session_still_takes_its_keys(self):
        keys = self.on("opencode")
        self.opening = True             # it drops a first key typed alone
        self.passes(keys)

    def test_a_palette_that_never_opens_gets_none_of_the_keys_meant_for_it(self):
        self.on("grokbuild")
        self.opens = False
        # its transcript quoting the palette's search row is no palette
        self.base = f"{PALETTE['edit prompt'].splitlines()[6]}\n{self.base}"
        self.show(DRAFT)
        self.assertIsNone(watch._edit(self.seat, watch.seat_editor(self.seat, self.cfg), "line",
                                      LINE))
        # the rest would have gone into the owner's composer; no ask is left for their own edit
        self.assertEqual((self.keys, self.composer, self.ask, self.buffers),
                         (["C-p"], DRAFT, None, {}))

    def test_a_palette_slow_to_open_still_hands_the_composer_to_ak_s_editor(self):
        # each key and what it draws take most of a wait, longer in all than ak's editor takes
        # an ask as fresh
        keys = self.on("grokbuild")
        self.slow = watch.SENT_WAIT - watch.SENT_POLL
        self.assertGreater(self.slow * len(keys), aside_editor.FRESH)
        self.passes(keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
