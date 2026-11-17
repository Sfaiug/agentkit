"""Every line of the why page (menu.models_why) fits a screen 14 cells wide or wider, the label
column and one cell of value: an other's lines after its first hang two cells further in only
where that leaves them a cell (menu.flowed).

In this process, an invented answer of one choice and an other it beats; judged by the cells of
each line at each width.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal


def model(name, quality, cost):
    return {"name": name, "quality": quality, "cost": cost, "points": None, "effort": "",
            "cost_rule": "board", "runs": 0, "se": 1, "measures": {}}


class WhyFitsItsWidth(unittest.TestCase):
    def test_no_line_is_wider_than_a_screen_of_14_cells_or_more(self):
        choice, other = model("Acme 1", 95.0, 1), model("Bolt 1", 90.0, 2)
        found = {"choices": [choice], "rated": [choice, other], "others": [other],
                 "whys": {id(other): ("beaten", choice)}, "cost_unit": "money"}
        for width in range(14, 41):
            with self.subTest(width=width), patch.object(terminal, "layout_width",
                                                         return_value=width):
                page = menu.models_why(found, "execute", choice, choice, "$ a task", [])
                # the other, its bar drawn: its lines hang
                self.assertIn("  shaded     ", [line[:13] for line in page])
                self.assertLessEqual(max(map(terminal.cells, page)), width, page)


if __name__ == "__main__":
    unittest.main()
