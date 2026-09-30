"""A model's effort on `c` reads as signal bars, and its highest level shimmers.

Beside each effort word stands a bar for every level that model offers, rising in height
(`▂▃▅▆█` for five), filled up to its effort and the rest dim; a model with one effort is its
word alone, with neither bars nor arrows.  A step raises the one bar it fills into place, or
lowers the one it empties, on the menu's animation clock, and a step onto the model's highest
level sends one light through the word, once.  Without UTF-8 each filled level is a `|`, and
under NO_COLOR nothing moves.

Each screen is `menu.show_config` in a child on a pty of its own, through
tests/test_config_matrix.py's Screen: a temporary HOME whose config is the shipped default plus
a Haiku, the catalog faked (Haiku takes only `none`, Opus low to max), the seat `fix-api`.  The
cells a frame writes are read back from where it places the cursor.  Nothing here reads or
writes the owner's ~/.agentkit, and the only process signalled is the test's own child.
"""

import re
import time
import unittest
from unittest.mock import patch

from test_config_matrix import DOWN, ENTER, EFFORT_KEYS, RIGHT, UP, Screen, row
from agentkit import motion, terminal

PLACE = re.compile(r"\x1b\[(\d+);(\d+)H")      # where a frame writes a cell
BAR = re.compile(rf"(\x1b\[[0-9;]*m)?[{terminal.SIGNAL}]")
LIT = "38;"     # a colour of its own: a dim bar's, or the light's on a letter


def drawn(screen):
    """The last whole screen's lines as written, colours and all."""
    part = [part for part in screen.text().split("\x1b[H") if "\x1b[J" in part][-1]
    return part.split("\x1b[J")[0].split("\n")


def filled(screen, name):
    """How many of `name`'s bars are drawn in the foreground, with no colour of their own."""
    line = next(line for line in drawn(screen)
                if terminal.ANSI.sub("", line)[2:].split(" ")[0] == name)
    return BAR.findall(line).count("")


def moved(screen, keys):
    """Keys, then every cell the frames after them wrote until the screen is still:
    [(row, column, what it shows, as written)]."""
    mark = len(screen.text())
    screen.press(keys)
    began, size, quiet = time.monotonic(), len(screen.text()), time.monotonic()
    while time.monotonic() - began < 1.0 or time.monotonic() - quiet < 0.3:
        time.sleep(0.02)
        if len(screen.text()) != size:
            size, quiet = len(screen.text()), time.monotonic()
    parts, cells = PLACE.split(screen.text()[mark:]), []
    for at, column, text in zip(parts[1::3], parts[2::3], parts[3::3]):
        text = text.split("\x1b[H")[0]            # a whole draw after it is no frame's
        cells.append((int(at), int(column), terminal.ANSI.sub("", text), text))
    return cells


def places(lines, name):
    """`name`'s row on the terminal, the column of its effort word and of its first bar."""
    number, line = row(lines, name)
    return (number, line.index("‹") + 3,
            next(at for at, cell in enumerate(line) if cell in terminal.SIGNAL) + 1)


