"""A Claude permission prompt with the seat's rule drawn under it reads asking.

Claude Code 2.1.325 closes a tool's permission prompt with the seat's named rule when a background
agent asks after the turn's Stop.  Read with that rule as its newest line, the prompt fell through
to the composer, and the standing Stop on background work kept the seat `working`: on 15 Nov 2026
one sat at this prompt for 16 hours reading "turn running 16h", and nobody was asked.  The
fixture is that seat's bottom rows as drawn, attributes left out, its session's name invented.
"""
import unittest

from fixtures.sandbox import REPO
from agentkit import watch

PANE = watch.pane_tail(
    (REPO / "tests/fixtures/claude-permission-over-rule-pane.txt").read_text(encoding="utf-8"))
BACKGROUND = {"event": "Stop", "kind": "background", "at": 100.0}


class PermissionOverRule(unittest.TestCase):
    def test_the_screen_alone_reads_asking(self):
        self.assertEqual(watch.screen_state("claude", PANE)[:2], ("asking", "asking.permission"))

    def test_a_standing_stop_on_background_work_gives_way_to_it(self):
        found = watch.classify("claude", PANE, BACKGROUND, None, {}, 101.0)
        self.assertEqual((found["state"], found["authority"]), ("asking", "screen"))

    def test_only_a_rule_under_the_hint_is_looked_past(self):
        # transcript text under the hint makes it something said, not the prompt
        quoted = PANE.replace(PANE.splitlines()[-1], "⏺ Done.")
        self.assertNotEqual(watch.screen_state("claude", quoted)[0], "asking")


if __name__ == "__main__":
    unittest.main(verbosity=2)
