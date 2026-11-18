"""A release is started at the second ask in a row that finds it.

A registry names a release before all of it is there: a platform's package can come minutes after
the release does, and an install begun at once fails.  So the tick's ask that first finds a
release behind starts nothing and installs nothing, and the ask an hour later starts it; a newer
release found at that later ask is not started then, and is at the ask after.  Black-box, on the
fixtures of tests/test_key_tick_keeps_harnesses_current.py, and this test fails against
`/bin/false`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_tick_keeps_harnesses_current import ASK_EVERY, Harnesses, starts


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class StartedAtTheSecondAsk(Harnesses, unittest.TestCase):
    def first_found(self, release):
        """claude's channel moves to `release`, and the tick whose ask finds it starts no upgrade
        and installs nothing."""
        self.write(**{"claude.latest": release})
        said = self.tick()
        self.assertEqual([line for line in said if " is behind " in line], [])
        self.assertEqual(self.installs(), [])

    def test_the_ask_that_first_finds_a_release_only_records_it(self):
        self.first_found("2.2.0")
        self.passes(ASK_EVERY)
        self.assertIn(starts("claude", "2.1.0", "2.2.0"), self.tick())
        self.told("claude")
        self.assertEqual(self.installed("claude"), "2.2.0 (Claude Code)")
        self.assertEqual(self.asks()["claude"], 2)

    def test_a_newer_release_found_at_the_second_ask_is_started_at_the_third(self):
        self.first_found("2.2.0")
        self.passes(ASK_EVERY)
        self.first_found("2.3.0")
        self.passes(ASK_EVERY)
        self.assertIn(starts("claude", "2.1.0", "2.3.0"), self.tick())
        self.told("claude")
        self.assertEqual(self.installed("claude"), "2.3.0 (Claude Code)")
        self.assertEqual(self.asks()["claude"], 3)


if __name__ == "__main__":
    unittest.main()
