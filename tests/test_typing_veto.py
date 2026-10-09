"""No line of ak's goes onto a screen the capture under the typing lock did not see empty.

The prompt is read once before the lock and once more inside it, off one capture, right
before the first key: a draft the owner started meanwhile, a dialog that came up, or a
screen whose composer cannot be read gets no key at all, and the line waits for the next
pass.  Driven through the wait line the tick types (`watch.wait_over`, `fixtures.seats`),
the same path every hand-back takes.  Offline.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.seats import Seats
from agentkit import orch, watch

DIALOG = (REPO / "tests/fixtures/claude-dialog-pane.txt").read_text(encoding="utf-8")


class TypingVeto(Seats):
    def setUp(self):
        super().setUp()
        self.keys = []
        tmux = self.tmux

        def spy(*args, **kwargs):
            if args[0] == "send-keys":
                self.keys.append(args)
            return tmux(*args, **kwargs)

        self.stack = patch.object(orch, "tmux_out", side_effect=spy)
        self.stack.start()
        self.addCleanup(self.stack.stop)

    def composed(self, text):
        """The seat's pane with that text in its composer."""
        return self.base.replace(self.empty, "❯ " + text + "\n")

    def changed_after_the_first_read(self, later):
        """The pane changes to `later` between the first read and the capture under the typing
        lock: the lock is taken, and the screen is already something else."""
        real = watch.seat_held

        @contextmanager
        def taken_then_changed(name):
            with real(name) as held:
                self.pane = later
                yield held

        return patch.object(watch, "seat_held", side_effect=taken_then_changed)

    def test_a_draft_the_owner_starts_after_the_first_read_is_never_typed_onto(self):
        self.wait_line()
        draft = "Fix the login redirect and run its tests again " * 3
        with self.changed_after_the_first_read(self.composed(draft)):
            self.tick()
        self.assertEqual((self.typed, self.keys), ([], []))
        self.assertFalse(self.told())
        self.assertIn(draft[:40], self.pane)              # the owner's words, untouched

    def test_no_key_goes_onto_a_screen_the_first_read_did_not_see(self):
        for later in (DIALOG, "  Loading the workspace…\n"):
            with self.subTest(later=later[:20]):
                self.setUp()
                self.wait_line()
                with self.changed_after_the_first_read(later):
                    self.tick()
                self.assertEqual((self.typed, self.keys), ([], []))
                self.assertFalse(self.told())
        # ... and the line goes in on the next pass, once the screen is its empty prompt again
        self.pane = self.base
        self.tick()
        self.assertTrue(self.told())


if __name__ == "__main__":
    unittest.main(verbosity=2)
