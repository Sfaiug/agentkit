"""A Muse 1.4.7 seat reads as what it is doing, under its task tray and its grey suggestions.

1.4.7 draws a tray of background tasks under its composer, up to twelve rows below the spinner
that says a turn is running: read only eight rows up, a working seat read as idle and paged
`needs you`.  And it draws its rotating composer suggestions in a grey with no faint attribute:
read as typed, an idle seat read as holding the owner's unsent draft.
"""
import unittest

from fixtures.sandbox import REPO
from agentkit import watch

FIX = REPO / "tests/fixtures"


def pane(name):
    return (FIX / f"muse-{name}-pane.txt").read_text(encoding="utf-8")


class MuseTray(unittest.TestCase):

    def test_a_turn_running_under_a_full_tray_reads_working(self):
        state, rule, _ = watch.screen_state("muse", watch.pane_tail(pane("tray-working")))
        self.assertEqual((state, rule), ("working", "working.interrupt"))

    def test_a_grey_suggestion_is_an_empty_composer(self):
        for name in ("placeholder", "tray-placeholder"):
            with self.subTest(name):
                self.assertEqual(
                    watch.screen_state("muse", watch.pane_tail(pane(name)))[:2],
                    ("at_prompt", "prompt.suggestion"))
                self.assertEqual(watch.composer_draft("muse", pane(name)), "")

    def test_the_hint_in_the_transcript_over_a_tray_is_no_turn(self):
        # The tray is left out, not read past: ten rows up, above the spinner's window, is
        # transcript, where `esc to interrupt` is only words.
        for name, reading in (("tray-draft", ("draft", "prompt.draft")),
                              ("tray-placeholder", ("at_prompt", "prompt.suggestion"))):
            with self.subTest(name):
                quoted = pane(name).replace("Starting the background sleep task.",
                                            "Press esc to interrupt it.")
                self.assertEqual(watch.screen_state("muse", watch.pane_tail(quoted))[:2], reading)

    def test_typed_text_over_the_tray_is_still_a_draft(self):
        self.assertEqual(watch.screen_state("muse", watch.pane_tail(pane("tray-draft")))[:2],
                         ("draft", "prompt.draft"))
        self.assertEqual(watch.composer_draft("muse", pane("tray-draft")), "acmedraftwords")


if __name__ == "__main__":
    unittest.main(verbosity=2)
