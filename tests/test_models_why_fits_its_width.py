"""Every line of the why page (menu.models_why) fits a screen 13 cells wide or wider: the label
column and one cell of value, or, where that leaves none, each value folded under its label two
cells in; an other's lines after its first hang two cells further in only where that leaves them
a cell (menu.flowed).

In this process, an invented answer of one choice and an other it beats; judged by the cells of
each line at each width.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal


def model(name, quality, cost, effort):
    return {"name": name, "quality": quality, "cost": cost, "points": None, "effort": effort,
            "cost_rule": "board", "runs": 0, "se": 1, "measures": {}}


class WhyFitsItsWidth(unittest.TestCase):
    def test_no_line_is_wider_than_a_screen_of_13_cells_or_more(self):
        # each role's verb, with and without an effort beside the name in the heading
        for role, effort, width in [(role, effort, width) for role in menu.DOES
                                    for effort in ("", "medium") for width in range(13, 41)]:
            choice, other = model("Acme 1", 95.0, 1, effort), model("Bolt 1", 90.0, 2, effort)
            found = {"choices": [choice], "rated": [choice, other], "others": [other],
                     "whys": {id(other): ("beaten", choice)}, "cost_unit": "money"}
            with self.subTest(role=role, effort=effort, width=width), patch.object(
                    terminal, "layout_width", return_value=width):
                page = menu.models_why(found, role, choice, choice, "$ a task", [])
                # the other, its bar drawn: its lines hang, beside its label or under it
                self.assertIn("  shaded", [line[:8] for line in page])
                self.assertLessEqual(max(map(terminal.cells, page)), width, page)


if __name__ == "__main__":
    unittest.main()
