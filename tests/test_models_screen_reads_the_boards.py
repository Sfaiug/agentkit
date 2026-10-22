"""The models screen (tests/test_models_screen.py) reads the public boards as it opens
(matrix.refresh), not the tick: the rows stored stand while they are read, the rule under the
header gliding (motion.fetching), and the rows scored anew show once the reading lands; a
reading that failed is said under the rows, the stored ones standing.

Offline, on test_models_screen's fixture: a throwaway HOME, rows written by hand, the reading
of the boards faked, the keys fed in.
"""

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import matrix, menu, motion, terminal
from agentkit.terminal import Key
import test_models_screen as screen

READ = menu.Fetch           # the screen's own reading, off the drawing thread


class ReadsTheBoards(screen.Screen):
    def setUp(self):
        super().setUp()
        self.store([screen.row("claude", "claude-opus-5-5", "xhigh", 100, 100, 100, cost=8)])
        self.scored = [*matrix.stored()["rows"],
                       screen.row("claude", "claude-sonnet-5-5", "max", 67.86, 84.52, 84.77, cost=7)]

    def test_the_stored_rows_stand_while_the_boards_are_read_and_the_new_ones_follow(self):
        asked, reads, standing = threading.Event(), [], []

        def refresh(cfg, **_kw):          # the boards answer once the stored rows were drawn
            asked.wait(10)
            self.store(self.scored)
            return {}, self.scored

        class Read(READ):
            def __init__(self, work):
                reads.append(self)
                super().__init__(work)

        pressed = iter([Key("char", "r"), Key("esc"), Key("esc")])

        def read_key(timeout=None, wake=None):
            if reads and reads[-1].is_alive():          # drawn while the boards are read
                standing.append(" ".join(terminal.plain(sys.stdout.getvalue(), spaced=True).split()))
                asked.set()
                reads[-1].join(10)
                return None
            return next(pressed)
        with patch.object(matrix, "refresh", side_effect=refresh), \
                patch.object(menu, "Fetch", Read), \
                patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                             wake=None: terminal.read_key(timeout, wake)), \
                patch.object(motion, "fetching", wraps=motion.fetching) as gliding:
            text = self.screens(read_key)
        self.assertEqual(len(standing), 1, "the screen drew nothing while the boards were read")
        self.assertIn(f"› {self.opus} claude ‹ xhigh › 100 100 100 8.00", standing[0])
        self.assertNotIn("claude-sonnet-5-5", standing[0])
        gliding.assert_called()
        self.assertIn("claude-sonnet-5-5 claude max 68 85 85 7.00", text)

    def test_a_reading_that_failed_is_said_and_the_stored_rows_stand(self):
        with patch.object(matrix, "refresh", side_effect=OSError("artificialanalysis.ai\n"
                                                                 "answered 503")):
            text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn(f"› {self.opus} claude ‹ xhigh › 100 100 100 8.00", text)
        self.assertIn("the boards were not read: artificialanalysis.ai answered 503", text)


if __name__ == "__main__":
    unittest.main()
