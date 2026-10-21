"""The quality and cost note on the models screen, highlighted, keeps its mark and its width:
the mark takes the note's first cell, not the first byte of its dim style, so the line reads
`› quality is 100 less how many points …` and runs no further than the screen, on a phone
as on a desk (tests/test_models_screen.py drives the screen).

Offline: a throwaway HOME with a matrix scored from rows written by hand, the keys fed in,
the terminal's colours on (the style is what the mark must not take).
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import terminal
from agentkit.terminal import Key
from test_models_screen import Screen


class NoteHighlighted(Screen):
    def test_the_note_highlighted_keeps_its_mark_and_its_width(self):
        # up from the first model to the note, on a desk and on a phone
        for width in (100, 40):
            with self.subTest(width=width), \
                    patch.object(terminal, "colour_depth", return_value=256):
                text = self.screens([Key("char", "r"), Key("up"), Key("esc"), Key("esc")],
                                    width=width)
                self.assertIn("› quality is 100 less how many points", text)
                self.assertNotIn("[2;", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
