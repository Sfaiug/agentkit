"""Lines ak typed that a harness drew late, joined in one composer, are still ak's and get sent.

On 22 Oct a seat drew a run's hand-back line only after the next line ak typed there: neither
mark's pass found its own line alone, so neither pressed Enter, and the row showed the joined
text as the owner's unsent words for 16 hours.  fixtures.seats' throwaway seat, its pane and
tmux faked: no tmux server or real harness.
"""

import unittest

from fixtures.seats import SEAT, Seats
from agentkit import watch

FIRST = "run 20261022-1750-acme-parser ended PASS, merged. Decide the next step."
SECOND = "run 20261022-1740-acme-docs ended PASS, merged; your wait is over."
OWNER = "and also look at the login page"


class HeldLineIsSent(Seats):
    def setUp(self):
        super().setUp()
        self.undrawn = []

    def tmux(self, *args, **kwargs):
        """The harness takes keys at once and draws them late, when `draw` says."""
        if args[0] == "send-keys" and "-l" in args:
            self.typed.append(args[-1])
            self.undrawn.append(args[-1])
            return 0, ""
        if args[0] == "send-keys":
            self.keys.append(args[-1])
        return super().tmux(*args, **kwargs)

    def draw(self, *texts):
        self.pane = self.base.replace(self.empty, "❯ " + "".join(texts) + "\n")
        self.undrawn.clear()

    def type(self, line, **kwargs):
        return watch.type_at_prompt(self.seat, line, lambda _: None, cfg=self.cfg, **kwargs)

    def unsent(self):
        found = watch.live_state(self.seat, "claude", pane=self.pane, cfg=self.cfg)
        return watch.unsent(SEAT, "claude", found, self.seat, self.cfg)

    def test_two_lines_drawn_joined_get_one_enter_and_both_read_delivered(self):
        self.keys, marks = [], []
        self.assertFalse(self.type(FIRST, receipt=marks.append))
        self.assertEqual(self.keys, [], "the first line's Enter waits: its composer reads empty")
        self.assertEqual(self.unsent(), "")
        self.assertFalse(self.type(SECOND, receipt=marks.append))
        self.assertEqual(self.typed, [FIRST, SECOND])
        self.assertEqual(self.keys, [])
        self.draw(*self.undrawn)
        self.assertEqual(watch.live_state(self.seat, "claude", pane=self.pane,
                                          cfg=self.cfg)["state"], "draft")
        self.assertEqual(self.unsent(), "")
        self.assertFalse(self.type(FIRST, typed=marks[0]))
        self.assertEqual(self.keys, ["Enter"])
        self.assertEqual(self.pane, self.base)
        self.assertEqual(self.unsent(), "")
        self.assertTrue(self.type(SECOND, typed=marks[1]))
        self.assertTrue(self.type(FIRST, typed=marks[0]))
        self.assertEqual(self.keys, ["Enter"])
        self.assertEqual(self.typed, [FIRST, SECOND])

    def test_owner_text_joined_to_aks_line_is_neither_sent_nor_hidden(self):
        for texts in ((FIRST, OWNER), (OWNER, FIRST), (FIRST, OWNER, SECOND)):
            with self.subTest(texts=[text[:12] for text in texts]):
                self.pane, self.keys, marks = self.base, [], []
                self.assertFalse(self.type(FIRST, receipt=marks.append))
                if SECOND in texts:
                    self.assertFalse(self.type(SECOND, receipt=marks.append))
                self.draw(*texts)
                for mark in marks:
                    self.assertFalse(self.type(mark["line"], typed=mark))
                self.assertEqual(self.keys, [])
                shown = self.unsent()
                self.assertTrue(shown and " ".join("".join(texts).split()).startswith(shown))

    def test_owner_text_above_a_cropped_composer_keeps_aks_lines_back(self):
        parts = [f"acme notice segment {at:02d}." for at in range(13)]
        first, second = "".join(parts[:6]), "".join(parts[6:])
        self.keys, marks = [], []
        for line in (first, second):
            self.assertFalse(self.type(line, receipt=marks.append))
        self.pane = self.base.replace(self.empty, "❯ " + OWNER + "\n" + "\n".join(parts) + "\n")
        self.assertFalse(self.type(first, typed=marks[0]))
        self.assertEqual(self.keys, [])

    def test_owner_drafts_ak_only_matches_in_part_still_show_unsent(self):
        for earlier, draft in ((watch.ACCOUNT_LINE, "Continue that turn and finish it;\n  do not "
                                                    "start over."),
                               ("acme result " * 90, "[Pasted text #2]")):
            with self.subTest(draft=draft[:12]):
                self.pane, self.keys = self.base, []
                self.assertFalse(self.type(earlier))
                self.draw(draft)
                self.assertEqual(self.unsent(), " ".join(draft.split()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