class EffortBars(unittest.TestCase):
    def test_each_model_has_a_bar_a_level_filled_to_its_effort(self):
        screen = Screen(self)
        lines = screen.frame()
        # Claude's five, Codex's and Muse's six, Grok's four, Gemini Flash's three and MiMo's
        # two, each filled to its effort in the shipped default
        for name, effort, bars, lit in (
                ("fable", "xhigh", "▂▃▅▆█", 4), ("opus", "xhigh", "▂▃▅▆█", 4),
                ("astra", "xhigh", "▁▃▄▅▇█", 4), ("spark", "xhigh", "▁▃▄▅▇█", 5),
                ("grok", "xhigh", "▂▄▆█", 4), ("gemini", "high", "▃▅█", 3),
                ("mimo", "high", "▄█", 2)):
            with self.subTest(name=name):
                self.assertEqual(row(lines, name)[1].split()[-4:], ["‹", effort, "›", bars])
                self.assertEqual(filled(screen, name), lit)
        screen.leave()

    def test_a_model_with_one_effort_is_its_word_alone(self):
        screen = Screen(self)
        lines = screen.frame()
        self.assertEqual(row(lines, "haiku")[1].split(), ["haiku", "claude", "○", "□", "□",
                                                          "xhigh"])
        screen.press(DOWN * 2 + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)
        cells = moved(screen, ENTER)                    # onto none, its only effort
        lines = screen.frame()
        self.assertEqual(row(lines, "haiku")[1].split(), ["›", "haiku", "claude", "○", "□", "□",
                                                          "none"])
        self.assertEqual([cell for cell in cells if cell[0] == row(lines, "haiku")[0]], [])
        self.assertEqual(screen.saved()["models"]["haiku"]["effort"], "none")
        screen.leave()

    def test_a_step_moves_its_one_bar_and_the_highest_shimmers_once(self):
        screen = Screen(self)
        lines = screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)
        number, word, bars = places(lines, "opus")
        # down from xhigh: its fourth bar lowers from its height to nothing, then stands dim
        cells = moved(screen, f"\x1b[<0;{word - 2};{number}M\x1b[<0;{word - 2};{number}m"
                      .encode())
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "high")
        self.assertEqual({(at, column) for at, column, _, _ in cells}, {(number, bars + 3)})
        heights = [(" " + terminal.SIGNAL).index(text) for _, _, text, _ in cells]
        self.assertEqual(heights[:-1], sorted(heights[:-1], reverse=True))
        self.assertLess(min(heights), 5, "lowered")
        self.assertEqual(cells[-1][2], "▆")
        self.assertIn(LIT, cells[-1][3])                # and dim
        self.assertEqual(filled(screen, "opus"), 3)
        # up again: the same bar rises from nothing into place, in the foreground
        cells = moved(screen, ENTER)
        self.assertEqual({(at, column) for at, column, _, _ in cells}, {(number, bars + 3)})
        heights = [(" " + terminal.SIGNAL).index(text) for _, _, text, _ in cells]
        self.assertEqual(heights, sorted(heights))
        self.assertLess(heights[0], 5, "risen")
        self.assertEqual(cells[-1][2], "▆")
        self.assertNotIn(LIT, cells[-1][3])
        # up onto max, Opus's highest: its fifth bar rises, and one light crosses the word
        cells = moved(screen, ENTER)
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "max")
        self.assertEqual({column for at, column, _, _ in cells if at == number},
                         {bars + 4, word, word + 1, word + 2})
        lit = {}
        for order, (_, column, text, written) in enumerate(cells):
            if column in (word, word + 1, word + 2):
                self.assertEqual(text, "max"[column - word])
                if LIT in written:
                    lit.setdefault(column, []).append(order)
        self.assertEqual([len(lit.get(column, [])) for column in (word, word + 1, word + 2)],
                         [1, 1, 1], "each letter lit once")
        self.assertLess(lit[word], lit[word + 1])       # left to right
        self.assertLess(lit[word + 1], lit[word + 2])
        self.assertNotIn(LIT, [cell for cell in cells if cell[1] == word + 2][-1][3])
        # and once: drawn again, moving off it and back, it is still
        for keys in (DOWN, UP):
            cells = moved(screen, keys)
            self.assertEqual([cell for cell in cells if cell[0] == number], [])
        screen.leave()

    def test_without_utf8_a_filled_level_is_a_bar_and_nothing_else_is(self):
        screen = Screen(self, env={"LANG": "C", "LC_ALL": ""})
        lines = screen.frame()
        self.assertEqual(row(lines, "opus")[1].split()[-4:], ["<", "xhigh", ">", "||||"])
        self.assertEqual(row(lines, "gemini")[1].split()[-4:], ["<", "high", ">", "|||"])
        self.assertEqual(row(lines, "haiku")[1].split()[-1], "xhigh")
        self.assertNotIn("<", row(lines, "haiku")[1])
        screen.leave()

    def test_under_no_color_nothing_moves(self):
        screen = Screen(self, env={"NO_COLOR": "1"})
        lines = screen.frame()
        self.assertEqual(row(lines, "opus")[1].split()[-1], "▂▃▅▆")   # nothing to dim the rest
        screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)
        self.assertEqual(moved(screen, ENTER), [])
        self.assertEqual(row(screen.frame(), "opus")[1].split()[-2:], ["›", "▂▃▅▆█"])
        screen.leave()

    def test_a_bar_takes_about_150_ms_and_the_light_about_600(self):
        with patch.object(terminal, "colour_depth", return_value=256):
            rise, until = motion.rising("█", True, 10.0)
            self.assertEqual(until, 10.15)
            self.assertEqual([rise(10.0 + t) for t in (0, 0.075)], [" ", "▄"])
            self.assertEqual(rise(10.15), "█")
            lower, _ = motion.rising("█", False, 10.0)
            self.assertEqual(lower(10.0), "█")
            self.assertEqual(lower(10.15), terminal.styled("█", "dim"))
            letters, until = motion.shimmering("max", 10.0)
            self.assertEqual(until, 10.6)
            for t, at in ((0.1, 0), (0.3, 1), (0.5, 2), (0.65, None)):
                self.assertEqual([LIT in letter(10.0 + t) for letter in letters],
                                 [n == at for n in range(3)])


if __name__ == "__main__":
    unittest.main()
