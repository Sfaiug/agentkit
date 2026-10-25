"""The models screen (tests/test_models_screen.py) reads the public boards as it opens
(matrix.refresh): the rows stored stand while they are read, the rule under the header gliding
(motion.fetching), and the rows scored anew show once the reading lands, no key pressed; a
reading or a board that failed is said under the rows, the stored ones standing.

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
        self.assertIn(f"Claude Code › ■ {self.opus} claude-opus-5-5 ↑↓ move", standing[0])
        gliding.assert_called()
        self.assertIn(f"Claude Code › ■ {self.opus} claude-opus-5-5 □ Sonnet 5.5 claude-sonnet-5-5", text)

    def test_a_reading_that_lands_is_drawn_with_no_key_pressed(self):
        # in flight on a screen nothing animates, or landed while the screen was laid out
        for lands_in_layout in (False, True):
            with self.subTest(lands_in_layout=lands_in_layout):
                self.store(matrix.stored()["rows"][:1])
                gate, reads = threading.Event(), []

                def refresh(cfg, **_kw):
                    gate.wait(10)
                    self.store(self.scored)
                    return {}, self.scored

                class Read(READ):
                    def __init__(self, work):
                        reads.append(self)
                        super().__init__(work)

                def land():
                    gate.set()
                    reads[-1].join(10)

                body = menu.models_body

                def laid_out(*args, **kwargs):
                    if lands_in_layout and reads:
                        land()
                    return body(*args, **kwargs)
                pressed = iter([Key("char", "r"), Key("esc"), Key("esc")])

                def read_key(timeout=None, wake=None):
                    if timeout is None:     # a wait for a key alone: the next is pressed
                        return next(pressed)
                    if reads:
                        land()
                    return None
                with patch.object(matrix, "refresh", side_effect=refresh), \
                        patch.object(menu, "Fetch", Read), \
                        patch.object(menu, "models_body", side_effect=laid_out), \
                        patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                                     wake=None: terminal.read_key(timeout, wake)):
                    text = self.screens(read_key)
                self.assertIn(f"Claude Code › ■ {self.opus} claude-opus-5-5 □ Sonnet 5.5 claude-sonnet-5-5", text)

    def test_a_board_that_failed_is_said_and_the_stored_rows_stand(self):
        boards = {"artificialanalysis.ai": {"error": "HTTP Error 503: Service Unavailable"},
                  "arena.ai": {"error": None}}
        with patch.object(matrix, "refresh", side_effect=lambda cfg, **_kw: (
                boards, matrix.stored()["rows"])):
            text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn(f"orch {self.opus} @ xhigh 100", text)
        self.assertIn("the boards were not read: artificialanalysis.ai HTTP Error 503: Service "
                      "Unavailable", text)

    def test_a_reading_that_failed_is_said_and_the_stored_rows_stand(self):
        # one with no message is said by its kind
        for fault, said in ((OSError("artificialanalysis.ai\nanswered 503"),
                             "artificialanalysis.ai answered 503"), (TimeoutError(), "TimeoutError")):
            with self.subTest(said=said), patch.object(matrix, "refresh", side_effect=fault):
                text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
            self.assertIn(f"orch {self.opus} @ xhigh 100", text)
            self.assertIn(f"the boards were not read: {said}", text)


if __name__ == "__main__":
    unittest.main()
