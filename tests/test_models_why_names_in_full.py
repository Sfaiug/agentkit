"""The why page (menu.models_why) names each release in full at any width: releases of one name
differ only at its end, so a name goes on at its words, never cut, and a word too long for its
line splits there with nothing put between its pieces.  A name and its effort are each made
plain on their own (menu.named), on the why page and the models screen: an escape one leaves
open takes nothing of the other, and a line break in either breaks no line.

In this process, invented answers of a choice, the best and others it beats; judged by where
each name appears on the page, a line's break allowed where the name has a space or inside a
word, nothing else between its characters.
"""

from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal


def model(name, quality, cost):
    return {"name": name, "quality": quality, "cost": cost, "points": None, "effort": "high",
            "cost_rule": "board", "runs": 0, "se": 1, "measures": {}}


def why(names, width):
    """The page of the first of `names` beside the best, the last, each between beaten by it."""
    rows = [model(name, 80 + n, 1 + n) for n, name in enumerate(names)]
    best = rows[-1]
    found = {"choices": [rows[0], best], "best": best, "others": rows[1:-1], "cost_unit": "money",
             "whys": {id(other): ("beaten", best) for other in rows[1:-1]}}
    with patch.object(terminal, "layout_width", return_value=width):
        return menu.models_why(found, "orchestrate", rows[0], rows[0], "$ a task", [], None)


def times(name, page):
    text = "\n".join(line.strip() for line in page)
    return len(re.findall("\n?".join(r"\s" if c == " " else re.escape(c) for c in name), text))


class WhyNamesInFull(unittest.TestCase):
    def test_each_release_is_named_whole_at_each_width(self):
        # the choice in the heading, each other once, the best below the choice and beating each
        for name, width in [("Acme Atlas Model Preview Edition 2026.{}", 40),
                            ("Acme Atlas.Preview.Edition.2026.{}", 40),
                            ("Acme Atlas.Preview.Edition.2026.{}", 22)]:
            names = [name.format(version) for version in (11, 12, 13, 14)]
            with self.subTest(name=name, width=width):
                page = why(names, width)
                self.assertEqual([times(one, page) for one in names], [1, 1, 1, 3], page)
                self.assertLessEqual(max(map(terminal.cells, page)), width, page)

    def test_an_escape_a_name_leaves_open_keeps_its_effort(self):
        page = why([f"Acme {n}\033[" for n in (1, 2, 3)], 40)
        self.assertEqual([times(f"Acme {n}[ high", page) for n in (1, 2, 3)], [1, 1, 2], page)

    def test_a_line_break_in_an_effort_breaks_no_row_of_the_models_screen(self):
        row = dict(model("Acme 1", 90.0, 1), effort="high\nlow")
        with patch.object(terminal, "layout_width", return_value=80):
            body, _ = menu.models_body([("execute", row, ("90.0", "$1.00"))], "$ a task")
        self.assertIn("  executor  Acme 1 high low  ", body[1])
        self.assertEqual([line for line in body if "\n" in line], [], body)


if __name__ == "__main__":
    unittest.main()
