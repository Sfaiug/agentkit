"""The models screen marks the pick, and what `r` takes where that is another row, in a column
before the name: `★ pick` and `r takes` on their rows, no words under the pick naming the take.
A blank line parts two roles and the columns' heads stand once.  Every column is sized over the
rows the widest `within` shows, so a knob step that brings in a row with a longer name and more
efforts than any other leaves every row's line as long as it was.  On 80 cells, where the notes
leave a line under 8 cells, they go under their row and the row keeps one line.  On 40 cells a
row folds and its mark takes a line of its own above its name, the pointer's on the first role's
pick.

Black-box, as tests/test_key_models_rows_drawn_as_c.py: the program `AK_BIN` names in a terminal,
its harness a fake listing an invented model, the boards held as just asked with invented rows;
judged by the screen.  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, lines
from test_key_models_rows_drawn_as_c import boards

# Per release and effort Omniscience, which alone parts them on review, a point of it a fifth of
# a point of quality, and cost a task.  Review within 4 of the best, 100: Bolt 3 at 98 the pick,
# no harness of yours running it, and Acme Max 5 high at 97 what `r` takes.  Zephyr's low, at 91,
# is the sixth row of the front, shown from within 5 on, its other efforts dearer and worse: the
# longest name and the most efforts of any row.
ROWS = [("acme-max-5", "Acme Max 5", "medium", 36, 5.0),
        ("acme-max-5", "Acme Max 5", "high", 45, 10.0),
        ("acme-max-5", "Acme Max 5", "max", 60, 20.0),
        ("bolt-3", "Bolt 3", None, 50, 3.0), ("crux-2", "Crux 2", None, 20, 2.0),
        *(("zephyr-long-context-9", "Zephyr Long Context 9", effort, omniscience, cost)
          for effort, omniscience, cost in (("minimal", 10, 1.2), ("low", 15, 1.0),
                                             ("medium", 12, 1.4), ("high", 14, 1.6),
                                             ("xhigh", 13, 1.8))),
        ("dune-1", "Dune 1", None, 0, 0.5)]
ROW = r"[ ›] (.{7})  (\S.*?) +([━╸─]{8,}) +(\d+\.\d) +\$\d+\.\d\d(?:  .+)?"


def drawn(shown):
    """(mark, name and effort, line, quality) of each row of `shown` drawn on one line."""
    return [found.groups() for found in map(lambda line: re.fullmatch(ROW, line), shown) if found]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer("models", "acme-max-5\tAcme Max 5\tlow medium high max\n")

    def setUp(self):
        akconfig.write(self.home, {"max": {"harness": "claude", "model": "acme-max-5",
                                           "effort": "high"}}, settings={"within": 4})
        self.home.write(".agentkit/state/boards.json", boards(ROWS))
        (self.home.path / ".agentkit/state/matrix.json").unlink(missing_ok=True)  # answered anew

    def models(self, width):
        """`r` on `c` in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, size=(width, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, lines(term.wait("comparing all 5 models"))

    def test_the_pick_and_what_r_takes_stand_before_their_names(self):
        _, shown = self.models(100)
        reviews = drawn(shown[shown.index("  reviews"):])
        self.assertEqual([(mark.rstrip(), " ".join(name.split()), quality)
                          for mark, name, _, quality in reviews[:3]],
                         [("", "Acme Max 5 ▰▰▰ max", "100.0"), ("★ pick", "Bolt 3", "98.0"),
                          ("r takes", "Acme Max 5 ▰▰▱ high", "97.0")])
        # `r takes` is a row's mark alone, never words under the pick
        self.assertEqual(sum("r takes" in line for line in shown),
                         sum(mark == "r takes" for mark, *_ in drawn(shown)))

    def test_a_blank_line_parts_the_roles_and_the_columns_heads_stand_once(self):
        _, shown = self.models(100)
        for head in ("  builds", "  reviews"):
            at = shown.index(head)
            self.assertEqual(shown[at - 1], "")
            self.assertNotEqual(shown[at - 2], "")
        self.assertEqual(sum("quality" in line for line in shown), 1)
        self.assertRegex(next(line for line in shown if "quality" in line), r"^  orch +quality")

    def test_a_knob_step_that_brings_in_a_wider_row_moves_no_line(self):
        term, shown = self.models(100)
        names = lambda rows: [name.split("  ")[0] for _, name, *_ in rows]
        before = drawn(shown)
        self.assertNotIn("Zephyr Long Context 9", names(before))
        term.keys("Right")
        after = drawn(lines(term.wait("within 5 points")))
        self.assertIn("Zephyr Long Context 9", names(after))
        self.assertEqual({len(line) for _, _, line, _ in before + after},
                         {len(before[0][2])})

    def test_on_80_cells_the_notes_go_under_their_row_before_it_folds(self):
        _, shown = self.models(80)
        reviews = shown[shown.index("  reviews"):]
        self.assertEqual([mark.rstrip() for mark, *_ in drawn(reviews)[:3]],
                         ["", "★ pick", "r takes"])
        at = next(number for number, line in enumerate(reviews) if "★ pick" in line)
        self.assertEqual(reviews[at + 1], " " * 13 + "no harness")

    def test_on_40_cells_a_mark_takes_a_line_above_its_name(self):
        _, shown = self.models(40)
        self.assertEqual(next(line for line in shown if "★ pick" in line), "›   ★ pick")
        at = shown.index("    ★ pick", shown.index("  reviews"))
        self.assertEqual(shown[at + 1], "    Bolt 3")
        self.assertRegex(shown[at + 2], r"^    [━╸─]{8,} +98\.0 +\$3\.00")


if __name__ == "__main__":
    unittest.main()
