"""A feature's dot is blue under `you` and green under `everyone`, where it is on.

The owner's pick of 18 Oct 2026 for the features screen: two columns of dots, `you` in working's
blue and `everyone` in done's green, an off dot dim and the keys' cell reversed, so which
audience a feature is on for reads at a glance.  Offline: `menu.features_body` alone.
"""

from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal  # noqa: E402

ROWS = [{"id": "dark", "name": "dark mode", "you": True, "everyone": False},
        {"id": "beta", "name": "beta search", "you": True, "everyone": True},
        {"id": "plan", "name": "plans", "you": False, "everyone": False}]


def marks(line):
    """Each mark a line draws, in order, with the colour code just before it."""
    return re.findall(r"\x1b\[([0-9;]*)m ([●○]) ", line)


BLUE, GREEN = "38;2;137;180;250", "38;2;166;227;161"


class FeatureDots(unittest.TestCase):
    def draw(self, at=None, column=0):
        with patch.object(terminal, "colour_depth", return_value=24), \
                patch.object(terminal, "utf8", return_value=True), \
                patch.object(terminal, "layout_width", return_value=80):
            lines, _ = menu.features_body(ROWS, at=at, column=column)
        return [marks(line) for line in lines[1:]]

    def test_on_is_blue_for_you_and_green_for_everyone_and_off_is_dim(self):
        dark, beta, plans = self.draw()
        self.assertEqual(dark[0], (BLUE, "●"))
        self.assertEqual(beta, [(BLUE, "●"), (GREEN, "●")])
        self.assertEqual([mark for _, mark in dark[1:] + plans], ["○"] * 3)
        self.assertNotIn(BLUE, str(dark[1:] + plans))
        self.assertNotIn(GREEN, str(dark[1:] + plans))

    def test_the_keys_cell_is_reversed_whatever_its_colour(self):
        _, beta, _ = self.draw(at="beta", column=1)
        self.assertEqual(beta, [(BLUE, "●"), ("7", "●")])


if __name__ == "__main__":
    unittest.main()
